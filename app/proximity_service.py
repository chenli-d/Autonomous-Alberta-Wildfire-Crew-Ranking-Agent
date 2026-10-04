"""Deterministic proximity to real populated-place points, independent of the UI."""
from app.geo import haversine_distance, validate_coordinates
from app.ranking_service import SAFE_FIELDS

PROXIMITY_FIELDS = ("nearest_community", "nearest_community_distance_km", "community_proximity_rank")


def valid_community_points(communities):
    points = []
    for community in communities:
        try:
            if community["geometry"].geom_type != "Point" or community["geometry"].is_empty or not community["name"].strip():
                continue
            # Use the source point geometry itself, never a polygon's marker/centroid.
            latitude, longitude = community["geometry"].y, community["geometry"].x
            validate_coordinates(latitude, longitude)
            points.append({**community, "latitude": latitude, "longitude": longitude})
        except (KeyError, AttributeError, TypeError, ValueError):
            continue
    return points


def find_nearest_community_points(lat, lon, communities, limit=5):
    try:
        validate_coordinates(lat, lon)
    except (TypeError, ValueError):
        return []
    candidates = [{**point, "distance_km": haversine_distance(lat, lon, point["latitude"], point["longitude"]),
                   "nearest_point": (point["longitude"], point["latitude"])}
                  for point in valid_community_points(communities)]
    return sorted(candidates, key=lambda p: (p["distance_km"], p["name"], str(p.get("source_id", ""))))[:limit]


def find_nearest_community(lat, lon, communities):
    candidates = find_nearest_community_points(lat, lon, communities, limit=1)
    if not candidates:
        return None
    return {"nearest_community": candidates[0]["name"], "nearest_community_distance_km": candidates[0]["distance_km"]}


def enrich_fire_proximity(records, communities):
    """Preserve RF order/values and calculate a separate sequential proximity rank."""
    points = valid_community_points(communities)
    enriched = []
    for source in records:
        record = {key: source[key] for key in SAFE_FIELDS if key in source}
        record.update(dict.fromkeys(PROXIMITY_FIELDS))
        nearest = find_nearest_community(record.get("LATITUDE"), record.get("LONGITUDE"), points)
        if nearest is not None:
            record.update(nearest)
        enriched.append(record)
    ranked = sorted((r for r in enriched if r["nearest_community_distance_km"] is not None),
                    key=lambda r: (r["nearest_community_distance_km"], r["fire_id"]))
    for rank, record in enumerate(ranked, 1):
        record["community_proximity_rank"] = rank
    return enriched
