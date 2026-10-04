import time
import csv
import tempfile
import unittest
from pathlib import Path
from datetime import date
from unittest.mock import patch
import streamlit as st

from streamlit.testing.v1 import AppTest

from app.community_service import CommunityFetch
from test_proximity import community
from streamlit_app import parse_wildfires, load_wildfires
from app.map_view import create_overview_map, create_map


def row(timestamp="2024-07-16 18:00", **values):
    return {"YEAR": "2024", "FIRE_NUMBER": "PWF076", "ASSESSMENT_DATETIME": timestamp,
            "FIRE_START_DATE": "2024-07-15 12:00",
            "LATITUDE": "56.707233", "LONGITUDE": "-118.9744", **values}


class DailyDataTests(unittest.TestCase):
    def test_assessment_join_retains_cohort_and_coordinates(self):
        with tempfile.TemporaryDirectory() as folder:
            seed, source = Path(folder)/"seed.csv", Path(folder)/"source.csv"
            seed_rows = [row(hazard_score=".2"), row(FIRE_NUMBER="missing")]
            for record in seed_rows:
                record.pop("ASSESSMENT_DATETIME")
            source_rows = [row("2024-07-17 12:00", LATITUDE="0"), row(FIRE_NUMBER="unrelated")]
            for path, records in [(seed, seed_rows), (source, source_rows)]:
                with path.open("w", newline="") as file:
                    writer = csv.DictWriter(file, fieldnames=records[0].keys())
                    writer.writeheader()
                    writer.writerows(records)
            days, invalid = load_wildfires(str(seed), seed.stat().st_mtime_ns,
                                            str(source), source.stat().st_mtime_ns)
        self.assertEqual(list(days), [date(2024,7,17)])
        fire = days[date(2024,7,17)]["fires"][0]
        self.assertEqual(fire["latitude"], 56.707233)
        self.assertEqual(fire["hazard_score"], .2)
        self.assertEqual(invalid, 1)  # Unmatched IDs never fall back to start dates.

    def test_dates_filtering_and_coordinates(self):
        records = [row(), row("2024-07-16 6:00", FIRE_NUMBER="A"), row("2024-07-17 00:00"), row("bad")]
        for value in ("", "bad", "nan", "inf", "91"):
            records.append(row(LATITUDE=value))
        records.append(row(LONGITUDE="181"))
        records.append(row("2024-07-18", LATITUDE=None))
        days, invalid = parse_wildfires(records)
        self.assertEqual(list(days), [date(2024,7,16), date(2024,7,17), date(2024,7,18)])
        self.assertEqual(len(days[date(2024,7,16)]["fires"]), 2)
        self.assertEqual(days[date(2024,7,16)]["skipped"], 6)
        self.assertEqual(days[date(2024,7,18)]["fires"], [])
        self.assertEqual(invalid, 1)

    def test_optional_scores(self):
        for values, expected in [({},None), ({"hazard_score":"0"},0),
                                 ({"hazard_score":".2","rf_probability":".3"},.2),
                                 ({"hazard_score":"nan","rf_probability":".3"},.3),
                                 ({"rf_probability":"inf"},None)]:
            days, _ = parse_wildfires([row(**values)])
            self.assertEqual(days[date(2024,7,16)]["fires"][0]["hazard_score"], expected)

    def test_overview_markers_without_lines(self):
        days, _ = parse_wildfires([row(hazard_score="0"), row(FIRE_NUMBER="A")])
        fires = days[date(2024,7,16)]["fires"]
        view = create_overview_map(fires)
        self.assertEqual(sum(child.__class__.__name__ == "Marker" for child in view._children.values()), 2)
        html = view.get_root().render()
        self.assertNotIn("poly_line", html)
        self.assertNotIn("geo_json", html)
        self.assertIn("2024:PWF076", html)
        self.assertIn("Hazard score: 0.0", html)
        self.assertIn("Hazard score: 0.0", create_map("fire", 0, 0, [], 0.0).get_root().render())


class UITests(unittest.TestCase):
    def app(self, fetched):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app.py"))
        app.session_state["community_fetch"] = fetched
        app.session_state["community_fetch_time"] = time.time()
        return app.run(timeout=30)

    def test_sample_and_table(self):
        app = self.app(CommunityFetch(communities=[community()]))
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.selectbox[0].value, date(2024,7,16))
        self.assertEqual(app.selectbox[0].label, "Assessment day")
        self.assertEqual(app.selectbox[1].value, app.selectbox[1].options[0])
        self.assertNotIn("2024:PWF076", app.selectbox[1].options)
        self.assertEqual(len(app.selectbox[1].options), 18)
        self.assertIn("0 records skipped", app.caption[1].value)
        self.assertEqual(len(app.dataframe), 1)
        self.assertEqual(app.dataframe[0].value.iloc[0]["Community"], "Example")
        original_distance = app.dataframe[0].value.iloc[0]["Distance (km)"]
        app.selectbox[1].select("2024:MWF086").run()
        self.assertEqual(len(app.exception), 0)
        self.assertIn("2024:MWF086", app.subheader[1].value)
        self.assertNotEqual(app.dataframe[0].value.iloc[0]["Distance (km)"], original_distance)
        other_day = app.selectbox[0].options[-1]
        app.selectbox[0].select(date.fromisoformat(other_day)).run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.selectbox[1].value, app.selectbox[1].options[0])

    def test_failure_keeps_fire_map(self):
        app = self.app(CommunityFetch(errors=["City: unavailable"]))
        self.assertEqual(len(app.exception), 0)
        self.assertGreater(len(app.warning), 0)
        self.assertGreater(len(app.info), 0)

    def test_day_without_coordinates_skips_maps_and_api(self):
        st.cache_data.clear()
        with patch("csv.DictReader", return_value=[row(LATITUDE="nan")]), patch("app.community_service.fetch_communities") as fetch, patch("app.map_view.create_overview_map") as overview, patch("app.map_view.create_map") as detail:
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app.py")).run(timeout=30)
        st.cache_data.clear()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.selectbox), 1)
        self.assertEqual(len(app.subheader), 0)
        self.assertIn("No valid wildfire locations", app.info[0].value)
        fetch.assert_not_called()
        overview.assert_not_called()
        detail.assert_not_called()


if __name__ == "__main__":
    unittest.main()
