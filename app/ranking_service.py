"""Join existing model outputs to official geography, exposing allowlisted fields only."""
import csv
import math
from datetime import date, datetime
from pathlib import Path

from app.geo import validate_coordinates

AVAILABLE_DATES = (date(2024, 7, 16),)
SAFE_FIELDS = (
    "fire_id", "rank", "rf_probability", "baseline_rank", "ASSESSMENT_HECTARES",
    "FIRE_SPREAD_RATE", "TEMPERATURE", "RELATIVE_HUMIDITY", "WIND_SPEED",
    "FIRE_TYPE", "FUEL_TYPE", "FIRE_POSITION_ON_SLOPE", "WEATHER_CONDITIONS_OVER_FIRE",
    "FOREST_AREA", "LATITUDE", "LONGITUDE", "assessment_date", "status",
)
NUMERIC_FIELDS = {"rank", "rf_probability", "baseline_rank", "ASSESSMENT_HECTARES",
                  "FIRE_SPREAD_RATE", "TEMPERATURE", "RELATIVE_HUMIDITY", "WIND_SPEED",
                  "LATITUDE", "LONGITUDE"}


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _day(value):
    value = (value or "").strip()
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M").date()
        except ValueError:
            return None


def join_rankings(ranking_rows, official_rows, selected_day=AVAILABLE_DATES[0]):
    # Drop unknown/outcome columns immediately; never return/cache raw CSV dictionaries.
    rankings = [{key: row.get(key) for key in SAFE_FIELDS if key in row} for row in ranking_rows]
    wanted, seen = set(), set()
    for row in rankings:
        identifier = (row.get("fire_id") or "").strip()
        row["fire_id"] = identifier
        if identifier in seen:
            raise ValueError(f"Duplicate ranking fire ID: {identifier}")
        wanted.add(identifier)
        seen.add(identifier)
    source = {}
    for row in official_rows:
        identifier = f"{str(row['YEAR']).strip()}:{row['FIRE_NUMBER'].strip()}"
        if identifier not in wanted:
            continue
        if identifier in source:
            raise ValueError(f"Duplicate official fire ID: {identifier}")
        source[identifier] = {"LATITUDE": row.get("LATITUDE"), "LONGITUDE": row.get("LONGITUDE"),
                              "assessment_date": row.get("ASSESSMENT_DATETIME")}
    records, unmatched, invalid_dates = [], 0, 0
    for row in rankings:
        official = source.get(row["fire_id"])
        if official is None:
            unmatched += 1
        # A present ranking date is authoritative; malformed dates never fall back.
        day = _day(row["assessment_date"] if "assessment_date" in row else (official or {}).get("assessment_date"))
        if day is None:
            invalid_dates += 1
            continue
        if day != selected_day:
            continue
        record = {key: row.get(key) for key in SAFE_FIELDS if key != "status" or "status" in row}
        record.update({"LATITUDE": (official or {}).get("LATITUDE"),
                       "LONGITUDE": (official or {}).get("LONGITUDE"), "assessment_date": day.isoformat()})
        for key, value in record.items():
            if key in NUMERIC_FIELDS:
                record[key] = _number(value)
                if key in ("rank", "baseline_rank") and record[key] is not None and record[key].is_integer():
                    record[key] = int(record[key])
            elif isinstance(value, str):
                record[key] = value.strip() or None
        records.append(record)
    records.sort(key=lambda row: (row["rank"] if row["rank"] is not None else math.inf, row["fire_id"]))
    return records, {"unmatched": unmatched, "invalid_dates": invalid_dates}


def load_rankings(ranking_path, official_path, selected_day=AVAILABLE_DATES[0]):
    with Path(ranking_path).open(newline="", encoding="utf-8-sig") as rankings, Path(official_path).open(newline="", encoding="utf-8-sig") as official:
        ranking_reader, official_reader = csv.DictReader(rankings), csv.DictReader(official)
        if "fire_id" not in (ranking_reader.fieldnames or []):
            raise ValueError("Ranking CSV must contain fire_id.")
        if not {"YEAR", "FIRE_NUMBER"}.issubset(official_reader.fieldnames or []):
            raise ValueError("Official CSV must contain YEAR and FIRE_NUMBER.")
        return join_rankings(ranking_reader, official_reader, selected_day)


def map_record(record):
    """Return just the existing map interface fields, or None for invalid coordinates."""
    try:
        validate_coordinates(record["LATITUDE"], record["LONGITUDE"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"fire_id": record["fire_id"], "latitude": record["LATITUDE"],
            "longitude": record["LONGITUDE"], "hazard_score": record.get("rf_probability")}
