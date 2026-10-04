"""Spherical distances; Shapely is used only for topology and marker placement."""
import math

from shapely.geometry import Point

EARTH_RADIUS_KM = 6371.0088


def validate_coordinates(latitude, longitude):
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise ValueError("Coordinates must be finite numbers.")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Latitude must be within ±90 and longitude within ±180.")


def haversine_distance(lat1, lon1, lat2, lon2):
    validate_coordinates(lat1, lon1)
    validate_coordinates(lat2, lon2)
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(max(0, min(1, h))))


def _vector(lon, lat):
    lon, lat = math.radians(lon), math.radians(lat)
    return (math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat))


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _angle(a, b):
    return math.atan2(math.sqrt(_dot(_cross(a, b), _cross(a, b))), _dot(a, b))


def _segment_nearest(latitude, longitude, start, end):
    """Nearest point on the minor great-circle arc, including its endpoints."""
    p, a, b = _vector(longitude, latitude), _vector(*start[:2]), _vector(*end[:2])
    candidates = [a, b]
    normal = _cross(a, b)
    norm2 = _dot(normal, normal)
    arc = _angle(a, b)
    if norm2 > 1e-24 and arc < math.pi - 1e-12:
        projection = tuple(p[i] - normal[i]*_dot(p, normal)/norm2 for i in range(3))
        length = math.sqrt(_dot(projection, projection))
        if length > 1e-12:
            q = tuple(v/length for v in projection)
            for candidate in (q, tuple(-v for v in q)):
                if abs(_angle(a, candidate) + _angle(candidate, b) - arc) < 1e-10:
                    candidates.append(candidate)
    nearest = min(candidates, key=lambda q: _angle(p, q))
    lon = math.degrees(math.atan2(nearest[1], nearest[0]))
    lat = math.degrees(math.atan2(nearest[2], math.hypot(nearest[0], nearest[1])))
    return haversine_distance(latitude, longitude, lat, lon), (lon, lat)


def distance_to_geometry(latitude, longitude, geometry):
    validate_coordinates(latitude, longitude)
    if geometry.geom_type == "Point":
        return haversine_distance(latitude, longitude, geometry.y, geometry.x), (geometry.x, geometry.y)
    if geometry.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError("Unsupported community geometry.")
    if geometry.covers(Point(longitude, latitude)):
        return 0.0, (longitude, latitude)
    polygons = [geometry] if geometry.geom_type == "Polygon" else geometry.geoms
    candidates = []
    for polygon in polygons:
        for ring in [polygon.exterior, *polygon.interiors]:
            coords = list(ring.coords)
            candidates.extend(_segment_nearest(latitude, longitude, a, b) for a, b in zip(coords, coords[1:]))
    return min(candidates, key=lambda item: item[0])


def find_nearest_communities(latitude, longitude, communities, limit=5):
    validate_coordinates(latitude, longitude)
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("Limit must be a positive integer.")
    ranked = []
    for community in communities:
        distance, endpoint = distance_to_geometry(latitude, longitude, community["geometry"])
        ranked.append({**community, "distance_km": distance, "nearest_point": endpoint})
    return sorted(ranked, key=lambda c: (c["distance_km"], c["type"], c["name"], c["source_id"]))[:limit]


def build_result(fire_id, latitude, longitude, hazard_score, nearby):
    validate_coordinates(latitude, longitude)
    if not fire_id.strip():
        raise ValueError("Fire ID is required.")
    if hazard_score is not None and not math.isfinite(hazard_score):
        raise ValueError("Hazard score must be finite.")
    fields = ("name", "type", "latitude", "longitude", "distance_km")
    return {"fire_id": fire_id.strip(), "latitude": latitude, "longitude": longitude,
            "hazard_score": hazard_score,
            "nearby_communities": [{key: c[key] for key in fields} for c in nearby]}
