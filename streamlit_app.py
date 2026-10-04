"""Run with: streamlit run streamlit_app.py."""
import csv
import json
import time
from pathlib import Path

import streamlit as st
from streamlit_folium import st_folium

from app.community_service import fetch_communities
from app.geo import build_result, find_nearest_communities, validate_coordinates
from app.map_view import create_map


@st.cache_data(ttl=3600, show_spinner="Loading Alberta communities…")
def load_communities():
    result = fetch_communities()
    # Do not cache failed or partial fetches as a successful snapshot.
    if result.errors:
        raise LookupError(result)
    return result


def sample_fire():
    with (Path(__file__).parent / "data/alberta_wildfires_2023_2025.csv").open(newline="", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            if row["YEAR"] == "2024" and row["FIRE_NUMBER"] == "PWF076" and row["FIRE_START_DATE"].startswith("2024-07-16"):
                return {"fire_id": "2024:PWF076", "latitude": float(row["LATITUDE"]),
                        "longitude": float(row["LONGITUDE"]), "hazard_score": None}
    raise ValueError("July 16, 2024 sample fire is missing from the CSV.")


def main():
    st.set_page_config(page_title="Alberta wildfire community proximity", layout="wide")
    st.title("Alberta wildfire community proximity")
    st.caption("Deterministic straight-line distances. Point communities use point-to-point distance; municipal polygons use distance to the community area (zero inside). Marker positions are representative locations.")
    if "fire" not in st.session_state:
        st.session_state.fire = sample_fire()
    fire = st.session_state.fire
    with st.form("fire_input"):
        fire_id = st.text_input("Fire ID", fire["fire_id"])
        latitude = st.number_input("Latitude", value=fire["latitude"], format="%.6f")
        longitude = st.number_input("Longitude", value=fire["longitude"], format="%.6f")
        hazard = st.text_input("Hazard score (optional, passed through unchanged)", "" if fire["hazard_score"] is None else str(fire["hazard_score"]))
        submitted = st.form_submit_button("Show nearby communities")
    if submitted:
        try:
            score = float(hazard) if hazard.strip() else None
            validate_coordinates(latitude, longitude)
            st.session_state.fire = build_result(fire_id, latitude, longitude, score, [])
            fire = st.session_state.fire
            st.session_state.pop("community_fetch", None)
        except ValueError as error:
            st.error(str(error))
            return
    if st.button("Refresh community data"):
        load_communities.clear()
        st.session_state.pop("community_fetch", None)
    if "community_fetch" not in st.session_state or time.time() - st.session_state.get("community_fetch_time", 0) >= 3600:
        try:
            st.session_state.community_fetch = load_communities()
        except LookupError as error:
            st.session_state.community_fetch = error.args[0]
        st.session_state.community_fetch_time = time.time()
    fetched = st.session_state.community_fetch
    if fetched.errors:
        st.warning("Incomplete community lookup: nearest results only cover successfully loaded layers. Use Refresh to retry.")
        for error in fetched.errors:
            st.caption(error)
    if fetched.skipped:
        st.warning(f"Skipped {fetched.skipped} malformed or invalid community records.")
    nearby = find_nearest_communities(fire["latitude"], fire["longitude"], fetched.communities)
    result = build_result(fire["fire_id"], fire["latitude"], fire["longitude"], fire["hazard_score"], nearby)
    st_folium(create_map(fire["fire_id"], fire["latitude"], fire["longitude"], nearby), height=580, use_container_width=True, returned_objects=[])
    if nearby:
        st.dataframe([{"Community": c["name"], "Type": c["type"], "Distance (km)": round(c["distance_km"], 2)} for c in nearby],
                     column_config={"Distance (km)": st.column_config.NumberColumn(format="%.2f")}, hide_index=True)
    else:
        st.info("No community records available. The map shows the wildfire location.")
    st.download_button("Download proximity JSON", json.dumps(result, indent=2, allow_nan=False), "community_proximity.json", "application/json")


if __name__ == "__main__":
    main()
