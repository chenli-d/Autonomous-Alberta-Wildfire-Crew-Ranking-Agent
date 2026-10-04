"""Read saved crew-cut context and select review candidates without allocation changes."""
import csv
import json
import math
from pathlib import Path

from app.ranking_service import SAFE_FIELDS, AVAILABLE_DATES
from app.proximity_service import PROXIMITY_FIELDS

CANDIDATE_FIELDS = (*SAFE_FIELDS, *PROXIMITY_FIELDS, "allocation_rank")
STATUSES = {"kept", "displaced", "no_crew"}


def _validate_counts(H, H_cut):
    if any(type(value) is not int or value < 0 for value in (H, H_cut)) or H_cut > H:
        raise ValueError("Crew counts must be nonnegative integers with H_cut <= H.")


def load_allocation_context(allocation_path, metadata_path, selected_day=AVAILABLE_DATES[0]):
    with Path(metadata_path).open(encoding="utf-8-sig") as file:
        metadata = json.load(file)
    context = {key: metadata[key] for key in ("allocation_date", "H", "H_cut")}
    _validate_counts(context["H"], context["H_cut"])
    if selected_day not in AVAILABLE_DATES or context["allocation_date"] != selected_day.isoformat():
        raise ValueError("Allocation date does not match the supported assessment day.")
    allocations, ranks = {}, set()
    with Path(allocation_path).open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not {"fire_id", "rank", "status"}.issubset(reader.fieldnames or []):
            raise ValueError("Allocation CSV requires fire_id, rank, and status.")
        for row in reader:
            identifier = row["fire_id"].strip()
            rank = int(row["rank"])
            status = row["status"].strip()
            if not identifier or rank < 1 or identifier in allocations or rank in ranks:
                raise ValueError("Allocation IDs and positive daily ranks must be unique.")
            expected = "kept" if rank <= context["H_cut"] else "displaced" if rank <= context["H"] else "no_crew"
            if status not in STATUSES or status != expected:
                raise ValueError(f"Saved allocation status is inconsistent for {identifier}.")
            allocations[identifier] = {"allocation_rank": rank, "status": status}
            ranks.add(rank)
    if ranks != set(range(1, len(allocations) + 1)):
        raise ValueError("Saved daily allocation ranks must be consecutive from 1.")
    return {**context, "allocations": allocations}


def attach_allocation_context(records, context):
    identifiers = [record["fire_id"] for record in records]
    if len(set(identifiers)) != len(identifiers) or set(identifiers) != set(context["allocations"]):
        raise ValueError("Displayed fires and saved allocation IDs must match completely.")
    return [{**{key: record[key] for key in CANDIDATE_FIELDS if key in record},
             "allocation_rank": context["allocations"][record["fire_id"]]["allocation_rank"],
             "status": context["allocations"][record["fire_id"]]["status"]} for record in records]


def select_review_candidates(records, H, H_cut):
    _validate_counts(H, H_cut)
    by_rank, identifiers = {}, set()
    for record in records:
        rank, identifier = record["allocation_rank"], record["fire_id"]
        if type(rank) is not int or rank < 1 or rank in by_rank or identifier in identifiers:
            raise ValueError("Review records require unique fire IDs and positive daily ranks.")
        if record.get("status") not in STATUSES:
            raise ValueError("Review records require a saved allocation status.")
        by_rank[rank] = record
        identifiers.add(identifier)
    candidates = {}

    def include(record, reason):
        if record is None:
            return
        identifier = record["fire_id"]
        if identifier not in candidates:
            candidates[identifier] = {key: record[key] for key in CANDIDATE_FIELDS if key in record}
            candidates[identifier]["review_reason"] = []
        if reason not in candidates[identifier]["review_reason"]:
            candidates[identifier]["review_reason"].append(reason)

    last = by_rank.get(H_cut)
    if last is not None and last["status"] == "kept":
        include(last, "last_kept")
    for rank in (H_cut + 1, H_cut + 2):
        include(by_rank.get(rank), "cutoff_boundary")
    proximity = []
    for record in records:
        distance = record.get("nearest_community_distance_km")
        if record["status"] in ("displaced", "no_crew") and isinstance(distance, (int, float)) and not isinstance(distance, bool) and math.isfinite(distance) and distance >= 0:
            proximity.append(record)
    for record in sorted(proximity, key=lambda r: (r["nearest_community_distance_km"], r["fire_id"]))[:2]:
        include(record, "proximity_exception")
    return list(candidates.values())
