import csv
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app.assessment_service import run_assessment
from app.community_service import CommunityFetch
from test_proximity import community

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2024, 7, 16)


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name).resolve()
        self.output = self.root / "outputs/ui_demo"
        self.fields = ["fire_id", "rank", "rf_probability", "baseline_rank", "status", "y"]
        self.rows = [{"fire_id": "2024:F1", "rank": 1, "rf_probability": .8,
                      "baseline_rank": 2, "status": "kept", "y": "SECRET"},
                     {"fire_id": "2024:F2", "rank": 2, "rf_probability": .7,
                      "baseline_rank": 1, "status": "displaced", "y": "SECRET"}]
        write_csv(self.root / "data/raw/fp-historical-wildfire-data-2006-2025.csv",
                  ["YEAR", "FIRE_NUMBER", "ASSESSMENT_DATETIME", "LATITUDE", "LONGITUDE"],
                  [{"YEAR": 2024, "FIRE_NUMBER": f"F{i}", "ASSESSMENT_DATETIME": DAY.isoformat(),
                    "LATITUDE": 56, "LONGITUDE": -112} for i in (1, 2)])

    def generate(self, *args, **kwargs):
        write_csv(self.output / f"allocation_{DAY}.csv", self.fields, self.rows)
        write_csv(self.output / "ranking_2024.csv", self.fields,
                  [{**r, "rank": r["rank"] + 20} for r in self.rows])
        (self.output / "metrics.json").write_text(json.dumps({"allocation_date": str(DAY), "H": 2, "H_cut": 1}))

    def run_model(self, day=DAY, **kwargs):
        return run_assessment(self.root, 2022, 2023, 2024, day, 2, **kwargs)

    def test_command_fresh_results_and_annual_ranks(self):
        with patch("app.assessment_service.subprocess.run", side_effect=self.generate) as run:
            first = self.run_model()
            self.rows[0]["rf_probability"] = .9
            second = self.run_model()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args.args[0], [sys.executable, str(self.root / "model/train_rf.py"),
                         "--train-start", "2022", "--train-end", "2023", "--test-year", "2024",
                         "--crews", "2", "--allocation-date", str(DAY), "--run-name", "ui_demo"])
        self.assertEqual(run.call_args.kwargs, {"cwd": self.root, "capture_output": True, "text": True, "check": True})
        self.assertEqual(first["records"][0]["rf_probability"], .8)
        self.assertEqual(second["records"][0]["rf_probability"], .9)
        self.assertEqual(second["records"][0]["rank"], 1)
        self.assertEqual(second["annual_ranks"]["2024:F1"], 21)
        self.assertNotIn("SECRET", repr(second))
        self.assertIsNone(second["review_error"])

    def test_validation_before_subprocess(self):
        for start, end, year, day, crews in [(2023, 2022, 2024, DAY, 2), (2022, 2023, 2023, DAY, 2),
                                           (2022, 2023, 2025, DAY, 2), (2022, 2023, 2024, date(2023, 7, 16), 2),
                                           (2022, 2023, 2024, DAY, 0)]:
            with patch("app.assessment_service.subprocess.run") as run, self.assertRaises(ValueError):
                run_assessment(self.root, start, end, year, day, crews)
            run.assert_not_called()

    def test_failure_and_missing_output_never_reuse_old_csv(self):
        self.generate()
        with patch("app.assessment_service.subprocess.run", side_effect=subprocess.CalledProcessError(2, "model", stderr="Bad input")):
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_model()
        self.assertFalse((self.output / f"allocation_{DAY}.csv").exists())
        self.generate()
        with patch("app.assessment_service.subprocess.run"):
            with self.assertRaises(FileNotFoundError):
                self.run_model()

    def test_malformed_and_empty_output(self):
        def malformed(*args, **kwargs):
            write_csv(self.output / f"allocation_{DAY}.csv", ["fire_id"], [])
        with patch("app.assessment_service.subprocess.run", side_effect=malformed), self.assertRaisesRegex(ValueError, "columns"):
            self.run_model()
        self.rows = []
        with patch("app.assessment_service.subprocess.run", side_effect=self.generate):
            result = self.run_model()
        self.assertEqual(result["records"], [])

    def test_other_date_and_optional_context_failure(self):
        other = date(2024, 7, 17)
        def generate(*args, **kwargs):
            self.generate()
            (self.output / f"allocation_{DAY}.csv").rename(self.output / f"allocation_{other}.csv")
        with patch("app.assessment_service.subprocess.run", side_effect=generate):
            result = self.run_model(other)
        self.assertEqual(result["records"], [])
        self.assertIn("date", result["review_error"])

        write_csv(self.root / "data/raw/fp-historical-wildfire-data-2006-2025.csv",
                  ["YEAR", "FIRE_NUMBER", "ASSESSMENT_DATETIME", "LATITUDE", "LONGITUDE"],
                  [{"YEAR": 2024, "FIRE_NUMBER": f"F{i}", "ASSESSMENT_DATETIME": str(other),
                    "LATITUDE": 56, "LONGITUDE": -112} for i in (1, 2)])
        def matching_generate(*args, **kwargs):
            generate()
            (self.output / "metrics.json").write_text(json.dumps({"allocation_date": str(other), "H": 2, "H_cut": 1}))
        with patch("app.assessment_service.subprocess.run", side_effect=matching_generate):
            result = self.run_model(other)
        self.assertEqual(len(result["records"]), 2)
        self.assertIsNone(result["review_error"])


