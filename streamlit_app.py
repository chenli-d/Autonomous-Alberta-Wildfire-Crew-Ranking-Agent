"""Run with: streamlit run streamlit_app.py."""
import csv
import json
import time
from pathlib import Path

import streamlit as st
from streamlit_folium import st_folium

from app.community_service import fetch_communities
from app.geo import build_result
from app.map_view import create_map, create_overview_map
from app.ranking_service import AVAILABLE_DATES, load_rankings, map_record
from app.proximity_service import enrich_fire_proximity, valid_community_points, find_nearest_community_points
from app.review_service import load_allocation_context, attach_allocation_context, select_review_candidates
from app.agent_view import show_agent_review
from app.config import load_local_environment


@st.cache_data(ttl=3600, show_spinner="Loading Alberta communities…")
def load_communities():
    result = fetch_communities(layer_ids=(0,))
    # Do not cache failed or partial fetches as a successful snapshot.
    if result.errors:
        raise LookupError(result)
    return result


@st.cache_data(show_spinner=False)
def load_fires(ranking_path, ranking_modified_ns, official_path, official_modified_ns, selected_day):
    # Both modification times invalidate the cache; only allowlisted records are cached.
    return load_rankings(ranking_path, official_path, selected_day)


@st.cache_data(show_spinner=False)
def load_review_context(allocation_path, allocation_modified_ns, metadata_path, metadata_modified_ns, selected_day):
    return load_allocation_context(allocation_path, metadata_path, selected_day)


def show_review_candidates(records, root, selected_day):
    st.subheader("Crew-cut review candidates")
    st.caption("Review shortlist only: RF ranking and crew allocation are unchanged. Cutoff rules use saved daily allocation RF rank; annual RF rank is retained separately.")
    allocation_path = root / "outputs/dev_recent/allocation_2024-07-16.csv"
    metadata_path = root / "outputs/dev_recent/metrics.json"
    try:
        context = load_review_context(str(allocation_path), allocation_path.stat().st_mtime_ns,
                                      str(metadata_path), metadata_path.stat().st_mtime_ns, selected_day)
        context = {**context, "source_versions": [
            path.stat().st_mtime_ns for path in (allocation_path, metadata_path,
                root / "outputs/dev_recent/ranking_2024.csv",
                root / "data/raw/fp-historical-wildfire-data-2006-2025.csv")]}
        allocated_records = attach_allocation_context(records, context)
        candidates = select_review_candidates(allocated_records, context["H"], context["H_cut"])
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as error:
        for key in ("agent_snapshot", "agent_trace", "final_crew_assignments"):
            st.session_state.pop(key, None)
        st.warning(f"Review shortlist unavailable: {error}")
        return
    st.caption(f"H = {context['H']}; H_cut = {context['H_cut']}; {len(candidates)} review candidates.")
    if not candidates:
        for key in ("agent_snapshot", "agent_trace", "final_crew_assignments"):
            st.session_state.pop(key, None)
        st.info("No review candidates available.")
        return
    st.dataframe([{"fire_id": record["fire_id"], "Daily allocation RF rank": record["allocation_rank"],
                   "Annual RF rank": record.get("rank"), "rf_probability": record.get("rf_probability"),
                   "Current allocation status": record["status"], "Nearest community": record.get("nearest_community") or "N/A",
                   "Distance (km)": record.get("nearest_community_distance_km") if record.get("nearest_community_distance_km") is not None else "N/A",
                   "Review reasons": ", ".join(record["review_reason"])} for record in candidates], hide_index=True,
                 column_config={"Distance (km)": st.column_config.NumberColumn(format="%.2f")})
    show_agent_review(allocated_records, candidates, context)


def show_fire_details(record):
    groups = {
        "Ranking": ("fire_id", "rank", "rf_probability", "baseline_rank", "status"),
        "Initial assessment": ("assessment_date", "ASSESSMENT_HECTARES"),
        "Weather / fire behaviour": ("FIRE_SPREAD_RATE", "TEMPERATURE", "RELATIVE_HUMIDITY", "WIND_SPEED"),
        "Fire characteristics": ("FIRE_TYPE", "FUEL_TYPE", "FIRE_POSITION_ON_SLOPE", "WEATHER_CONDITIONS_OVER_FIRE", "FOREST_AREA"),
        "Location": ("LATITUDE", "LONGITUDE"),
        "Community proximity": ("nearest_community", "nearest_community_distance_km", "community_proximity_rank"),
    }
    with st.container(border=True):
        st.subheader(f"Fire details: {record['fire_id']}")
        for heading, fields in groups.items():
            st.markdown(f"**{heading}**")
            st.dataframe([{"Field": field, "Value": (f"{record[field]:.2f}" if field == "nearest_community_distance_km" else str(record[field])) if record.get(field) is not None else "N/A"}
                          for field in fields if field != "status" or field in record], hide_index=True)


