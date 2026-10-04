import time
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from app.community_service import CommunityFetch
from app.ranking_service import AVAILABLE_DATES, SAFE_FIELDS, join_rankings, load_rankings, map_record
from test_proximity import community


def ranking(identifier="2024:TEST", **values):
    return {"fire_id": identifier, "rank": "21", "rf_probability": ".532", "baseline_rank": "42",
            "y": "FUTURE_OUTCOME_SECRET", "CURRENT_SIZE": "FINAL_SIZE_SECRET",
            "future_outcome": "OTHER_OUTCOME_SECRET", **values}


def official(year="2024", number="TEST", timestamp="2024-07-16 6:00", **values):
    return {"YEAR": year, "FIRE_NUMBER": number, "ASSESSMENT_DATETIME": timestamp,
            "LATITUDE": "56.472313", "LONGITUDE": "-111.98066", **values}


class RankingTests(unittest.TestCase):
    def test_join_date_coordinates_and_allowlist(self):
        rows, diagnostics = join_rankings([ranking(), ranking("2023:TEST")],
                                          [official(number=" TEST "), official("2023", timestamp="2023-07-16 12:00")])
        self.assertEqual(len(rows), 1)
        self.assertEqual(diagnostics, {"unmatched": 0, "invalid_dates": 0})
        record = rows[0]
        self.assertEqual(record["LATITUDE"], 56.472313)
        self.assertEqual(record["LONGITUDE"], -111.98066)
        self.assertEqual(record["assessment_date"], "2024-07-16")
        self.assertEqual(record["rank"], 21)
        self.assertLessEqual(set(record), set(SAFE_FIELDS))
        for key in ("y", "CURRENT_SIZE", "future_outcome"):
            self.assertNotIn(key, record)
        self.assertNotIn("SECRET", repr(rows))

    def test_direct_dates_missing_fields_and_coordinates(self):
        rows, diagnostics = join_rankings([
            ranking(assessment_date="2024-07-16", rank="", rf_probability="nan", status="kept"),
            ranking("2024:OTHER", assessment_date="2024-07-17"),
            ranking("2024:BAD", assessment_date="bad"),
            ranking("2024:UNMATCHED", assessment_date="2024-07-16")],
            [official(timestamp="2024-07-17", LATITUDE="91", LONGITUDE=""), official(number="BAD")])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(map_record(row) is None for row in rows))
        test = next(r for r in rows if r["fire_id"] == "2024:TEST")
        self.assertIsNone(test["rf_probability"])
        self.assertEqual(test["status"], "kept")
        self.assertEqual(test["assessment_date"], "2024-07-16")
        self.assertEqual(diagnostics["unmatched"], 2)
        self.assertEqual(diagnostics["invalid_dates"], 1)

    def test_duplicates_and_unsupported_date(self):
        for ranked, source in [([ranking(), ranking()], [official()]), ([ranking()], [official(), official()])]:
            with self.assertRaises(ValueError):
                join_rankings(ranked, source)
        self.assertEqual(join_rankings([], [], date(2024,7,17))[0], [])

    def test_rank_sort_and_map_adapter(self):
        rows, _ = join_rankings([ranking("2024:B", rank=""), ranking("2024:C", rank="2"), ranking("2024:A", rank="2")],
                                [official(number=n) for n in "ABC"])
        self.assertEqual([r["fire_id"] for r in rows], ["2024:A", "2024:C", "2024:B"])
        self.assertEqual(set(map_record(rows[0])), {"fire_id", "latitude", "longitude", "hazard_score"})
        self.assertEqual(map_record(rows[0])["hazard_score"], .532)

    def test_actual_files(self):
        root = Path(__file__).resolve().parents[1]
        rows, diagnostics = load_rankings(root / "outputs/dev_recent/ranking_2024.csv",
                                          root / "data/raw/fp-historical-wildfire-data-2006-2025.csv")
        self.assertEqual(len(rows), 49)
        self.assertEqual(rows[0]["fire_id"], "2024:MWF086")
        self.assertEqual(rows[0]["rank"], 21)
        self.assertEqual(rows[0]["LATITUDE"], 56.472313)
        self.assertEqual(rows[0]["LONGITUDE"], -111.98066)
        self.assertEqual(diagnostics["unmatched"], 0)
        self.assertTrue(all(r["assessment_date"] == "2024-07-16" for r in rows))
        self.assertTrue(all(set(r).issubset(SAFE_FIELDS) for r in rows))
        self.assertTrue(all(map_record(r) is not None for r in rows))