class CombinedUITests(unittest.TestCase):
    def app(self):
        app = AppTest.from_file(str(ROOT / "streamlit_app.py"))
        app.session_state["community_point_fetch"] = CommunityFetch(communities=[community()])
        app.session_state["community_point_fetch_time"] = time.time()
        return app.run(timeout=30)

    def snapshot(self, probability=.8):
        rows = [{"fire_id": f"2024:F{i}", "rank": i, "rf_probability": probability,
                 "baseline_rank": i, "status": "kept" if i == 1 else "displaced",
                 "LATITUDE": 56, "LONGITUDE": -112, "assessment_date": str(DAY)} for i in (1, 2)]
        return {"records": rows, "diagnostics": {"unmatched": 0, "invalid_dates": 0},
                "context": {"allocation_date": str(DAY), "H": 2, "H_cut": 1,
                            "allocations": {r["fire_id"]: {"allocation_rank": r["rank"], "status": r["status"]} for r in rows}},
                "annual_ranks": {r["fire_id"]: r["rank"] + 20 for r in rows}, "review_error": None,
                "settings": {"train_start": 2022, "train_end": 2023, "test_year": 2024, "assessment_date": DAY, "crews": 2}}

    def test_combined_action_once_and_session_persistence(self):
        response = json.dumps({"decision": "KEEP_ORIGINAL", "promote_fire_id": None,
                               "displace_fire_id": None, "reason": "Keep RF allocation", "evidence": ["Similar probabilities"]})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
             patch("app.assessment_service.run_assessment", side_effect=[self.snapshot(), self.snapshot(.9)]) as model, \
             patch("app.agent_view.review_crew_cut", return_value=response) as agent:
            app = self.app()
            model.assert_not_called()
            agent.assert_not_called()
            self.assertEqual([b.label for b in app.button], ["Run assessment"])
            app.button[0].click().run(timeout=30)
            self.assertFalse(app.exception)
            model.assert_called_once_with(ROOT, 2022, 2023, 2024, DAY, 10)
            agent.assert_called_once()
            self.assertEqual(agent.call_args.args[0]["last_kept"]["rank"], 21)
            self.assertEqual(app.dataframe[0].value.iloc[0]["rank"], 1)
            app.selectbox[0].select("2024:F2").run()
            app.run()
            self.assertEqual(model.call_count, 1)
            self.assertEqual(agent.call_count, 1)
            app.button[0].click().run(timeout=30)
            self.assertEqual(model.call_count, 2)
            self.assertEqual(agent.call_count, 2)
            self.assertEqual(app.dataframe[0].value.iloc[0]["rf_probability"], .9)
            self.assertNotIn("Run agent review", [b.label for b in app.button])

    def test_selected_settings_forwarded(self):
        with patch("app.assessment_service.run_assessment", return_value=self.snapshot()) as model:
            app = self.app()
            app.number_input[0].set_value(2018)
            app.number_input[1].set_value(2021)
            app.number_input[2].set_value(2022)
            app.number_input[3].set_value(15)
            app.date_input[0].set_value(date(2022, 6, 1))
            app.button[0].click().run(timeout=30)
            model.assert_called_once_with(ROOT, 2018, 2021, 2022, date(2022, 6, 1), 15)

    def test_combined_swap_requires_apply_and_does_not_repeat_run(self):
        response = json.dumps({"decision": "SWAP", "promote_fire_id": "2024:F2",
                               "displace_fire_id": "2024:F1", "reason": "Boundary trade-off",
                               "evidence": ["Similar probabilities"]})
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}), \
             patch("app.assessment_service.run_assessment", return_value=self.snapshot()) as model, \
             patch("app.agent_view.review_crew_cut", return_value=response) as agent:
            app = self.app()
            app.button[0].click().run(timeout=30)
            self.assertTrue(app.session_state["final_crew_assignments"]["2024:F1"])
            next(b for b in app.button if b.label == "Apply swap").click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertFalse(app.session_state["final_crew_assignments"]["2024:F1"])
            self.assertTrue(app.session_state["final_crew_assignments"]["2024:F2"])
            self.assertTrue(next(b for b in app.button if b.label == "Apply swap").disabled)
            model.assert_called_once()
            agent.assert_called_once()

    def test_failure_clears_stale_review_and_displays_diagnostics(self):
        for failure in (subprocess.CalledProcessError(2, "model", stderr="Training data unavailable"),
                        OSError("Cannot start interpreter"), ValueError("Missing ranking columns")):
            with patch("app.assessment_service.run_assessment", side_effect=failure), \
                 patch("app.agent_view.review_crew_cut") as agent:
                app = self.app()
                app.session_state["agent_trace"] = {"stale": True}
                app.button[0].click().run(timeout=30)
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
                self.assertNotIn("agent_trace", app.session_state)
                self.assertNotIn("assessment", app.session_state)
                self.assertFalse(app.dataframe)
                agent.assert_not_called()
                if isinstance(failure, subprocess.CalledProcessError):
                    self.assertIn("Training data unavailable", app.code[0].value)

    def test_missing_key_and_agent_failure_keep_rf_visible(self):
        for key, failure in [("", None), ("test", ValueError("Agent unavailable"))]:
            with patch.dict(os.environ, {"OPENAI_API_KEY": key}), \
                 patch("app.assessment_service.run_assessment", return_value=self.snapshot()), \
                 patch("app.agent_view.review_crew_cut", side_effect=failure) as agent:
                app = self.app()
                app.button[0].click().run(timeout=30)
                self.assertFalse(app.exception)
                self.assertEqual(len(app.dataframe[0].value), 2)
                self.assertEqual(agent.call_count, int(bool(key)))
