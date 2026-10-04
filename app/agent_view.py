"""Explicit review/apply UI; session-only assignments and downloadable audit trace."""
import hashlib
import json
import os
from datetime import datetime, timezone

import streamlit as st

from app.agent_review import build_agent_input, review_crew_cut, PROMPT_VERSION, POLICY
from app.agent_validation import original_assignments, validate_agent_decision, apply_agent_decision


def show_agent_review(records, candidates, context):
    st.subheader("Agent boundary review")
    st.caption("Review only the allocation boundary. RF ranks and saved allocation files are unchanged. A proposed swap requires Apply swap.")
    try:
        agent_input = build_agent_input(candidates)
        original = original_assignments(records, context["H_cut"])
    except ValueError as error:
        for key in ("agent_snapshot", "agent_trace", "final_crew_assignments"):
            st.session_state.pop(key, None)
        st.info(str(error))
        return
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    snapshot = {"input": agent_input, "allocation": {r["fire_id"]: {
        "status": r["status"], "allocation_rank": r["allocation_rank"], "rank": r.get("rank")
        } for r in records}, "date": context["allocation_date"], "H": context["H"],
        "H_cut": context["H_cut"], "model": model, "prompt_version": PROMPT_VERSION,
        "source_versions": context.get("source_versions")}
    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if st.session_state.get("agent_snapshot") != fingerprint:
        st.session_state.agent_snapshot = fingerprint
        st.session_state.pop("agent_trace", None)
        st.session_state.final_crew_assignments = original.copy()
    st.write(f"Original last-kept fire: {agent_input['last_kept']['fire_id']}")
    st.write("Shortlisted challengers: " + ", ".join(r["fire_id"] for r in agent_input["challengers"]))
    configured = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    if not configured:
        st.info("Set OPENAI_API_KEY in the project .env file or server environment, then restart Streamlit. Never paste the key into chat or commit it.")
    if st.button("Run agent review", disabled=not configured, key="run_agent_review"):
        # A new review starts from the unchanged saved RF allocation.
        st.session_state.final_crew_assignments = original.copy()
        trace = {"timestamp": datetime.now(timezone.utc).isoformat(), "fingerprint": fingerprint,
                 "model": model, "prompt_version": PROMPT_VERSION, "policy": POLICY,
                 "sanitized_input": agent_input, "raw_structured_response": None,
                 "validation": {"valid": False}, "final_action": "ORIGINAL_UNCHANGED",
                 "final_crew_assignments": original.copy()}
        try:
            with st.spinner("Reviewing allocation boundary…"):
                raw = review_crew_cut(agent_input, model)
            trace["raw_structured_response"] = raw
            decision, _ = validate_agent_decision(raw, records, context["H"], context["H_cut"])
            trace["decision"] = decision
            trace["validation"] = {"valid": True, "message": "Boundary and crew-count checks passed."}
        except (ValueError, TypeError) as error:
            trace["validation"] = {"valid": False, "message": str(error)}
        st.session_state.agent_trace = trace
    trace = st.session_state.get("agent_trace")
    if not trace:
        st.caption("Final allocation unchanged; no agent review has been run for this snapshot.")
        return
    if not trace["validation"]["valid"]:
        st.warning("Agent action rejected. " + trace["validation"].get("message", "Validation failed."))
    else:
        decision = trace["decision"]
        st.write("Agent decision: " + decision["decision"])
        st.write(decision["reason"])
        for evidence in decision["evidence"]:
            st.write("• " + evidence)
        st.caption(trace["validation"]["message"])
        if decision["decision"] == "SWAP":
            a, b = decision["displace_fire_id"], decision["promote_fire_id"]
            st.table([{"Fire": a, "Before": "crew", "Proposed after": "no crew"},
                      {"Fire": b, "Before": "no crew", "Proposed after": "crew"}])
            if st.button("Apply swap", disabled=trace["final_action"] == "SWAP_APPLIED", key="apply_agent_swap"):
                try:
                    final = apply_agent_decision(trace["raw_structured_response"], records, context["H"], context["H_cut"])
                    st.session_state.final_crew_assignments = final
                    trace["final_crew_assignments"] = final
                    trace["final_action"] = "SWAP_APPLIED"
                    st.rerun()
                except (ValueError, TypeError):
                    st.warning("Swap rejected during revalidation; original allocation retained.")
                    st.session_state.final_crew_assignments = original.copy()
    changed = trace["final_action"] == "SWAP_APPLIED"
    st.caption("Final allocation: one boundary swap applied; RF ranking unchanged." if changed else "Final allocation unchanged.")
    if changed:
        st.table([{"fire_id": r["fire_id"], "Annual RF rank": r.get("rank"),
                   "Saved status": r["status"], "Final crew assigned": st.session_state.final_crew_assignments[r["fire_id"]]}
                  for r in records])
    st.download_button("Download agent review trace", json.dumps(trace, indent=2, allow_nan=False),
                       "crew_review_trace.json", "application/json")
