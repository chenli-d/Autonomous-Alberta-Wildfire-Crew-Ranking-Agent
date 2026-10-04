import unittest
from unittest.mock import patch

from shapely.geometry import Point, Polygon

from app.community_service import fetch_communities
from app.proximity_service import (enrich_fire_proximity, find_nearest_community,
                                   find_nearest_community_points, valid_community_points)
from app.ranking_service import SAFE_FIELDS
from test_proximity import community, METADATA, feature
import test_ui as ui_fixtures
from app.ranking_service import join_rankings


class PointProximityTests(unittest.TestCase):
    def test_distances_ties_and_map_consistency(self):
        points = [community("Z", Point(1, 0), "0:2"), community("A", Point(1, 0), "0:3"),
                  community("A", Point(1, 0), "0:1")]
        nearest = find_nearest_community(0, 0, points)
        self.assertEqual(nearest["nearest_community"], "A")
        self.assertAlmostEqual(nearest["nearest_community_distance_km"], 111.195080, places=5)
        selected = find_nearest_community_points(0, 0, points)
        self.assertEqual(selected[0]["source_id"], "0:1")
        self.assertEqual(selected[0]["distance_km"], nearest["nearest_community_distance_km"])
        self.assertEqual(find_nearest_community(0, 1, points)["nearest_community_distance_km"], 0)

    def test_invalid_fire_and_community_data(self):
        points = [community("", Point(0, 0)), community("bad", Point(181, 0)),
                  community("polygon", Polygon([(0,0),(1,0),(0,1)])),
                  {"name":"missing"}, {"name":"empty", "geometry":Point()}, community("ok", Point(1, 0))]
        self.assertEqual(len(valid_community_points(points)), 1)
        self.assertIsNone(find_nearest_community(None, 0, points))
        self.assertIsNone(find_nearest_community(91, 0, points))
        self.assertIsNone(find_nearest_community(float("nan"), 0, points))
        self.assertIsNone(find_nearest_community(0, 0, []))

    def test_ranks_rf_order_safety_and_missing_data(self):
        records = [{"fire_id":"B", "LATITUDE":0, "LONGITUDE":0, "rank":21, "rf_probability":.5,
                    "y":1, "CURRENT_SIZE":500, "future_outcome":"secret", "nearest_community":"invented"},
                   {"fire_id":"A", "LATITUDE":0, "LONGITUDE":0, "rank":30},
                   {"fire_id":"C", "LATITUDE":None, "LONGITUDE":0, "rank":31},
                   {"fire_id":"D", "LATITUDE":0, "LONGITUDE":1, "rank":40}]
        result = enrich_fire_proximity(records, [community("Known", Point(0,0))])
        self.assertEqual([r["fire_id"] for r in result], ["B","A","C","D"])
        self.assertEqual([r["rank"] for r in result], [21,30,31,40])
        self.assertEqual([r["community_proximity_rank"] for r in result], [2,1,None,3])
        self.assertEqual(result[0]["rf_probability"], .5)
        self.assertEqual(result[1]["nearest_community_distance_km"], min(r["nearest_community_distance_km"] for r in result if r["nearest_community_distance_km"] is not None))
        self.assertTrue(all(set(r).issubset(set(SAFE_FIELDS) | {"nearest_community","nearest_community_distance_km","community_proximity_rank"}) for r in result))
        self.assertTrue(all(r["nearest_community_distance_km"] is None for r in enrich_fire_proximity(records, [])))

    def test_layer_subset(self):
        from unittest.mock import Mock
        with patch("app.community_service._get", side_effect=[METADATA,{"features":[feature()]}]) as get:
            result = fetch_communities(Mock(), layer_ids=(0,))
        self.assertEqual(len(result.communities), 1)
        self.assertEqual(get.call_count, 2)
        self.assertIn("/0/query", get.call_args.args[1])


class EnrichmentUITests(unittest.TestCase):
    run_app = ui_fixtures.UITests.run_app

    def test_refresh_recomputes_table_and_card(self):
        rows, _ = join_rankings([ui_fixtures.ranking()], [ui_fixtures.official()])
        app = self.run_app(rows)
        original = app.dataframe[0].value.iloc[0]["nearest_community_distance_km"]
        from app.community_service import CommunityFetch
        replacement = CommunityFetch(communities=[community("New point", Point(-111.98066,56.472313))])
        with patch("app.ranking_service.load_rankings", return_value=(rows,{"unmatched":0,"invalid_dates":0})), patch("app.community_service.fetch_communities", return_value=replacement) as fetch:
            app.button[0].click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertNotEqual(original, app.dataframe[0].value.iloc[0]["nearest_community_distance_km"])
        self.assertEqual(app.dataframe[0].value.iloc[0]["nearest_community_distance_km"], 0)
        fetch.assert_called_once_with(layer_ids=(0,))
        self.assertIn("New point", repr([frame.value.to_dict() for frame in app.dataframe]))

    def test_failed_source_keeps_records(self):
        rows, _ = join_rankings([ui_fixtures.ranking()], [ui_fixtures.official()])
        from app.community_service import CommunityFetch
        with patch("app.ranking_service.load_rankings", return_value=(rows,{"unmatched":0,"invalid_dates":0})), patch("app.community_service.fetch_communities", return_value=CommunityFetch(errors=["Unavailable"])):
            app = self.run_app(rows)
            app.button[0].click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.dataframe[0].value.iloc[0]["nearest_community_distance_km"], "N/A")
        self.assertTrue(any("source unavailable" in warning.value for warning in app.warning))


if __name__ == "__main__":
    unittest.main()
