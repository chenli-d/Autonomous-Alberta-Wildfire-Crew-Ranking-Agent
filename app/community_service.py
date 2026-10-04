"""Community geometries from Alberta Government's public municipal MapServer."""
from dataclasses import dataclass, field
import math

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from shapely.geometry import shape
from shapely.errors import GEOSException

SERVICE_URL = "https://geospatial.alberta.ca/titan/rest/services/boundaries/municipal_communities_public/MapServer"
LAYERS = {0: "Hamlet, Locality, Townsite", 1: "Village", 2: "Summer Village",
          3: "Town", 4: "Urban Service Area", 5: "City", 6: "Settlement"}


@dataclass
class CommunityFetch:
    communities: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    skipped: int = 0


def create_session():
    session = requests.Session()
    retry = Retry(total=2, backoff_factor=0.5, respect_retry_after_header=False,
                  status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _get(session, url, params):
    response = session.get(url, params=params, timeout=(5, 30))
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("ArcGIS returned an invalid response")
    if "error" in payload:
        raise ValueError(payload["error"].get("message", "ArcGIS query failed"))
    return payload


def _normalize(feature, layer_id, name_field, id_field):
    properties = feature["properties"]
    name = properties.get(name_field)
    identifier = properties.get(id_field)
    geometry = shape(feature["geometry"])
    if not name or identifier is None or geometry.is_empty or not geometry.is_valid:
        raise ValueError("Missing name, identifier, or valid geometry")
    if geometry.geom_type not in ("Point", "Polygon", "MultiPolygon"):
        raise ValueError("Unsupported geometry")
    # Validate all source vertices, not just the representative marker.
    def check_coordinates(node):
        if isinstance(node[0], (int, float)):
            lon, lat = node[:2]
            if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError("Invalid coordinates")
        else:
            for child in node:
                check_coordinates(child)
    check_coordinates(feature["geometry"]["coordinates"])
    marker = geometry if geometry.geom_type == "Point" else geometry.representative_point()
    return {"name": str(name), "type": str(properties.get("TYPE") or LAYERS[layer_id]),
            "latitude": marker.y, "longitude": marker.x, "geometry": geometry,
            "source_id": f"{layer_id}:{identifier}"}


def fetch_communities(session=None, layer_ids=None):
    selected_layers = LAYERS if layer_ids is None else {layer: LAYERS[layer] for layer in layer_ids}
    owned = session is None
    session = session or create_session()
    result = CommunityFetch()
    try:
        for layer_id, layer_name in selected_layers.items():
            try:
                url = f"{SERVICE_URL}/{layer_id}"
                metadata = _get(session, url, {"f": "json"})
                fields = metadata["fields"]
                name_field = next(f["name"] for f in fields if f["name"].endswith("_NAME"))
                id_field = next(f["name"] for f in fields if f["type"] == "esriFieldTypeOID")
                page_size = min(1000, metadata.get("maxRecordCount", 1000))
                offset, seen, records = 0, set(), []
                previous_page_ids = None
                while True:
                    page = _get(session, url + "/query", {
                        "where": "1=1", "outFields": f"{name_field},{id_field}" + (",TYPE" if layer_id == 0 else ""),
                        "outSR": 4326, "returnGeometry": "true", "f": "geojson",
                        "orderByFields": f"{id_field} ASC", "resultOffset": offset,
                        "resultRecordCount": page_size})
                    features = page["features"]
                    if not isinstance(features, list):
                        raise ValueError("ArcGIS returned an invalid feature list")
                    page_ids = tuple(str(f.get("properties", {}).get(id_field)) if isinstance(f, dict) and isinstance(f.get("properties"), dict) else "invalid" for f in features)
                    if features and page_ids == previous_page_ids:
                        raise ValueError("Pagination made no progress")
                    previous_page_ids = page_ids
                    for feature in features:
                        try:
                            record = _normalize(feature, layer_id, name_field, id_field)
                            if record["source_id"] not in seen:
                                records.append(record)
                                seen.add(record["source_id"])
                        except (ValueError, KeyError, TypeError, IndexError, AttributeError, GEOSException):
                            result.skipped += 1
                    exceeded = page.get("exceededTransferLimit", page.get("properties", {}).get("exceededTransferLimit", False))
                    if not features or (len(features) < page_size and not exceeded):
                        break
                    offset += len(features)
                result.communities.extend(records)
            except (requests.RequestException, ValueError, KeyError, TypeError, StopIteration) as error:
                result.errors.append(f"{layer_name}: {error}")
    finally:
        if owned:
            session.close()
    return result
