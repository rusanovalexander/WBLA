"""
ANALYSIS Phase - Extracted from app.py

Lines 334-515
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

def render_phase_analysis():
    st.header("📋 Phase 1: Teaser Analysis")
    st.info(f"📄 Teaser: {st.session_state.teaser_file} ({len(st.session_state.teaser_text):,} chars)")

    if not st.session_state.extracted_data:
        if st.button("🔍 Run Agentic Analysis", type="primary", use_container_width=True):
            with st.spinner("Process Analyst analyzing teaser with autonomous RAG searches..."):
                result = run_agentic_analysis(
                    teaser_text=st.session_state.teaser_text,
                    search_procedure_fn=tool_search_procedure,
                    tracer=get_tracer(),
                    governance_context=st.session_state.get("governance_context"),
                )

                st.session_state.extracted_data = result.get("full_analysis", "") or ""
                st.session_state.process_path = result.get("process_path", "") or ""
                st.session_state.origination_method = result.get("origination_method", "") or ""
                st.session_state.procedure_sources = result.get("procedure_sources", {})
                st.session_state.assessment_reasoning = result.get("assessment_reasoning", "")
                st.session_state.origination_reasoning = result.get("origination_reasoning", "")
                st.session_state.decision_found = result.get("decision_found", False)
                st.session_state.decision_confidence = result.get("decision_confidence", "NONE")

                decision = create_process_decision(
                    result.get("process_path") or "", result.get("origination_method") or "",
                    result.get("full_analysis", "") or "", result.get("procedure_sources", {}),
                    result.get("assessment_reasoning", ""),
                    result.get("origination_reasoning", ""),
                    result.get("decision_found", False),
                    result.get("decision_confidence", "NONE"),
                )
                st.session_state.process_decision = decision.model_dump()

                insights = run_orchestrator_decision(
                    "ANALYSIS",
                    {"Analysis": result["full_analysis"][:3000]},
                    {"Teaser": st.session_state.teaser_text[:1500]},
                    get_tracer(),
                    governance_context=st.session_state.get("governance_context"),
                )
                st.session_state.orchestrator_insights = insights.full_text
                st.session_state.orchestrator_flags = [f.model_dump() for f in insights.flags]
                st.session_state.orchestrator_recommendations = insights.recommendations
                st.session_state.orchestrator_routing = {
                    "can_proceed": insights.can_proceed,
                    "requires_human_review": insights.requires_human_review,
                    "suggested_additional_steps": insights.suggested_additional_steps,
                    "block_reason": insights.block_reason,
                }
                st.rerun()

    if st.session_state.extracted_data:
        st.subheader("📊 Agent Activity")
        render_agent_dashboard(get_tracer())
        st.divider()

        with st.expander("📋 Full Analysis", expanded=True):
            st.markdown(st.session_state.extracted_data)

        # === PROCESS PATH APPROVAL — handles both autonomous and manual ===
        st.subheader("🔒 Process Path Decision")
        decision = st.session_state.get("process_decision", {})

        if decision and not decision.get("locked"):
            if st.session_state.decision_found:
                # Agent made a decision — show it for approval
                conf = st.session_state.decision_confidence
                conf_color = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(conf, "⚪")

                st.success(f"Agent determined (confidence: {conf_color} {conf}):")
                col1, col2 = st.columns(2)
                with col1:
                    st.info(f"**Assessment:** {decision.get('assessment_approach', 'N/A')}")
                with col2:
                    st.info(f"**Origination:** {decision.get('origination_method', 'N/A')}")

                evidence = decision.get("evidence", {})
                if evidence.get("reasoning"):
                    st.caption(f"Reasoning: {evidence['reasoning'][:400]}")

                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("✅ Approve & Lock", type="primary", use_container_width=True):
                        st.session_state.process_decision["locked"] = True
                        st.session_state.process_decision_locked = True
                        st.rerun()
                with col2:
                    if st.button("✏️ Override", use_container_width=True):
                        st.session_state["show_manual_path"] = True
                        st.rerun()
                with col3:
                    if st.button("🔄 Re-analyze", use_container_width=True):
                        st.session_state.extracted_data = ""
                        st.session_state.process_decision = None
                        st.session_state.decision_found = False
                        st.rerun()
            else:
                # Agent could NOT decide — human MUST choose
                st.warning(
                    "⚠️ **Agent could not determine the process path.** "
                    "The analysis did not produce a clear recommendation. "
                    "Please select manually based on the analysis above."
                )
                st.session_state["show_manual_path"] = True

            # Manual selection (shown when agent failed OR user clicked Override)
            if st.session_state.get("show_manual_path"):
                st.markdown("**Manual Process Path Selection:**")
                st.caption("Enter the assessment approach and origination method as defined in your Procedure document.")
                assessment = st.text_input(
                    "Assessment Approach:",
                    value=st.session_state.process_path or "",
                    key="manual_assessment",
                    placeholder="Enter the assessment approach from your Procedure",
                )
                origination = st.text_input(
                    "Origination Method:",
                    value=st.session_state.origination_method or "",
                    key="manual_origination",
                    placeholder="Enter the origination method from your Procedure",
                )
                manual_reason = st.text_input("Reason for selection:", key="manual_reason")

                if st.button("🔒 Lock Manual Selection", type="primary", use_container_width=True):
                    st.session_state.process_path = assessment
                    st.session_state.origination_method = origination
                    st.session_state.process_decision = {
                        "assessment_approach": assessment,
                        "origination_method": origination,
                        "locked": True,
                        "evidence": {"reasoning": f"Human override: {manual_reason}", "deal_size": "See analysis"},
                    }
                    st.session_state.process_decision_locked = True
                    st.session_state.change_log.record_change(
                        "manual_input", "Process Path",
                        f"{st.session_state.get('process_path', '')}/{st.session_state.get('origination_method', '')}",
                        f"{assessment}/{origination}", "ANALYSIS"
                    )
                    st.rerun()

        elif decision and decision.get("locked"):
            st.success(f"🔒 Locked: {decision['assessment_approach']} / {decision['origination_method']}")

            # === ORCHESTRATOR ROUTING GATE ===
            routing = st.session_state.get("orchestrator_routing", {})
            can_proceed = routing.get("can_proceed", True)
            requires_review = routing.get("requires_human_review", False)
            block_reason = routing.get("block_reason", "")
            additional_steps = routing.get("suggested_additional_steps", [])

            if not can_proceed:
                st.error(f"🚫 **Orchestrator blocks progression:** {block_reason}")
                st.warning("Address the issues above before continuing, or override:")
                if st.checkbox("I acknowledge the risks and wish to override the block"):
                    st.session_state.change_log.record_change(
                        "manual_input", "Orchestrator Override", "blocked", "overridden", "ANALYSIS"
                    )
                    if st.button("➡️ Continue to Requirements", type="primary", use_container_width=True):
                        advance_phase("PROCESS_GAPS")
                        st.rerun()
            elif requires_review:
                st.warning("⚠️ **Orchestrator recommends human review before proceeding:**")
                for step in additional_steps:
                    st.caption(f"  • Suggested: {step}")
                for flag in st.session_state.orchestrator_flags:
                    if flag.get("severity") == "HIGH":
                        st.error(f"⚠️ HIGH: {flag['text'][:80]}")
                if st.checkbox("I have reviewed the flags and wish to proceed"):
                    if st.button("➡️ Continue to Requirements", type="primary", use_container_width=True):
                        advance_phase("PROCESS_GAPS")
                        st.rerun()
            else:
                if st.button("➡️ Continue to Requirements", type="primary", use_container_width=True):
                    advance_phase("PROCESS_GAPS")
                    st.rerun()


# =============================================================================
# Phase: PROCESS_GAPS — Dynamic Requirements
# =============================================================================

