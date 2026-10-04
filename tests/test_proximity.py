import math
import unittest
from unittest.mock import Mock, patch

import requests
from shapely.geometry import Point, Polygon, MultiPolygon

from app.community_service import fetch_communities, _normalize
from app.geo import (haversine_distance, distance_to_geometry, _segment_nearest,
                     find_nearest_communities, build_result)
from app.map_view import create_map


def community(name="Example", geometry=None, identifier="0:1"):
    geometry = geometry if geometry is not None else Point(0, 0)
    marker = geometry.representative_point()
    return {"name": name, "type": "Town", "source_id": identifier,
            "geometry": geometry, "latitude": marker.y, "longitude": marker.x}


class GeoTests(unittest.TestCase):
    def test_haversine(self):
        self.assertEqual(haversine_distance(10, 20, 10, 20), 0)
        self.assertAlmostEqual(haversine_distance(0, 0, 0, 1), 111.195080, places=5)
        self.assertAlmostEqual(haversine_distance(0, 0, 0, 180), math.pi*6371.0088)
        for lat, lon in [(91, 0), (0, 181), (float("nan"), 0), (0, float("inf"))]:
            with self.assertRaises(ValueError):
                haversine_distance(lat, lon, 0, 0)

    def test_polygon_inside_edge_and_hole(self):
        polygon = Polygon([(-2,-2),(2,-2),(2,2),(-2,2)],
                          holes=[[(-1,-1),(1,-1),(1,1),(-1,1)]])
        self.assertEqual(distance_to_geometry(1.5, 0, polygon)[0], 0)
        self.assertEqual(distance_to_geometry(0, 2, polygon)[0], 0)
        self.assertAlmostEqual(distance_to_geometry(0, 0, polygon)[0], 111.195080, places=5)

    def test_segment_interior_endpoint_and_degenerate(self):
        distance, endpoint = _segment_nearest(1, 0, (-1, 0), (1, 0))
        self.assertAlmostEqual(distance, 111.195080, places=5)
        self.assertAlmostEqual(endpoint[0], 0)
        distance, endpoint = _segment_nearest(0, 3, (-1, 0), (1, 0))
        self.assertAlmostEqual(endpoint[0], 1)
        self.assertAlmostEqual(distance, haversine_distance(0, 3, 0, 1))
        self.assertAlmostEqual(_segment_nearest(0, 1, (0, 0), (0, 0))[0], 111.195080, places=5)
        self.assertTrue(math.isfinite(_segment_nearest(10, 20, (0,0), (180,0))[0]))

    def test_multipolygon(self):
        first = Polygon([(5,5),(6,5),(6,6),(5,6)])
        second = Polygon([(-1,-1),(1,-1),(1,1),(-1,1)])
        multi = MultiPolygon([first, second])
        self.assertEqual(distance_to_geometry(0, 0, multi)[0], 0)
        self.assertEqual(distance_to_geometry(0, 2, multi), distance_to_geometry(0, 2, second))

    def test_ranking_and_result(self):
        records = [community("B", identifier="0:2"), community("A", identifier="0:3"), community("A", identifier="0:1")]
        nearest = find_nearest_communities(0, 0, records)
        self.assertEqual([c["source_id"] for c in nearest], ["0:1", "0:3", "0:2"])
        self.assertEqual(find_nearest_communities(0, 0, []), [])
        result = build_result(" sample ", 0, 0, 0.158, nearest)
        self.assertEqual(result["hazard_score"], 0.158)
        self.assertEqual(set(result["nearby_communities"][0]), {"name","type","latitude","longitude","distance_km"})
        for name, score in [(" ", None), ("ok", float("inf"))]:
            with self.assertRaises(ValueError):
                build_result(name, 0, 0, score, [])

    def test_map_render(self):
        polygon = Polygon([(-1,-1),(1,-1),(1,1),(-1,1)])
        nearby = find_nearest_communities(0, 2, [community("<Town>", polygon)])
        html = create_map("fire", 0, 2, nearby).get_root().render()
        for content in ("poly_line", "geo_json", "Straight-line distance", "Alberta Government", "&lt;Town&gt;", "OpenStreetMap"):
            self.assertIn(content, html)


METADATA = {"fields": [{"name":"CULPT_NAME", "type":"esriFieldTypeString"},
                       {"name":"OBJECTID", "type":"esriFieldTypeOID"}], "maxRecordCount": 2}


def feature(identifier=1):
    return {"properties": {"CULPT_NAME":"Example", "TYPE":"Hamlet", "OBJECTID":identifier},
            "geometry": {"type":"Point", "coordinates":[-114, 54]}}


class ServiceTests(unittest.TestCase):
    def run_fetch(self, payloads):
        session = Mock()
        def response(*args, **kwargs):
            payload = next(payloads)
            if isinstance(payload, Exception):
                raise payload
            result = Mock()
            result.json.return_value = payload
            return result
        session.get.side_effect = response
        with patch("app.community_service.LAYERS", {0:"Hamlet, Locality, Townsite"}):
            fetched = fetch_communities(session)
        return fetched, session

    def test_pagination_and_normalization(self):
        fetched, session = self.run_fetch(iter([METADATA, {"features":[feature(1),feature(2)]}, {"features":[feature(3)]}]))
        self.assertEqual(len(fetched.communities), 3)
        self.assertEqual(fetched.communities[0]["type"], "Hamlet")
        params = session.get.call_args.kwargs["params"]
        self.assertEqual(params["resultOffset"], 2)
        self.assertEqual(params["outSR"], 4326)
        self.assertEqual(params["f"], "geojson")
        self.assertEqual(fetched.errors, [])

    def test_empty_malformed_duplicates(self):
        fetched, _ = self.run_fetch(iter([METADATA, {"features":[]}]))
        self.assertEqual(fetched.communities, [])
        self.assertEqual(fetched.errors, [])
        fetched, _ = self.run_fetch(iter([METADATA, {"features":[feature(1), {}]}, {"features":[feature(1)]}]))
        self.assertEqual(len(fetched.communities), 1)
        self.assertEqual(fetched.skipped, 1)

    def test_invalid_geometry(self):
        invalid = feature()
        invalid["geometry"] = {"type":"Polygon", "coordinates":[[[0,0],[1,1],[1,0],[0,1],[0,0]]]}
        with self.assertRaises(ValueError):
            _normalize(invalid, 0, "CULPT_NAME", "OBJECTID")

    def test_polygon_name_and_type(self):
        polygon = {"properties":{"VILL_NAME":"Acme", "OBJECTID":1},
                   "geometry":{"type":"Polygon", "coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}}
        record = _normalize(polygon, 1, "VILL_NAME", "OBJECTID")
        self.assertEqual(record["name"], "Acme")
        self.assertEqual(record["type"], "Village")
        self.assertTrue(record["geometry"].contains(Point(record["longitude"], record["latitude"])))

    def test_timeout_and_arcgis_error(self):
        for failure in [requests.Timeout("timeout"), {"error":{"message":"unavailable"}}]:
            fetched, _ = self.run_fetch(iter([failure]))
            self.assertEqual(len(fetched.errors), 1)
            self.assertEqual(fetched.communities, [])

    def test_partial_failure(self):
        with patch("app.community_service.LAYERS", {0:"Hamlet",1:"Village"}), patch("app.community_service._get") as get:
            get.side_effect = [METADATA, {"features":[feature()]}, requests.Timeout("timeout")]
            fetched = fetch_communities(Mock())
        self.assertEqual(len(fetched.communities), 1)
        self.assertEqual(len(fetched.errors), 1)


if __name__ == "__main__":
    unittest.main()
