import copy
import json
import os
import unittest
from unittest.mock import patch

import test_assessment as assessment_fixtures


def swap_response():
    return json.dumps({"decision": "SWAP", "promote_fire_id": "2024:F2",
                       "displace_fire_id": "2024:F1", "reason": "Boundary trade-off", "evidence": []})


def button(app, label):
    return next(item for item in app.button if item.label == label)


class HumanReviewTests(unittest.TestCase):
    app = assessment_fixtures.CombinedUITests.app
    snapshot = assessment_fixtures.CombinedUITests.snapshot

    def reviewed_app(self):
        app = self.app()
        button(app, "Run assessment").click().run(timeout=30)
        self.assertFalse(app.exception)
        return app

    def test_accept_and_reject_preserve_model_and_lock_decision(self):
        for choice, expected, status in [
                ("Accept agent reranking", ["2024:F2", "2024:F1"], "Agent proposal accepted"),
                ("Keep model ranking", ["2024:F1", "2024:F2"], "Original model ranking retained")]:
            source = self.snapshot()
            before = copy.deepcopy(source)
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
                 patch("app.assessment_service.run_assessment", return_value=source) as model, \
                 patch("app.agent_view.review_crew_cut", return_value=swap_response()) as agent:
                app = self.reviewed_app()
                self.assertTrue(any(item.value == "Pending human review" for item in app.info))
                self.assertNotIn("final_ranking", app.session_state)
                self.assertNotIn("human_decision", app.session_state)
                original = copy.deepcopy(app.session_state["assessment"]["records"])
                proposal = copy.deepcopy(app.session_state["agent_trace"]["proposed_ranking"])
                button(app, choice).click().run(timeout=30)
                self.assertFalse(app.exception)
                final = app.session_state["final_ranking"]
                self.assertEqual([row["fire_id"] for row in final], expected)
                self.assertEqual([row["final_rank"] for row in final], [1, 2])
                self.assertEqual(app.session_state["assessment"]["records"], original)
                self.assertEqual(app.session_state["agent_trace"]["proposed_ranking"], proposal)
                self.assertEqual(source, before)
                for label in ("Accept agent reranking", "Keep model ranking"):
                    self.assertTrue(button(app, label).disabled)
                rendered = [item.value for item in app.info] + [item.value for item in app.success]
                self.assertIn(status, rendered)
                human = app.session_state["human_decision"]
                self.assertEqual(human["run_id"], app.session_state["assessment"]["run_id"])
                self.assertEqual(human["fingerprint"], app.session_state["agent_trace"]["fingerprint"])
                self.assertEqual(app.session_state["agent_trace"]["human_decision"], human)
                self.assertEqual(app.session_state["agent_trace"]["final_ranking"], final)
                app.selectbox[0].select("2024:F2").run(timeout=30)
                self.assertEqual(app.session_state["human_decision"], human)
                self.assertEqual(app.session_state["final_ranking"], final)
                model.assert_called_once()
                agent.assert_called_once()

    def test_new_run_resets_decisions_and_failed_model_drops_all_state(self):
        for choice in ("Accept agent reranking", "Keep model ranking"):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
                 patch("app.assessment_service.run_assessment", return_value=self.snapshot()) as model, \
                 patch("app.agent_view.review_crew_cut", return_value=swap_response()) as agent:
                app = self.reviewed_app()
                button(app, choice).click().run(timeout=30)
                first = app.session_state["assessment"]["run_id"]
                button(app, "Run assessment").click().run(timeout=30)
                self.assertNotEqual(app.session_state["assessment"]["run_id"], first)
                self.assertNotIn("human_decision", app.session_state)
                self.assertNotIn("final_ranking", app.session_state)
                self.assertFalse(button(app, "Accept agent reranking").disabled)
                button(app, choice).click().run(timeout=30)
                model.side_effect = OSError("Model failed")
                button(app, "Run assessment").click().run(timeout=30)
                self.assertFalse(app.exception)
                for key in ("assessment", "agent_trace", "human_decision", "final_ranking"):
                    self.assertNotIn(key, app.session_state)
                self.assertEqual(agent.call_count, 2)

    def test_proposal_invalidation_clears_human_state(self):
        for invalidation in ("refresh", "run", "fingerprint", "context", "unavailable"):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
                 patch("app.assessment_service.run_assessment", return_value=self.snapshot()), \
                 patch("app.agent_view.review_crew_cut", return_value=swap_response()) as agent:
                app = self.reviewed_app()
                button(app, "Accept agent reranking").click().run(timeout=30)
                if invalidation == "refresh":
                    with patch("app.community_service.fetch_communities", return_value=app.session_state["community_point_fetch"]):
                        button(app, "Refresh community data").click().run(timeout=30)
                elif invalidation == "run":
                    app.session_state["agent_trace"] = {**app.session_state["agent_trace"], "run_id": "old-run"}
                    app.run(timeout=30)
                elif invalidation == "fingerprint":
                    with patch.dict(os.environ, {"OPENAI_MODEL": "different-model"}):
                        app.run(timeout=30)
                elif invalidation == "context":
                    app.session_state["assessment"]["review_error"] = "Context unavailable"
                    app.run(timeout=30)
                else:
                    app.session_state["agent_trace"]["validation"] = {"valid": False, "message": "Unavailable"}
                    app.run(timeout=30)
                self.assertFalse(app.exception, invalidation)
                self.assertNotIn("human_decision", app.session_state, invalidation)
                self.assertNotIn("final_ranking", app.session_state, invalidation)
                self.assertNotIn("Accept agent reranking", [item.label for item in app.button])
                agent.assert_called_once()

    def test_failed_acceptance_revalidation_leaves_pending(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
             patch("app.assessment_service.run_assessment", return_value=self.snapshot()), \
             patch("app.agent_view.review_crew_cut", return_value=swap_response()):
            app = self.reviewed_app()
            app.session_state["agent_trace"]["raw_structured_response"] = swap_response().replace("2024:F1", "2024:UNKNOWN")
            button(app, "Accept agent reranking").click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertNotIn("human_decision", app.session_state)
            self.assertNotIn("final_ranking", app.session_state)
            self.assertFalse(button(app, "Accept agent reranking").disabled)
            self.assertTrue(any(item.value == "Pending human review" for item in app.info))

    def test_keep_has_model_final_ranking_without_decision_buttons(self):
        response = json.dumps({"decision": "KEEP_ORIGINAL", "promote_fire_id": None,
                               "displace_fire_id": None, "reason": "Keep RF order", "evidence": []})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
             patch("app.assessment_service.run_assessment", return_value=self.snapshot()), \
             patch("app.agent_view.review_crew_cut", return_value=response):
            app = self.reviewed_app()
            self.assertTrue(any(item.value == "No reranking proposed" for item in app.info))
            self.assertEqual([row["fire_id"] for row in app.session_state["final_ranking"]], ["2024:F1", "2024:F2"])
            self.assertNotIn("human_decision", app.session_state)
            self.assertNotIn("Accept agent reranking", [item.label for item in app.button])

    def test_model_csv_bytes_unchanged_after_both_human_actions(self):
        # Use real model-output loading, then verify human actions never rewrite its files.
        from test_assessment import AssessmentTests, DAY
        from app.assessment_service import run_assessment
        fixture = AssessmentTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for label in ("Accept agent reranking", "Keep model ranking"):
            with patch("app.assessment_service.subprocess.run", side_effect=fixture.generate):
                snapshot = run_assessment(fixture.root, 2022, 2023, 2024, DAY, 2)
            paths = [fixture.output / f"allocation_{DAY}.csv", fixture.output / "ranking_2024.csv", fixture.output / "metrics.json"]
            before = {path: path.read_bytes() for path in paths}
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
                 patch("app.assessment_service.run_assessment", return_value=snapshot), \
                 patch("app.agent_view.review_crew_cut", return_value=swap_response()):
                app = self.reviewed_app()
                button(app, label).click().run(timeout=30)
                self.assertFalse(app.exception)
            self.assertEqual({path: path.read_bytes() for path in paths}, before)
