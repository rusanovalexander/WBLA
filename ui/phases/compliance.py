"""
COMPLIANCE Phase - Extracted from app.py

Lines 1427-1646
"""

import streamlit as st
from pathlib import Path
from datetime import datetime
import json

# Import all necessary items (add as needed based on actual usage)
from config.settings import *
from tools.document_loader import *
from tools.rag_search import *
from core.orchestration import *
from core.llm_client import *
from agents import *
from ui.utils.session_state import get_tracer, advance_phase
from ui.components.agent_dashboard import render_agent_dashboard

def render_phase_compliance():
    st.header("⚖️ Phase 3: Compliance Assessment")

    # Auto-recover: if compliance result exists but checks weren't extracted, retry extraction
    if st.session_state.compliance_result and not st.session_state.compliance_checks:
        with st.spinner("Re-extracting compliance checks from previous analysis..."):
            from core.orchestration import _extract_compliance_checks
            checks = _extract_compliance_checks(st.session_state.compliance_result, get_tracer())
            if checks:
                st.session_state.compliance_checks = checks

    if not st.session_state.compliance_result:
        if st.button("🔍 Run Agentic Compliance Check", type="primary", use_container_width=True):
            with st.spinner("Compliance Advisor searching Guidelines and assessing deal..."):
                # Wrap search function to capture RAG evidence
                rag_evidence = []

                def _logging_search_guidelines(query, num_results=5):
                    result = tool_search_guidelines(query, num_results)
                    rag_evidence.append({
                        "query": query,
                        "status": result.get("status", "ERROR"),
                        "num_results": result.get("num_results", 0),
                        "results": [
                            {
                                "title": r.get("title", ""),
                                "doc_type": r.get("doc_type", ""),
                                "content": r.get("content", "")[:2000],
                            }
                            for r in result.get("results", [])
                        ],
                    })
                    return result

                result_text, checks = run_agentic_compliance(
                    requirements=st.session_state.process_requirements,
                    teaser_text=st.session_state.teaser_text,
                    extracted_data=st.session_state.extracted_data,
                    search_guidelines_fn=_logging_search_guidelines,
                    tracer=get_tracer(),
                    governance_context=st.session_state.get("governance_context"),
                )
                st.session_state.compliance_result = result_text
                st.session_state.compliance_checks = checks
                st.session_state.guideline_sources = rag_evidence

                insights = run_orchestrator_decision(
                    "COMPLIANCE",
                    {"Compliance": result_text[:3000]},
                    {"Process Path": st.session_state.process_path},
                    get_tracer(),
                    governance_context=st.session_state.get("governance_context"),
                )
                st.session_state.orchestrator_insights = insights.full_text
                st.session_state.orchestrator_flags = [f.model_dump() for f in insights.flags]
                st.session_state.orchestrator_routing = {
                    "can_proceed": insights.can_proceed,
                    "requires_human_review": insights.requires_human_review,
                    "suggested_additional_steps": insights.suggested_additional_steps,
                    "block_reason": insights.block_reason,
                }
                st.rerun()

    if st.session_state.compliance_result:
        st.subheader("📊 Agent Activity")
        render_agent_dashboard(get_tracer())
        st.divider()

        # Dynamic compliance badges — whatever the agent checked
        checks = st.session_state.compliance_checks
        if checks:
            st.subheader(f"Compliance Matrix ({len(checks)} criteria)")
            cols_per_row = min(len(checks), 5)
            for row_start in range(0, len(checks), cols_per_row):
                row_checks = checks[row_start:row_start + cols_per_row]
                cols = st.columns(len(row_checks))
                for j, check in enumerate(row_checks):
                    with cols[j]:
                        status = check.get("status", "REVIEW")
                        icon = "✅" if status == "PASS" else ("❌" if status == "FAIL" else "⚠️")
                        criterion = check.get("criterion", "?")
                        st.metric(criterion[:20], icon)
                        if check.get("reference"):
                            st.caption(check["reference"])

            # Show FAIL/REVIEW details
            issues = [c for c in checks if c.get("status") in ("FAIL", "REVIEW")]
            if issues:
                st.subheader(f"⚠️ Issues ({len(issues)})")
                for issue in issues:
                    severity = "🔴" if issue.get("status") == "FAIL" else "🟡"
                    st.write(
                        f"{severity} **{issue['criterion']}**: "
                        f"Guideline: {issue.get('guideline_limit', '?')} vs "
                        f"Deal: {issue.get('deal_value', '?')} — "
                        f"{issue.get('evidence', '')}"
                    )
        elif not checks:
            # AG-2: Detect when compliance text exists but structured extraction failed
            st.warning("⚠️ No structured compliance checks could be extracted from the agent's analysis.")
            if st.session_state.compliance_result and len(st.session_state.compliance_result.strip()) > 100:
                st.error(
                    "🚫 **Compliance analysis was received but structured data couldn't be extracted.** "
                    "Please review the raw compliance report below before proceeding."
                )
                # Manual retry button
                if st.button("🔄 Retry Compliance Extraction", use_container_width=True):
                    with st.spinner("Re-extracting compliance checks..."):
                        from core.orchestration import _extract_compliance_checks
                        retry_checks = _extract_compliance_checks(
                            st.session_state.compliance_result, get_tracer()
                        )
                        if retry_checks:
                            st.session_state.compliance_checks = retry_checks
                            st.success(f"✅ Successfully extracted {len(retry_checks)} compliance checks!")
                            st.rerun()
                        else:
                            st.error("Extraction failed again. Please review the raw report below and proceed manually.")

        with st.expander("📋 Full Compliance Report", expanded=False):
            st.markdown(st.session_state.compliance_result)

        # RAG Evidence Panel — show actual data retrieved from Guidelines
        rag_evidence = st.session_state.get("guideline_sources", [])
        if rag_evidence:
            with st.expander(f"🔍 RAG Evidence — {len(rag_evidence)} searches performed", expanded=False):
                st.caption(
                    "This section shows the **actual data retrieved from your Guidelines document** "
                    "via RAG search. Use it to verify that the compliance checks are grounded in real document content, "
                    "not hallucinated."
                )
                for i, evidence in enumerate(rag_evidence, 1):
                    query = evidence.get("query", "")
                    status = evidence.get("status", "ERROR")
                    results = evidence.get("results", [])

                    status_icon = "✅" if status == "OK" and results else "❌"
                    st.markdown(f"**Search {i}:** `{query}` {status_icon} ({len(results)} results)")

                    if not results:
                        st.warning(f"  No results returned for this query")
                    else:
                        for j, r in enumerate(results, 1):
                            title = r.get("title", "Untitled")
                            doc_type = r.get("doc_type", "Unknown")
                            content = r.get("content", "")
                            with st.container():
                                st.caption(f"  📄 **[{doc_type}]** {title}")
                                if content:
                                    # Show first 500 chars of actual RAG content
                                    preview = content[:500]
                                    if len(content) > 500:
                                        preview += "..."
                                    st.text(preview)
                    st.divider()
        elif st.session_state.compliance_result:
            st.info("ℹ️ RAG evidence not captured for this run. Re-run compliance to see search evidence.")

        # Orchestrator routing gate
        routing = st.session_state.get("orchestrator_routing", {})
        can_proceed = routing.get("can_proceed", True)
        has_failures = any(c.get("status") == "FAIL" for c in checks)

        # AG-2: Also block when compliance text exists but extraction failed
        extraction_failed = (
            st.session_state.compliance_result
            and len(st.session_state.compliance_result.strip()) > 100
            and not checks
        )

        if has_failures or not can_proceed or extraction_failed:
            if extraction_failed:
                block_reason = "Compliance data received but could not be structured — review raw report"
            else:
                block_reason = routing.get("block_reason", "Compliance failures detected")
            st.error(f"🚫 **Cannot auto-proceed:** {block_reason}")
            ack_label = (
                "I have reviewed the raw compliance report and wish to proceed"
                if extraction_failed
                else "I acknowledge the compliance issues and wish to proceed to drafting"
            )
            if st.checkbox(ack_label):
                st.session_state.change_log.record_change(
                    "manual_input", "Compliance Override", "blocked", "overridden", "COMPLIANCE"
                )
                if st.button("➡️ Continue to Drafting", use_container_width=True):
                    advance_phase("DRAFTING")
                    st.rerun()
        else:
            if st.button("➡️ Continue to Drafting", type="primary", use_container_width=True):
                advance_phase("DRAFTING")
                st.rerun()


# =============================================================================
# Note: _build_drafting_context moved to ui/phases/drafting.py (where it's used)
# =============================================================================


