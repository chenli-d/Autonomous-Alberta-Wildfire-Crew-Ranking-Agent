"""Automatic boundary assessment with run-bound, copy-only ranking proposals."""
import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timezone

import streamlit as st

from app.agent_review import build_agent_input, review_crew_cut, PROMPT_VERSION, POLICY
from app.agent_validation import original_assignments, build_ranking_proposal


def clear_human_review():
    for key in ("human_decision", "final_ranking"):
        st.session_state.pop(key, None)


def final_ranking_copy(proposal):
    return [{**{key: deepcopy(value) for key, value in row.items() if key != "proposed_rank"},
             "final_rank": row["proposed_rank"]}
            for row in proposal]


def show_agent_review(records, candidates, context, run_review=False):
    st.subheader("Agent boundary review")
    st.caption("RERANK proposes one boundary swap. Only a human can accept it; original RF results are preserved.")
    run_id = context["run_id"]
    try:
        original_assignments(records, context["H_cut"])
        agent_input = build_agent_input(candidates, records, context)
    except (ValueError, TypeError, KeyError) as error:
        st.session_state.pop("agent_trace", None)
        clear_human_review()
        st.warning(f"Agent assessment unavailable: {error}")
        return
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    settings = {key: value.isoformat() if hasattr(value, "isoformat") else value
                for key, value in context.get("settings", {}).items()}
    snapshot = {"run_id": run_id, "settings": settings, "input": agent_input,
                "model": model, "prompt_version": PROMPT_VERSION,
                "source_versions": context.get("source_versions")}
    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True, allow_nan=False).encode()).hexdigest()
    trace = st.session_state.get("agent_trace")
    if (st.session_state.get("agent_snapshot") != fingerprint or
            trace is not None and (trace.get("run_id") != run_id or trace.get("fingerprint") != fingerprint)):
        st.session_state.agent_snapshot = fingerprint
        st.session_state.pop("agent_trace", None)
        clear_human_review()
        trace = None
    # A repeated render of the same run cannot repeat the request, including failures.
    if run_review and trace is None:
        trace = {"timestamp": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
                 "fingerprint": fingerprint, "settings": settings, "model": model,
                 "prompt_version": PROMPT_VERSION, "policy": POLICY,
                 "sanitized_input": agent_input, "raw_structured_response": None,
                 "validation": {"valid": False}, "recommendation": None,
                 "proposed_ranking": None, "status": "unavailable",
                 "final_action": "PROPOSAL_NOT_APPLIED"}
        try:
            if not records or agent_input["last_kept"] is None or not agent_input["challengers"]:
                reason = ("No assessed fires are available." if not records else
                          "No eligible boundary swap is available for the current crew capacity and shortlist.")
                raw = {"decision": "KEEP_ORIGINAL", "promote_fire_id": None,
                       "displace_fire_id": None, "reason": reason, "evidence": []}
                trace["status"] = "deterministic_keep"
            else:
                if not os.environ.get("OPENAI_API_KEY", "").strip():
                    raise ValueError("Agent assessment skipped: set OPENAI_API_KEY in the project .env or server environment and run assessment again.")
                with st.spinner("Reviewing fresh model allocation…"):
                    raw = review_crew_cut(agent_input, model)
                trace["raw_structured_response"] = raw
                trace["status"] = "agent_review"
            decision, proposal = build_ranking_proposal(raw, records, context["H"], context["H_cut"])
            trace["decision"] = decision
            trace["recommendation"] = "KEEP" if decision["decision"] == "KEEP_ORIGINAL" else "RERANK"
            trace["proposed_ranking"] = proposal
            trace["validation"] = {"valid": True, "message": "Boundary and crew-count checks passed."}
        except (ValueError, TypeError, KeyError) as error:
            trace["status"] = "unavailable"
            trace["validation"] = {"valid": False, "message": str(error)}
        st.session_state.agent_trace = trace
    if trace is None:
        clear_human_review()
        st.info("No current agent assessment. Run assessment again to review the current model results; community refresh invalidates prior proposals.")
        return
    if not trace["validation"]["valid"]:
        clear_human_review()
        trace["final_action"] = "PROPOSAL_NOT_APPLIED"
        st.warning("Agent assessment unavailable. " + trace["validation"].get("message", "Validation failed."))
    else:
        st.write("Agent recommendation: " + trace["recommendation"])
        if trace["status"] == "deterministic_keep":
            st.caption("Deterministic KEEP: no agent API request was made.")
        st.write(trace["decision"]["reason"])
        for evidence in trace["decision"]["evidence"]:
            st.write("• " + evidence)
        st.subheader("Proposed daily ranking")
        proposal = trace["proposed_ranking"]
        if proposal:
            st.dataframe([{"fire_id": row["fire_id"], "Model daily rank": row["model_daily_rank"],
                           "Proposed rank": row["proposed_rank"], "Annual RF rank": row.get("rank"),
                           "RF probability": row.get("rf_probability"), "Saved model status": row["status"]}
                          for row in proposal], hide_index=True)
        else:
            st.info("The model ranking and proposal are both empty.")
        human = st.session_state.get("human_decision")
        if human is not None and (human.get("run_id") != run_id or human.get("fingerprint") != fingerprint):
            clear_human_review()
            human = None
        keep_decision = {"decision": "KEEP_ORIGINAL", "promote_fire_id": None,
                         "displace_fire_id": None, "reason": "Original model ranking retained", "evidence": []}
        if trace["recommendation"] == "KEEP":
            st.info("No reranking proposed")
            _, model_order = build_ranking_proposal(keep_decision, records, context["H"], context["H_cut"])
            st.session_state.final_ranking = final_ranking_copy(model_order)
            trace["final_action"] = "MODEL_RETAINED"
        else:
            if human is None:
                st.session_state.pop("final_ranking", None)
                trace["final_action"] = "PROPOSAL_NOT_APPLIED"
            decision = trace["decision"]
            st.write(f"Proposed boundary swap: promote {decision['promote_fire_id']}; displace {decision['displace_fire_id']}.")
            columns = st.columns(2)
            accept = columns[0].button("Accept agent reranking", disabled=human is not None,
                                       key=f"accept_agent_{run_id}_{fingerprint}")
            retain = columns[1].button("Keep model ranking", disabled=human is not None,
                                       key=f"keep_model_{run_id}_{fingerprint}")
            if human is None and (accept or retain):
                try:
                    if accept:
                        validated, final = build_ranking_proposal(trace["raw_structured_response"], records,
                                                                  context["H"], context["H_cut"])
                        if validated != decision or final != proposal:
                            raise ValueError("Stored proposal no longer matches the validated agent response.")
                    else:
                        _, final = build_ranking_proposal(keep_decision, records, context["H"], context["H_cut"])
                    st.session_state.human_decision = {"run_id": run_id, "fingerprint": fingerprint,
                                                       "choice": "ACCEPT" if accept else "KEEP_MODEL"}
                    st.session_state.final_ranking = final_ranking_copy(final)
                    st.rerun()
                except (ValueError, TypeError, KeyError) as error:
                    clear_human_review()
                    st.error(f"Unable to finalize ranking: {error}")
            if human is None:
                st.info("Pending human review")
            elif human["choice"] == "ACCEPT":
                st.success("Agent proposal accepted")
                trace["final_action"] = "AGENT_PROPOSAL_ACCEPTED"
            else:
                st.info("Original model ranking retained")
                trace["final_action"] = "MODEL_RETAINED"
        final = st.session_state.get("final_ranking")
        if final is not None:
            st.subheader("Final accepted daily ranking")
            if final:
                st.dataframe([{"fire_id": row["fire_id"], "Final rank": row["final_rank"],
                               "Original model daily rank": row["model_daily_rank"],
                               "Annual RF rank": row.get("rank"), "Saved model status": row["status"]}
                              for row in final], hide_index=True)
            else:
                st.info("The final ranking is empty.")
    trace["human_decision"] = deepcopy(st.session_state.get("human_decision"))
    trace["final_ranking"] = deepcopy(st.session_state.get("final_ranking"))
    st.download_button("Download agent review trace", json.dumps(trace, indent=2, allow_nan=False),
                       "crew_review_trace.json", "application/json")