class UITests(unittest.TestCase):
    def run_app(self, rows=None, failure=None):
        st.cache_data.clear()
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app.py"))
        app.session_state["community_point_fetch"] = CommunityFetch(communities=[community()])
        app.session_state["community_point_fetch_time"] = time.time()
        from app.review_service import load_allocation_context
        root = Path(__file__).resolve().parents[1]
        try:
            context = load_allocation_context(root / "outputs/dev_recent/allocation_2024-07-16.csv",
                                              root / "outputs/dev_recent/metrics.json")
            review_error = None
        except (OSError, ValueError) as error:
            context, review_error = None, str(error)
        snapshot = {"records": rows, "diagnostics": {"unmatched": 0, "invalid_dates": 0},
                    "context": context, "annual_ranks": {r["fire_id"]: r["rank"] for r in rows or []},
                    "review_error": review_error,
                    "settings": {"train_start": 2022, "train_end": 2023, "test_year": 2024,
                                 "assessment_date": date(2024, 7, 16), "crews": 10}}
        app.run(timeout=30)
        with patch("app.assessment_service.run_assessment", side_effect=failure, return_value=snapshot):
            app.button[0].click().run(timeout=30)
        return app

    def test_single_date_table_details_and_selection(self):
        rows, _ = join_rankings([ranking(), ranking("2024:OTHER", rank="22")], [official(), official(number="OTHER")])
        app = self.run_app(rows)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.date_input[0].value, AVAILABLE_DATES[0])
        self.assertEqual(len(app.number_input), 4)
        self.assertEqual(list(app.dataframe[0].value.columns), ["fire_id", "rank", "rf_probability", "baseline_rank", "nearest_community_distance_km", "community_proximity_rank"])
        self.assertIn("Fire details: 2024:TEST", [h.value for h in app.subheader])
        rendered = repr([df.value.to_dict() for df in app.dataframe])
        for forbidden in ("SECRET", "CURRENT_SIZE", "future_outcome"):
            self.assertNotIn(forbidden, rendered)
        for dataframe in app.dataframe:
            self.assertNotIn("y", dataframe.value.columns)
            if "Field" in dataframe.value:
                self.assertNotIn("y", dataframe.value["Field"].tolist())
        self.assertIn("N/A", rendered)
        with patch("app.ranking_service.load_rankings", return_value=(rows, {"unmatched":0,"invalid_dates":0})):
            app.selectbox[0].select("2024:OTHER").run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("Fire details: 2024:OTHER", [h.value for h in app.subheader])

    def test_missing_coordinates_still_shows_details(self):
        rows, _ = join_rankings([ranking()], [official(LATITUDE="nan")])
        with patch("app.map_view.create_overview_map") as overview, patch("app.community_service.fetch_communities") as fetch:
            app = self.run_app(rows)
        self.assertEqual(len(app.exception), 0)
        self.assertIn("Fire details: 2024:TEST", [h.value for h in app.subheader])
        self.assertTrue(any("proximity is unavailable" in info.value for info in app.info))
        overview.assert_not_called()
        fetch.assert_not_called()

    def test_selector_survives_empty_or_error(self):
        for rows, failure in [([], None), (None, OSError("Ranking file unavailable"))]:
            app = self.run_app(rows, failure)
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.date_input[0].value, AVAILABLE_DATES[0])
            self.assertEqual(len(app.selectbox), 0)


if __name__ == "__main__":
    unittest.main()
