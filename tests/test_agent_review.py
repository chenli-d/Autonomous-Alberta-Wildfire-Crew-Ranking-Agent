import copy
import json
import os
import unittest
from unittest.mock import Mock, patch

import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.agent_review import build_agent_input, review_crew_cut, INPUT_FIELDS
from app.agent_validation import validate_agent_decision, apply_agent_decision
from app.review_service import select_review_candidates


def records():
    return [{"fire_id": f"2024:F{i}", "allocation_rank": i, "rank": 100+i,
             "rf_probability": .5, "status": "kept" if i <= 2 else "no_crew",
             "nearest_community_distance_km": i, "nearest_community": "Example",
             "y": "SECRET", "CURRENT_SIZE": "SECRET", "future_outcome": "SECRET"}
            for i in range(1, 6)]


def decision(kind="KEEP_ORIGINAL", promote=None, displace=None):
    return {"decision": kind, "promote_fire_id": promote, "displace_fire_id": displace,
            "reason": "Evidence remains ambiguous.", "evidence": ["Probabilities are equal."]}


class AgentTests(unittest.TestCase):
    def test_sanitized_input_keep_and_swap(self):
        rows = records()
        before = copy.deepcopy(rows)
        candidates = select_review_candidates(rows, 2, 2)
        payload = build_agent_input(candidates)
        self.assertNotIn("SECRET", json.dumps(payload))
        self.assertEqual(set(payload["last_kept"]), set(INPUT_FIELDS))
        self.assertNotIn("LATITUDE", payload["last_kept"])
        original = {r["fire_id"]: r["status"] == "kept" for r in rows}
        _, final = validate_agent_decision(json.dumps(decision()), rows, 2, 2)
        self.assertEqual(final, original)
        swap = decision("SWAP", "2024:F3", "2024:F2")
        final = apply_agent_decision(swap, rows, 2, 2)
        self.assertEqual(sum(final.values()), 2)
        self.assertEqual([k for k in final if final[k] != original[k]], ["2024:F2", "2024:F3"])
        self.assertEqual(rows, before)

    def test_invalid_outputs_never_mutate(self):
        rows = records()
        before = copy.deepcopy(rows)
        bad = ["not json", {}, decision("OTHER"), decision(promote="2024:F3"),
               decision("SWAP", "2024:F5", "2024:F2"),
               decision("SWAP", "2024:F3", "2024:F1"),
               decision("SWAP", "2024:F2", "2024:F2"),
               {**decision(), "extra": 1}, {**decision(), "evidence": "wrong"},
               {**decision(), "promote_fire_id": []}, {**decision(), "reason": ""}]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises((ValueError, TypeError)):
                validate_agent_decision(raw, rows, 2, 2)
        with self.assertRaises(ValueError):
            validate_agent_decision(decision(), rows, 3, 3)
        self.assertEqual(rows, before)

    def test_single_api_request_sanitization_and_errors(self):
        payload = build_agent_input(select_review_candidates(records(),2,2))
        payload["last_kept"]["y"] = "SECRET"
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(decision())}}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), patch("app.agent_review.requests.post", return_value=response) as post:
            self.assertEqual(json.loads(review_crew_cut(payload)), decision())
            post.assert_called_once()
            body = post.call_args.kwargs["json"]
            self.assertNotIn("SECRET", json.dumps(body))
            self.assertNotIn("test-key", json.dumps(body))
            self.assertTrue(body["response_format"]["json_schema"]["strict"])
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), patch("app.agent_review.requests.post") as post:
            with self.assertRaises(ValueError):
                review_crew_cut(payload)
            post.assert_not_called()
        for failure in (requests.Timeout(), requests.ConnectionError()):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch("app.agent_review.requests.post", side_effect=failure) as post:
                with self.assertRaisesRegex(ValueError, "unavailable"):
                    review_crew_cut(payload)
                post.assert_called_once()
        for status, choice in [(401, {}), (200, {"finish_reason": "length", "message": {}}),
                               (200, {"finish_reason": "stop", "message": {"refusal": "refused"}})]:
            response.status_code = status
            response.json.return_value = {"choices": [choice]}
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch("app.agent_review.requests.post", return_value=response):
                with self.assertRaises(ValueError):
                    review_crew_cut(payload)


UI_SCRIPT = '''
from app.agent_view import show_agent_review
from app.review_service import select_review_candidates
rows = [{"fire_id":f"2024:F{i}", "allocation_rank":i, "rank":100+i,
         "rf_probability":.5, "status":"kept" if i<=2 else "no_crew",
         "nearest_community_distance_km":float(i)} for i in range(1,6)]
show_agent_review(rows, select_review_candidates(rows,2,2),
                  {"H":2, "H_cut":2, "allocation_date":"2024-07-16"})
'''


class AgentUITests(unittest.TestCase):
    def test_explicit_apply_duplicate_and_stale(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch("app.agent_view.review_crew_cut", return_value=json.dumps(decision("SWAP", "2024:F3", "2024:F2"))) as call:
            app = AppTest.from_string(UI_SCRIPT).run()
            call.assert_not_called()
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.session_state["final_crew_assignments"]["2024:F2"])
            self.assertFalse(app.session_state["final_crew_assignments"]["2024:F3"])
            app.button[1].click().run()
            self.assertFalse(app.exception)
            self.assertFalse(app.session_state["final_crew_assignments"]["2024:F2"])
            self.assertTrue(app.session_state["final_crew_assignments"]["2024:F3"])
            self.assertTrue(app.button[1].disabled)
            self.assertEqual(call.call_count, 1)
            with patch.dict(os.environ, {"OPENAI_MODEL": "different-model"}):
                app.run()
                self.assertTrue(app.session_state["final_crew_assignments"]["2024:F2"])
                self.assertNotIn("agent_trace", app.session_state)

    def test_missing_key_keep_and_rejection(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            app = AppTest.from_string(UI_SCRIPT).run()
            self.assertTrue(app.button[0].disabled)
        for raw, valid in [(json.dumps(decision()), True), ("broken", False)]:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), patch("app.agent_view.review_crew_cut", return_value=raw):
                app = AppTest.from_string(UI_SCRIPT).run()
                app.button[0].click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["agent_trace"]["validation"]["valid"], valid)
                self.assertEqual(sum(app.session_state["final_crew_assignments"].values()), 2)
                self.assertEqual(len(app.button), 1)


if __name__ == "__main__":
    unittest.main()
