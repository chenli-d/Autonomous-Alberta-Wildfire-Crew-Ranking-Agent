"""Deterministic validation and copy-only crew assignment application."""
import json

from app.agent_review import RESPONSE_SCHEMA, INPUT_FIELDS
from app.review_service import select_review_candidates


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate keys in agent response.")
        result[key] = value
    return result


def original_assignments(records, H_cut):
    if type(H_cut) is not int or H_cut < 0:
        raise ValueError("Invalid crew count.")
    result = {r["fire_id"]: r["status"] == "kept" for r in records}
    if len(result) != len(records) or sum(result.values()) != min(H_cut, len(records)):
        raise ValueError("Original allocation does not match crew count.")
    return result


def validate_agent_decision(raw, records, H, H_cut):
    original = original_assignments(records, H_cut)
    candidates = select_review_candidates(records, H, H_cut)
    decision = json.loads(raw, object_pairs_hook=_unique_object) if isinstance(raw, str) else raw
    if type(decision) is not dict or set(decision) != set(RESPONSE_SCHEMA["required"]):
        raise ValueError("Agent response has an invalid schema.")
    if decision["decision"] not in ("KEEP_ORIGINAL", "SWAP"):
        raise ValueError("Unknown agent decision.")
    if not isinstance(decision["reason"], str) or not decision["reason"].strip() or len(decision["reason"]) > 2000:
        raise ValueError("Agent reason must be concise text.")
    if type(decision["evidence"]) is not list or len(decision["evidence"]) > 20 or any(type(x) is not str or len(x) > 2000 for x in decision["evidence"]):
        raise ValueError("Agent evidence must be a list of concise text.")
    promote, displace = decision["promote_fire_id"], decision["displace_fire_id"]
    if any(x is not None and type(x) is not str for x in (promote, displace)):
        raise ValueError("Agent fire IDs must be strings or null.")
    final = original.copy()
    if decision["decision"] == "KEEP_ORIGINAL":
        if promote is not None or displace is not None:
            raise ValueError("KEEP_ORIGINAL cannot change assignments.")
    else:
        last = [r for r in candidates if "last_kept" in r["review_reason"]]
        eligible = {r["fire_id"] for r in candidates if r["status"] in ("displaced", "no_crew")}
        if len(last) != 1 or displace != last[0]["fire_id"] or promote not in eligible or promote == displace:
            raise ValueError("Swap must promote a shortlisted no-crew fire and displace only the last-kept fire.")
        final[displace], final[promote] = False, True
        if {k for k in final if final[k] != original[k]} != {promote, displace}:
            raise ValueError("Swap changed unrelated crew assignments.")
    if sum(final.values()) != min(H_cut, len(records)):
        raise ValueError("Crew count changed.")
    return dict(decision), final


def build_ranking_proposal(raw, records, H, H_cut):
    """Validate one boundary swap, then construct a separate daily ranking proposal."""
    decision, _ = validate_agent_decision(raw, records, H, H_cut)
    ordered = sorted(records, key=lambda row: row["allocation_rank"])
    if decision["decision"] == "SWAP":
        positions = {row["fire_id"]: index for index, row in enumerate(ordered)}
        a, b = positions[decision["promote_fire_id"]], positions[decision["displace_fire_id"]]
        ordered[a], ordered[b] = ordered[b], ordered[a]
    proposal = [{**{key: row[key] for key in INPUT_FIELDS if key in row},
                 "model_daily_rank": row["allocation_rank"], "proposed_rank": index}
                for index, row in enumerate(ordered, start=1)]
    return decision, proposal


def apply_agent_decision(raw, records, H, H_cut):
    # Revalidate immediately before application; source records are never mutated.
    return validate_agent_decision(raw, records, H, H_cut)[1]
