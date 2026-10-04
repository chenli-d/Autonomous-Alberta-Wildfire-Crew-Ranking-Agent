"""Run with: streamlit run streamlit_app.py."""
import csv
import json
import math
import time
from datetime import date, datetime
from pathlib import Path

import streamlit as st
from streamlit_folium import st_folium

from app.community_service import fetch_communities
from app.geo import build_result, find_nearest_communities, validate_coordinates
from app.map_view import create_map, create_overview_map


@st.cache_data(ttl=3600, show_spinner="Loading Alberta communities…")
def load_communities():
    result = fetch_communities()
    # Do not cache failed or partial fetches as a successful snapshot.
    if result.errors:
        raise LookupError(result)
    return result


def parse_wildfires(rows):
    """Group by assessment day, retaining dates even when coordinates are invalid."""
    days, invalid_dates = {}, 0
    for row in rows:
        try:
            timestamp = row["ASSESSMENT_DATETIME"].strip()
            try:
                day = datetime.fromisoformat(timestamp).date()
            except ValueError:
                # The source CSV also uses single-digit hours, e.g. "2024-07-16 6:00".
                day = datetime.strptime(timestamp, "%Y-%m-%d %H:%M").date()
        except (ValueError, KeyError, AttributeError):
            invalid_dates += 1
            continue
        daily = days.setdefault(day, {"fires": [], "skipped": 0})
        try:
            latitude, longitude = float(row["LATITUDE"]), float(row["LONGITUDE"])
            validate_coordinates(latitude, longitude)
        except (ValueError, KeyError, TypeError):
            daily["skipped"] += 1
            continue
        score = None
        for column in ("hazard_score", "rf_probability"):
            try:
                candidate = float(row.get(column))
                if math.isfinite(candidate):
                    score = candidate
                    break
            except (ValueError, TypeError):
                pass
        daily["fires"].append({"fire_id": f"{row['YEAR']}:{row['FIRE_NUMBER']}",
                               "latitude": latitude, "longitude": longitude, "hazard_score": score})
    for daily in days.values():
        daily["fires"].sort(key=lambda fire: fire["fire_id"])
    return dict(sorted(days.items())), invalid_dates


@st.cache_data(show_spinner=False)
def load_wildfires(path, modified_ns, assessment_path, assessment_modified_ns):
    # File modification time is part of the cache key so replacing the CSV reloads it.
    with Path(path).open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    if rows and "ASSESSMENT_DATETIME" not in rows[0]:
        # The bundled subset omits assessment time. Join the existing local source,
        # retaining the subset's coordinates/scores and its original fire cohort.
        wanted = {(r["YEAR"].strip(), r["FIRE_NUMBER"].strip()) for r in rows}
        assessments = {}
        with Path(assessment_path).open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            if "ASSESSMENT_DATETIME" not in (reader.fieldnames or []):
                raise ValueError("Assessment source is missing ASSESSMENT_DATETIME.")
            for source in reader:
                key = (source["YEAR"].strip(), source["FIRE_NUMBER"].strip())
                if key in wanted:
                    if key in assessments:
                        raise ValueError(f"Duplicate assessment source fire: {key}")
                    assessments[key] = source["ASSESSMENT_DATETIME"]
        rows = [{**r, "ASSESSMENT_DATETIME": assessments.get((r["YEAR"].strip(), r["FIRE_NUMBER"].strip()), "")} for r in rows]
    return parse_wildfires(rows)


def main():
    st.set_page_config(page_title="Alberta wildfire community proximity", layout="wide")
    st.title("Alberta wildfire community proximity")
    st.caption("Deterministic straight-line distances. Point communities use point-to-point distance; municipal polygons use distance to the community area (zero inside). Marker positions are representative locations.")
    path = Path(__file__).parent / "data/alberta_wildfires_2023_2025.csv"
    assessment_path = path.parent / "raw/fp-historical-wildfire-data-2006-2025.csv"
    try:
        days, invalid_dates = load_wildfires(str(path), path.stat().st_mtime_ns,
                                             str(assessment_path), assessment_path.stat().st_mtime_ns)
    except (OSError, csv.Error, ValueError) as error:
        st.error(f"Unable to load wildfire data: {error}")
        return
    if invalid_dates:
        st.warning(f"Skipped {invalid_dates} records with missing or unparseable ASSESSMENT_DATETIME values.")
    if not days:
        st.info("No valid assessment dates available in the dataset.")
        return
    dates = list(days)
    default_day = date(2024, 7, 16) if date(2024, 7, 16) in days else dates[-1]
    selected_day = st.selectbox("Assessment day", dates, index=dates.index(default_day),
                                format_func=lambda day: day.isoformat(), key="selected_day")
    fires = days[selected_day]["fires"]
    st.caption(f"{len(fires)} valid wildfire locations; {days[selected_day]['skipped']} records skipped for missing or invalid coordinates. Day means ASSESSMENT_DATETIME, not fire start date or an active-fire snapshot.")
    if st.session_state.get("previous_day") != selected_day:
        st.session_state.pop("selected_fire", None)
        st.session_state.previous_day = selected_day
    if not fires:
        st.info("No valid wildfire locations for this day.")
        return
    st.subheader("Daily wildfire overview")
    st_folium(create_overview_map(fires), height=450, use_container_width=True,
              returned_objects=[], key="daily_overview")
    fire_ids = [fire["fire_id"] for fire in fires]
    default_id = fire_ids[0]
    selected_id = st.selectbox("Wildfire", fire_ids, index=fire_ids.index(default_id), key="selected_fire")
    fire = fires[fire_ids.index(selected_id)]
    st.subheader(f"Community proximity: {fire['fire_id']}")
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