def main():
    load_local_environment()
    st.set_page_config(page_title="Alberta wildfire community proximity", layout="wide")
    st.title("Alberta wildfire community proximity")
    st.caption("Deterministic point-to-point distances to Alberta Hamlet/Locality/Townsite points (layer 0). Cities and towns supplied as municipal polygons are not included. Proximity rank does not change RF ranking.")
    selected_day = st.selectbox("Assessment day", AVAILABLE_DATES,
                                format_func=lambda day: day.isoformat(), key="supported_assessment_day")
    st.subheader(f"Fires assessed on {selected_day.isoformat()}")
    root = Path(__file__).parent
    ranking_path = root / "outputs/dev_recent/ranking_2024.csv"
    official_path = root / "data/raw/fp-historical-wildfire-data-2006-2025.csv"
    try:
        records, diagnostics = load_fires(str(ranking_path), ranking_path.stat().st_mtime_ns,
                                           str(official_path), official_path.stat().st_mtime_ns, selected_day)
    except (OSError, csv.Error, ValueError) as error:
        for key in ("agent_snapshot", "agent_trace", "final_crew_assignments"):
            st.session_state.pop(key, None)
        st.error(f"Unable to load ranked fires: {error}")
        return
    if diagnostics["unmatched"]:
        st.warning(f"{diagnostics['unmatched']} ranking fire IDs have no official source match.")
    if diagnostics["invalid_dates"]:
        st.warning(f"Skipped {diagnostics['invalid_dates']} records with missing or invalid assessment dates.")
    if not records:
        for key in ("agent_snapshot", "agent_trace", "final_crew_assignments"):
            st.session_state.pop(key, None)
        st.info("No ranked fires available for this assessment day.")
        return
    if st.button("Refresh community data"):
        load_communities.clear()
        st.session_state.pop("community_point_fetch", None)
        for key in ("agent_snapshot", "agent_trace", "final_crew_assignments"):
            st.session_state.pop(key, None)
    if "community_point_fetch" not in st.session_state or time.time() - st.session_state.get("community_point_fetch_time", 0) >= 3600:
        try:
            st.session_state.community_point_fetch = load_communities()
        except LookupError as error:
            st.session_state.community_point_fetch = error.args[0]
        st.session_state.community_point_fetch_time = time.time()
    fetched = st.session_state.community_point_fetch
    if fetched.errors:
        st.warning("Community point source unavailable. Proximity values are N/A; use Refresh to retry.")
        for error in fetched.errors:
            st.caption(error)
    if fetched.skipped:
        st.warning(f"Skipped {fetched.skipped} malformed or invalid community records.")
    points = valid_community_points(fetched.communities) if not fetched.errors else []
    if not points and not fetched.errors:
        st.warning("Community point source has no usable records. Proximity values are N/A.")
    records = enrich_fire_proximity(records, points)
    table_fields = ("fire_id", "rank", "rf_probability", "baseline_rank", "nearest_community_distance_km", "community_proximity_rank")
    st.dataframe([{key: r[key] if r[key] is not None else "N/A" for key in table_fields} for r in records], hide_index=True,
                 column_config={"nearest_community_distance_km": st.column_config.NumberColumn(format="%.2f")})
    show_review_candidates(records, root, selected_day)
    locations = [mapped for r in records if (mapped := map_record(r)) is not None]
    st.caption(f"{len(records)} ranked fires; {len(locations)} valid locations; {len(records)-len(locations)} missing or invalid locations.")
    if locations:
        st.subheader("Daily wildfire overview")
        st_folium(create_overview_map(locations), height=450, use_container_width=True,
                  returned_objects=[], key="daily_overview")
    else:
        st.info("No valid coordinates for the overview map.")
    fire_ids = [record["fire_id"] for record in records]
    if st.session_state.get("selected_fire") not in fire_ids:
        st.session_state.pop("selected_fire", None)
    selected_id = st.selectbox("Wildfire", fire_ids, key="selected_fire")
    record = records[fire_ids.index(selected_id)]
    show_fire_details(record)
    fire = map_record(record)
    if fire is None:
        st.info("This fire has missing or invalid official coordinates. Community proximity is unavailable.")
        return
    st.subheader(f"Community proximity: {fire['fire_id']}")
    nearby = find_nearest_community_points(fire["latitude"], fire["longitude"], points)
    result = build_result(fire["fire_id"], fire["latitude"], fire["longitude"], fire["hazard_score"], nearby)
    st_folium(create_map(fire["fire_id"], fire["latitude"], fire["longitude"], nearby, fire["hazard_score"]),
              height=580, use_container_width=True, returned_objects=[], key="selected_proximity")
    if nearby:
        st.dataframe([{"Community": c["name"], "Type": c["type"], "Distance (km)": round(c["distance_km"], 2)} for c in nearby],
                     column_config={"Distance (km)": st.column_config.NumberColumn(format="%.2f")}, hide_index=True)
    else:
        st.info("No community records available. The map shows the wildfire location.")
    st.download_button("Download proximity JSON", json.dumps(result, indent=2, allow_nan=False), "community_proximity.json", "application/json")


if __name__ == "__main__":
    main()
