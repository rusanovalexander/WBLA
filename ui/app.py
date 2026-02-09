"""
Credit Pack Multi-Agent PoC v3.2 — Streamlit Application (AUTONOMY FIXED)

Key changes from previous version:
- Orchestrator routing decisions gate phase transitions (not just display)
- Requirements are dynamically discovered per deal (no static 28-field schema)
- Section structure adapts to process path (lighter methods ≠ comprehensive methods)
- No silent fallbacks — all failures are visible to the user
- Process path defaults removed — agent must decide or human must choose
"""

import streamlit as st
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Any

# Setup
PROJECT_ROOT = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    PROJECT_ID, MODEL_PRO, MODEL_FLASH, VERSION,
    DATA_STORE_ID, TEASERS_FOLDER, EXAMPLES_FOLDER,
    setup_environment, validate_config,
)
setup_environment()

from tools.document_loader import (
    tool_load_document, tool_scan_data_folder,
    scan_data_folder, universal_loader,
)
from tools.rag_search import (
    tool_search_rag, tool_search_procedure, tool_search_guidelines,
    test_rag_connection,
)
from tools.change_tracker import ChangeLog
from tools.phase_manager import PhaseManager
from agents import (
    ORCHESTRATOR_INSTRUCTION,
    get_orchestrator_instruction,
    AgentCommunicationBus,
    create_process_analyst_responder,
    create_compliance_advisor_responder,
)
from core.tracing import TraceStore, set_tracer
from core.llm_client import call_llm, call_llm_streaming, call_llm_with_backoff
from core.orchestration import (
    run_agentic_analysis,
    run_agentic_compliance,
    run_orchestrator_decision,
    discover_requirements,
    generate_section_structure,
    draft_section,
    create_process_decision,
)
from core.parsers import (
    format_requirements_for_context,
    safe_extract_json,
)
from core.governance_discovery import run_governance_discovery, get_terminology_synonyms
from core.export import generate_docx, generate_audit_trail
from ui.components.sidebar import render_sidebar
from ui.components.agent_dashboard import render_agent_dashboard


# =============================================================================
# Page Config
# =============================================================================

st.set_page_config(
    page_title=f"Credit Pack PoC v{VERSION}",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =============================================================================
# Session State Init
# =============================================================================

def init_state():
    defaults = {
        "messages": [],
        "workflow_phase": "SETUP",
        "rag_ok": None,
        "teaser_text": "", "teaser_file": "",
        "example_text": "", "example_file": "",
        "extracted_data": "",
        "process_path": "", "origination_method": "",
        "assessment_reasoning": "", "origination_reasoning": "",
        "decision_found": False, "decision_confidence": "NONE",
        "procedure_sources": {},
        "process_decision": None, "process_decision_locked": False,
        "orchestrator_insights": "",
        "orchestrator_flags": [],
        "orchestrator_recommendations": [],
        "orchestrator_routing": {},  # NEW: routing decisions
        "process_requirements": [],
        "supplement_texts": {},
        "compliance_result": "", "compliance_checks": [],
        "guideline_sources": {},
        "proposed_structure": [], "section_drafts": {},
        "final_document": "",
        "agent_bus": None,
        "change_log": None,
        "phase_manager": None,
        "orch_chat_history": [], "orch_chat_active": False,
        "tracer": None,
        "governance_context": None,
        "governance_discovery_done": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if st.session_state.agent_bus is None:
        st.session_state.agent_bus = AgentCommunicationBus()
        # Register responders so Writer agent can query other agents (Level 3)
        st.session_state.agent_bus.register_responder(
            "ProcessAnalyst",
            create_process_analyst_responder(call_llm, MODEL_PRO)
        )
        st.session_state.agent_bus.register_responder(
            "ComplianceAdvisor",
            create_compliance_advisor_responder(call_llm, MODEL_PRO, tool_search_guidelines)
        )
    if st.session_state.change_log is None:
        st.session_state.change_log = ChangeLog()
    if st.session_state.phase_manager is None:
        st.session_state.phase_manager = PhaseManager()
    if st.session_state.tracer is None:
        st.session_state.tracer = TraceStore()
    # AG-H2: Bind session tracer to contextvars so core modules use it
    set_tracer(st.session_state.tracer)

init_state()

def get_tracer() -> TraceStore:
    return st.session_state.tracer


def _advance_phase(next_phase: str):
    """Advance workflow phase using PhaseManager with state snapshot."""
    pm = st.session_state.phase_manager
    # Build snapshot of current state for potential rollback
    snapshot = {
        "extracted_data": st.session_state.get("extracted_data", ""),
        "process_path": st.session_state.get("process_path", ""),
        "origination_method": st.session_state.get("origination_method", ""),
        "process_decision": st.session_state.get("process_decision"),
        "process_decision_locked": st.session_state.get("process_decision_locked", False),
        "process_requirements": list(st.session_state.get("process_requirements", [])),
        "compliance_result": st.session_state.get("compliance_result", ""),
        "compliance_checks": list(st.session_state.get("compliance_checks", [])),
        "section_drafts": dict(st.session_state.get("section_drafts", {})),
        "proposed_structure": list(st.session_state.get("proposed_structure", [])),
    }
    try:
        pm.advance_to(next_phase, snapshot)
        st.session_state.workflow_phase = next_phase  # ONLY on success
    except ValueError as e:
        # AG-H1: Log validation failures and BLOCK the transition
        change_log = st.session_state.get("change_log")
        if change_log:
            change_log.record_change(
                "system", "Phase Transition Blocked",
                st.session_state.get("workflow_phase", "?"),
                next_phase,
                f"PhaseManager validation failed: {e}",
            )
        st.error(f"Phase transition blocked: {e}")
        return  # Do NOT advance


# =============================================================================
# Orchestrator Chat Handler
# =============================================================================

def handle_orchestrator_chat(question: str) -> str:
    tracer = get_tracer()
    tracer.record("OrchestratorChat", "QUERY", question[:100])

    context = f"""Current Phase: {st.session_state.workflow_phase}
Process Path: {st.session_state.process_path}
Origination Method: {st.session_state.origination_method}
"""
    if st.session_state.extracted_data:
        context += f"\nExtracted Data (excerpt):\n{st.session_state.extracted_data[:2000]}"
    if st.session_state.compliance_result:
        context += f"\nCompliance (excerpt):\n{st.session_state.compliance_result[:2000]}"

    gov_ctx = st.session_state.get("governance_context")
    orchestrator_instr = get_orchestrator_instruction(gov_ctx)

    prompt = f"""{orchestrator_instr}

## CONTEXT
{context}

## HUMAN QUESTION
{question}

Answer concisely and helpfully.
"""
    result = call_llm(prompt, MODEL_PRO, 0.1, 2000, "OrchestratorChat", tracer)
    return result.text


# =============================================================================
# Phase: SETUP
# =============================================================================

def render_phase_setup():
    st.header("🏦 Credit Pack System")
    st.subheader(f"v{VERSION} — Autonomous Multi-Agent System")

    if st.session_state.rag_ok is None:
        with st.spinner("Testing RAG connection..."):
            rag_test = test_rag_connection()
            st.session_state.rag_ok = rag_test.get("connected", False)

    if st.session_state.rag_ok:
        st.success("✅ RAG connected to Vertex AI Search")
        # Run governance discovery once to learn the institution's framework
        if not st.session_state.governance_discovery_done:
            with st.spinner("🔍 Analyzing governance documents (Procedure & Guidelines)..."):
                gov_ctx = run_governance_discovery(
                    search_procedure_fn=tool_search_procedure,
                    search_guidelines_fn=tool_search_guidelines,
                    tracer=get_tracer(),
                )
                st.session_state.governance_context = gov_ctx
                st.session_state.governance_discovery_done = True
                # AG-4: Re-register agent responders with governance context
                bus = st.session_state.get("agent_bus")
                if bus and gov_ctx and gov_ctx.get("discovery_status") in ("complete", "partial"):
                    bus.register_responder(
                        "ProcessAnalyst",
                        create_process_analyst_responder(call_llm, MODEL_PRO, gov_ctx)
                    )
                    bus.register_responder(
                        "ComplianceAdvisor",
                        create_compliance_advisor_responder(call_llm, MODEL_PRO, tool_search_guidelines, gov_ctx)
                    )
        # Show discovery results
        gov_ctx = st.session_state.governance_context
        if gov_ctx and gov_ctx.get("discovery_status") == "complete":
            st.success(
                f"📚 Governance framework discovered: "
                f"{len(gov_ctx.get('requirement_categories', []))} categories, "
                f"{len(gov_ctx.get('compliance_framework', []))} compliance criteria, "
                f"{len(gov_ctx.get('risk_taxonomy', []))} risk categories"
            )
        elif gov_ctx and gov_ctx.get("discovery_status") == "partial":
            st.info("📚 Governance framework partially discovered — some prompts will use defaults")
        elif gov_ctx:
            st.warning("📚 Could not discover governance framework — using default prompts")
    else:
        st.warning("⚠️ RAG not connected — agents will not be able to search Procedure/Guidelines")

    st.subheader("📁 Documents")
    docs = scan_data_folder()

    # --- Teaser upload ---
    st.markdown("**Deal Teaser** (required)")
    if docs.get("teasers"):
        for f in docs["teasers"]:
            st.write(f"📄 {Path(f).name}")
    uploaded_teaser = st.file_uploader(
        "Upload deal teaser",
        type=["pdf", "docx", "txt", "xlsx", "xls", "csv", "png", "jpg", "html", "htm", "json", "pptx"],
        accept_multiple_files=False,
        key="setup_teaser_upload",
    )
    if uploaded_teaser:
        dest = TEASERS_FOLDER / uploaded_teaser.name
        with open(dest, "wb") as out:
            out.write(uploaded_teaser.getbuffer())
        st.success(f"Uploaded teaser: {uploaded_teaser.name}")

    # --- Example credit pack upload ---
    st.markdown("**Example Credit Pack** (optional — used as style/structure reference for drafting)")
    if docs.get("examples"):
        for f in docs["examples"]:
            st.write(f"📄 {Path(f).name}")
    uploaded_example = st.file_uploader(
        "Upload example credit pack",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=False,
        key="setup_example_upload",
    )
    if uploaded_example:
        dest = EXAMPLES_FOLDER / uploaded_example.name
        with open(dest, "wb") as out:
            out.write(uploaded_example.getbuffer())
        st.success(f"Uploaded example: {uploaded_example.name}")

    if st.button("📋 Load Documents & Start", type="primary", use_container_width=True):
        with st.spinner("Loading documents..."):
            # Re-scan to pick up any freshly uploaded files
            docs = scan_data_folder()
            if docs["teasers"]:
                result = tool_load_document(docs["teasers"][0], force_ocr=True)
                if result["status"] == "OK":
                    st.session_state.teaser_text = result["text"]
                    st.session_state.teaser_file = result["file_name"]
            if docs["examples"]:
                result = tool_load_document(docs["examples"][0])
                if result["status"] == "OK":
                    st.session_state.example_text = result["text"]
                    st.session_state.example_file = result["file_name"]

            if st.session_state.teaser_text:
                _advance_phase("ANALYSIS")
                st.rerun()
            else:
                st.error("No teaser document found. Upload a teaser file above.")


# =============================================================================
# Phase: ANALYSIS
# =============================================================================

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

                st.session_state.extracted_data = result["full_analysis"]
                st.session_state.process_path = result["process_path"]
                st.session_state.origination_method = result["origination_method"]
                st.session_state.procedure_sources = result.get("procedure_sources", {})
                st.session_state.assessment_reasoning = result.get("assessment_reasoning", "")
                st.session_state.origination_reasoning = result.get("origination_reasoning", "")
                st.session_state.decision_found = result.get("decision_found", False)
                st.session_state.decision_confidence = result.get("decision_confidence", "NONE")

                decision = create_process_decision(
                    result["process_path"], result["origination_method"],
                    result["full_analysis"], result.get("procedure_sources", {}),
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
                    placeholder="e.g., Full Creditworthiness Assessment",
                )
                origination = st.text_input(
                    "Origination Method:",
                    value=st.session_state.origination_method or "",
                    key="manual_origination",
                    placeholder="e.g., Credit Rationale",
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
                        _advance_phase("PROCESS_GAPS")
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
                        _advance_phase("PROCESS_GAPS")
                        st.rerun()
            else:
                if st.button("➡️ Continue to Requirements", type="primary", use_container_width=True):
                    _advance_phase("PROCESS_GAPS")
                    st.rerun()


# =============================================================================
# Phase: PROCESS_GAPS — Dynamic Requirements
# =============================================================================

def render_phase_process_gaps():
    st.header("📝 Phase 2: Requirements & Gap Filling")

    if not st.session_state.process_requirements:
        with st.spinner("Discovering deal-specific requirements..."):
            tracer = get_tracer()

            # Dynamic discovery based on deal analysis and process path
            reqs = discover_requirements(
                analysis_text=st.session_state.extracted_data,
                assessment_approach=st.session_state.process_path,
                origination_method=st.session_state.origination_method,
                tracer=tracer,
                search_procedure_fn=tool_search_procedure,
                governance_context=st.session_state.get("governance_context"),
            )

            if reqs:
                st.session_state.process_requirements = reqs
            else:
                # Discovery failed — tell the user, don't silently fallback
                st.error(
                    "⚠️ **Requirements discovery failed.** "
                    "The system could not determine what information is needed for this deal. "
                    "You can add requirements manually below."
                )
                st.session_state.process_requirements = []

            # Auto-fill from analysis
            if st.session_state.process_requirements:
                _auto_fill_requirements()
                # Aggressive: auto-suggest remaining CRITICAL requirements individually
                _auto_suggest_critical_requirements()

            st.rerun()

    reqs = st.session_state.process_requirements
    filled = sum(1 for r in reqs if r.get("status") == "filled")
    pending = sum(1 for r in reqs if r.get("status") != "filled")

    if reqs:
        st.progress(filled / max(len(reqs), 1))
        st.caption(f"**{filled}** filled / **{pending}** remaining / **{len(reqs)}** total")

        # Show auto-fill summary if just completed
        if st.session_state.get("_autofill_count") is not None:
            count = st.session_state["_autofill_count"]
            if count > 0:
                st.success(f"✅ Auto-filled **{count}** requirements from the teaser")
            else:
                st.info("ℹ️ Auto-fill could not find values in the teaser. Use AI Suggest or Upload for individual requirements.")
            del st.session_state["_autofill_count"]

        # Re-run auto-fill button
        if pending > 0:
            with st.expander("🔄 Re-run auto-fill from teaser", expanded=False):
                st.caption("Try again to extract values from the teaser for all unfilled requirements.")
                if st.button("🔍 Re-run Auto-Fill", use_container_width=True):
                    _auto_fill_requirements()
                    st.rerun()

        # === Bulk file upload ===
        with st.expander("📁 Upload Supporting Documents", expanded=False):
            st.caption(
                "Upload files (valuations, financial models, term sheets, etc.) — "
                "the agent will analyze each file and auto-fill matching requirements."
            )
            bulk_files = st.file_uploader(
                "Upload documents:",
                type=["pdf", "docx", "xlsx", "xls", "txt", "csv", "png", "jpg", "html", "htm", "json", "pptx"],
                accept_multiple_files=True,
                key="bulk_upload_phase2",
            )
            if bulk_files:
                already_uploaded = st.session_state.get("_bulk_uploaded_files", set())
                new_files = [f for f in bulk_files if f.name not in already_uploaded]

                if new_files:
                    st.write(f"**{len(new_files)} new file(s)** ready to analyze")
                    if st.button("🔍 Analyze All Files", type="primary", use_container_width=True):
                        _bulk_analyze_files(new_files, reqs, get_tracer())
                        already = st.session_state.get("_bulk_uploaded_files", set())
                        for f in new_files:
                            already.add(f.name)
                        st.session_state["_bulk_uploaded_files"] = already
                        st.rerun()

                if st.session_state.supplement_texts:
                    st.caption(f"📎 {len(st.session_state.supplement_texts)} supplementary document(s) loaded — available for compliance & drafting")

        # Group by category
        categories = {}
        for r in reqs:
            cat = r.get("category", "GENERAL")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(r)

        for cat, cat_reqs in categories.items():
            cat_filled = sum(1 for r in cat_reqs if r.get("status") == "filled")
            st.subheader(f"{cat} ({cat_filled}/{len(cat_reqs)})")

            for i, req in enumerate(cat_reqs):
                global_idx = reqs.index(req)
                status_icon = "✅" if req.get("status") == "filled" else "⬜"
                priority_badge = "🔴" if req.get("priority") == "CRITICAL" else ("🟡" if req.get("priority") == "IMPORTANT" else "⚪")

                with st.expander(
                    f"{status_icon} {priority_badge} {req['name']}",
                    expanded=(req.get("status") != "filled")
                ):
                    if req.get("why_required"):
                        st.caption(f"_Why needed: {req['why_required']}_")

                    if req.get("status") == "filled":
                        value_preview = req["value"][:300] + "..." if len(req.get("value", "")) > 300 else req.get("value", "")
                        st.write(f"**Value:** {value_preview}")
                        st.caption(f"Source: {req.get('source', 'unknown')}")

                        new_val = st.text_area("Edit:", value=req.get("value", ""), key=f"edit_{global_idx}")
                        if new_val != req.get("value", "") and st.button("💾 Save", key=f"save_{global_idx}"):
                            old = req["value"]
                            req["value"] = new_val
                            st.session_state.change_log.record_change(
                                "requirement_edit", req["name"], old[:100], new_val[:100], "PROCESS_GAPS"
                            )
                            st.rerun()
                    else:
                        st.caption(req.get("description", ""))

                        # Check for pending results (suggestion or file extraction)
                        sug_key = f"_suggestion_{global_idx}"
                        pending_sug = st.session_state.get(sug_key)

                        if pending_sug:
                            # Show result from AI Suggest or File Upload
                            conf = pending_sug.get("confidence", "?")
                            conf_icon = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(conf, "⚪")
                            source_type = pending_sug.get("source_type", "analysis")
                            source_label = f"📄 From uploaded file: {pending_sug.get('file_name', '')}" if source_type == "file" else "🔍 From teaser/analysis"

                            st.success(f"{conf_icon} Found (confidence: {conf}) — {source_label}")
                            if pending_sug.get("source_quote"):
                                st.caption(f"Source: _{pending_sug['source_quote'][:300]}_")

                            confirmed = st.text_area(
                                "Confirm/edit value:",
                                value=pending_sug["value"],
                                key=f"confirm_{global_idx}",
                            )
                            col_a, col_b = st.columns(2)
                            with col_a:
                                if st.button("✅ Accept", key=f"acc_sug_{global_idx}"):
                                    req["value"] = confirmed
                                    req["status"] = "filled"
                                    req["source"] = f"{source_type}: {pending_sug.get('file_name', 'ai')}"
                                    req["suggestion_detail"] = f"[{conf}] {pending_sug.get('source_quote', '')[:200]}"
                                    del st.session_state[sug_key]
                                    st.rerun()
                            with col_b:
                                if st.button("❌ Dismiss", key=f"dismiss_sug_{global_idx}"):
                                    del st.session_state[sug_key]
                                    st.rerun()

                        else:
                            # === Three input methods ===
                            input_mode = st.radio(
                                "Input method:",
                                ["✏️ Manual", "🤖 AI Suggest", "📁 Upload File"],
                                horizontal=True,
                                key=f"mode_{global_idx}",
                                label_visibility="collapsed",
                            )

                            if input_mode == "✏️ Manual":
                                manual = st.text_area("Enter value:", key=f"manual_{global_idx}", height=80)
                                if manual and st.button("✅ Accept", key=f"accept_{global_idx}"):
                                    req["value"] = manual
                                    req["status"] = "filled"
                                    req["source"] = "manual"
                                    st.rerun()

                            elif input_mode == "🤖 AI Suggest":
                                st.caption("Search teaser and analysis for this value")
                                if st.button("🔍 Search", key=f"ai_{global_idx}", use_container_width=True):
                                    with st.spinner("Searching teaser for this value..."):
                                        parsed = _ai_suggest_requirement_with_retry(req, get_tracer())
                                        if parsed and parsed.get("value"):
                                            parsed["source_type"] = "analysis"
                                            st.session_state[sug_key] = parsed
                                            st.rerun()
                                        else:
                                            st.warning("Could not find this value in the teaser or analysis.")

                            elif input_mode == "📁 Upload File":
                                st.caption("Upload a document (PDF, DOCX, XLSX, TXT, CSV, HTML, JSON, PPTX) — the agent will extract the relevant value")
                                uploaded = st.file_uploader(
                                    "Upload file:",
                                    type=["pdf", "docx", "xlsx", "xls", "txt", "csv", "png", "jpg", "html", "htm", "json", "pptx"],
                                    key=f"upload_{global_idx}",
                                    label_visibility="collapsed",
                                )
                                if uploaded:
                                    if st.button("📄 Analyze File", key=f"analyze_{global_idx}", type="primary", use_container_width=True):
                                        with st.spinner(f"Analyzing {uploaded.name}..."):
                                            parsed = _extract_from_uploaded_file(
                                                uploaded, req, get_tracer()
                                            )
                                            if parsed and parsed.get("value"):
                                                parsed["source_type"] = "file"
                                                parsed["file_name"] = uploaded.name
                                                st.session_state[sug_key] = parsed
                                                st.rerun()
                                            else:
                                                st.warning(
                                                    f"Could not extract **{req['name']}** from {uploaded.name}. "
                                                    "The file may not contain this information, or try a different file."
                                                )

    # Add manual requirement
    st.divider()
    with st.expander("➕ Add Custom Requirement"):
        new_name = st.text_input("Requirement name:", key="new_req_name")
        new_desc = st.text_input("Description:", key="new_req_desc")
        new_why = st.text_input("Why needed for this deal:", key="new_req_why")
        new_priority = st.selectbox("Priority:", ["CRITICAL", "IMPORTANT", "SUPPORTING"], key="new_req_pri")
        if new_name and st.button("Add Requirement"):
            reqs.append({
                "id": len(reqs) + 1,
                "name": new_name,
                "description": new_desc,
                "why_required": new_why,
                "priority": new_priority,
                "category": "CUSTOM",
                "status": "pending",
                "value": "", "source": "", "evidence": "", "suggestion_detail": "",
            })
            st.rerun()

    # Continue gate — based on critical requirements
    st.divider()
    critical_reqs = [r for r in reqs if r.get("priority") == "CRITICAL"]
    critical_filled = sum(1 for r in critical_reqs if r.get("status") == "filled")

    if critical_reqs and critical_filled < len(critical_reqs):
        unfilled_critical = [r["name"] for r in critical_reqs if r.get("status") != "filled"]
        st.warning(f"⚠️ {len(unfilled_critical)} CRITICAL requirements unfilled: {', '.join(unfilled_critical[:5])}")
        if st.checkbox("Proceed anyway (not recommended)"):
            if st.button("➡️ Continue to Compliance", use_container_width=True):
                _advance_phase("COMPLIANCE")
                st.rerun()
    elif not reqs:
        st.info("No requirements defined. Add requirements above or continue.")
        if st.button("➡️ Continue to Compliance", use_container_width=True):
            _advance_phase("COMPLIANCE")
            st.rerun()
    else:
        if st.button("➡️ Continue to Compliance", type="primary", use_container_width=True):
            _advance_phase("COMPLIANCE")
            st.rerun()


def _auto_fill_requirements():
    """
    Auto-fill requirements from the teaser and analysis.

    Sends BOTH the raw teaser text AND the LLM analysis to maximize extraction.
    Uses descriptions so the LLM knows what to look for.
    """
    tracer = get_tracer()
    reqs = st.session_state.process_requirements
    unfilled = [r for r in reqs if r.get("status") != "filled"]

    if not unfilled:
        return

    tracer.record("AutoFill", "START", f"Auto-filling {len(unfilled)} requirements from teaser + analysis")

    # Include descriptions so LLM knows what to look for
    unfilled_for_prompt = [
        {
            "id": r["id"],
            "name": r["name"],
            "description": r.get("description", ""),
        }
        for r in unfilled
    ]
    unfilled_json = json.dumps(unfilled_for_prompt, indent=2)

    # KEY FIX: Include BOTH teaser text AND extracted analysis
    teaser = st.session_state.teaser_text or ""
    analysis = st.session_state.extracted_data or ""

    prompt = f"""You are extracting multiple values from a credit teaser and analysis.

## SOURCE DOCUMENTS:

### PRIMARY SOURCE - Teaser Document:
{teaser[:12000]}

### SECONDARY SOURCE - Analyst's Extraction:
{analysis[:5000]}

## REQUIREMENTS TO FILL:
{unfilled_json}

## EXTRACTION INSTRUCTIONS:

1. **SEMANTIC MATCHING:** Requirement names may differ from source terminology.
   Examples of equivalent terms:
{get_terminology_synonyms(st.session_state.get("governance_context"))}

   **Search for CONCEPTS, not exact words.** Be flexible in matching terminology.

2. **SEARCH THOROUGHLY:**
   - Read the ENTIRE teaser document, not just the beginning
   - Check the analysis if the teaser is unclear or incomplete
   - Look in multiple sections (financials, asset details, parties, narrative)
   - Information might be embedded in paragraphs, not explicit fields

3. **EXTRACT COMPLETELY:**
   - For tables and multi-part values, include ALL rows and components
   - For multi-paragraph descriptions, include everything relevant
   - Don't truncate or summarize complex values
   - Format tables as markdown if needed

4. **QUALITY RULES:**
   - Use EXACT values from teaser (don't round numbers)
   - Include source quote for verification
   - Skip requirements you truly cannot find (don't guess)
   - id must be a NUMBER matching requirement id

## OUTPUT FORMAT:

Return ONLY valid JSON between XML tags, with NO other text:

<json_output>
[
  {{"id": 1, "value": "[amount in deal currency]", "source_quote": "exact quote from teaser..."}},
  {{"id": 2, "value": "[entity name]", "source_quote": "exact quote from teaser..."}}
]
</json_output>

Examples:

Simple value:
<json_output>
[{{"id": 5, "value": "5 years", "source_quote": "facility tenor of 5 years"}}]
</json_output>

Multi-line value:
<json_output>
[{{"id": 8, "value": "Item A: detail one\\nItem B: detail two\\nTotal: combined detail", "source_quote": "the portfolio comprises Item A (detail one)..."}}]
</json_output>

Not found:
<json_output>
[]
</json_output>

CRITICAL RULES:
- Output ONLY the JSON array between <json_output></json_output> tags
- NO preambles like "Here is the JSON:" or "Based on the teaser:"
- NO explanations before or after the tags
- If you can't find any requirements, return empty array: <json_output>[]</json_output>

NOW: Extract ALL requirements you can find from the documents above. 
Use semantic matching to find values even if terminology differs.
Output ONLY <json_output> tags with JSON array inside, NO other text.
"""

    result = call_llm_with_backoff(prompt, MODEL_PRO, 0.0, 4000, "AutoFill", tracer, max_retries=5)

    tracer.record("AutoFill", "RAW_RESPONSE", f"LLM returned {len(result.text)} chars")

    fills = safe_extract_json(result.text, "array")

    if not fills:
        tracer.record("AutoFill", "PARSE_FAIL", f"Could not parse JSON from response: {result.text[:200]}")
        return

    fill_count = 0
    for fill in fills:
        # Normalize ID to int for comparison (LLM may return string or int)
        try:
            fill_id = int(fill.get("id", -1))
        except (ValueError, TypeError):
            continue

        value = fill.get("value", "").strip()
        if not value or value.upper() in ("NOT STATED", "NOT STATED IN TEASER", "N/A", "NOT FOUND", "NOT AVAILABLE", ""):
            continue

        for req in reqs:
            if int(req.get("id", -1)) == fill_id and req.get("status") != "filled":
                req["value"] = value
                req["status"] = "filled"
                req["source"] = "auto_extracted"
                req["evidence"] = fill.get("source_quote", "")
                fill_count += 1
                break

    tracer.record("AutoFill", "COMPLETE", f"Auto-filled {fill_count}/{len(unfilled)} requirements")
    st.session_state["_autofill_count"] = fill_count


def _auto_suggest_critical_requirements():
    """
    Aggressive auto-fill: after bulk auto-fill, individually search for
    remaining unfilled CRITICAL requirements using AI Suggest.

    This ensures maximum data capture without user intervention.
    Caps at 10 requirements to avoid rate limiting.
    """
    reqs = st.session_state.process_requirements
    tracer = get_tracer()

    critical_unfilled = [
        r for r in reqs
        if r.get("priority") == "CRITICAL" and r.get("status") != "filled"
    ]

    if not critical_unfilled:
        return

    tracer.record("AutoSuggest", "BATCH_START",
                  f"Auto-suggesting {len(critical_unfilled)} unfilled CRITICAL requirements")

    suggested_count = 0
    for req in critical_unfilled[:10]:  # Cap at 10 to avoid rate limits
        try:
            parsed = _ai_suggest_requirement(req, tracer)
            if parsed and parsed.get("value"):
                confidence = parsed.get("confidence", "MEDIUM")
                req["value"] = parsed["value"]
                req["status"] = "filled"
                req["source"] = f"auto_suggest ({confidence})"
                req["evidence"] = parsed.get("source_quote", "")
                req["suggestion_detail"] = f"[{confidence}] {parsed.get('source_quote', '')[:200]}"
                suggested_count += 1
        except Exception as e:
            tracer.record("AutoSuggest", "ERROR", f"{req['name']}: {str(e)[:100]}")
            continue

    tracer.record("AutoSuggest", "BATCH_COMPLETE",
                  f"Auto-suggested {suggested_count}/{len(critical_unfilled)} critical requirements")

    if suggested_count > 0:
        autofill_count = st.session_state.get("_autofill_count", 0)
        st.session_state["_autofill_count"] = autofill_count + suggested_count


def _ai_suggest_requirement(req: dict, tracer) -> dict | None:
    """
    Search teaser + analysis for a requirement value with ROBUST semantic extraction.
    
    Improvements:
    1. Semantic matching - searches for concepts, not just exact words
    2. XML output tags - constrains LLM response format
    3. Increased token budget - 3000 instead of 800 tokens
    4. Better examples - shows how to handle complex values
    5. Enhanced instructions - tells LLM to search thoroughly
    """
    teaser = st.session_state.teaser_text or ""
    analysis = st.session_state.extracted_data or ""
    
    tracer.record("AISuggest", "START", f"Searching for: {req['name']}")
    
    prompt = f"""You are extracting a specific value from a credit teaser and analysis.

## TARGET REQUIREMENT:
**Name:** {req['name']}
**Description:** {req.get('description', 'N/A')}
**Why Needed:** {req.get('why_required', 'N/A')}
**Expected Source:** {req.get('typical_source', 'teaser')}

## SOURCE DOCUMENTS:

### PRIMARY SOURCE - Teaser Document:
{teaser[:12000]}

### SECONDARY SOURCE - Analyst's Extraction (for reference):
{analysis[:5000]}

## EXTRACTION INSTRUCTIONS:

1. **SEMANTIC MATCHING:** The requirement name may use different terminology than the source documents.
   Examples of equivalent terms:
{get_terminology_synonyms(st.session_state.get("governance_context"))}

   **Search for the CONCEPT, not just the exact words.** Be flexible in matching.

2. **SEARCH THOROUGHLY:** 
   - Read the ENTIRE teaser, not just the beginning
   - Check the analysis if the teaser is unclear
   - Look in multiple sections (the info might be in financial summary, asset details, or narrative)
   - For multi-part requirements, search for each component

3. **EXTRACT COMPLETELY:**
   - If the value is a table or multi-part data, include ALL rows and components
   - If the value is a multi-paragraph description, include it all
   - If the value is a calculation, show the math
   - If the value spans multiple sentences or paragraphs, include the full context
   - Do NOT truncate or summarize unless the value is extremely long (>1000 words)

4. **CONFIDENCE ASSESSMENT:**
   - HIGH: Value is explicitly stated with clear source quote
   - MEDIUM: Value is reasonably inferred from available information  
   - LOW: Value is uncertain or requires assumptions
   - If truly not found anywhere, set value to empty string and confidence to LOW

5. **EXTRACTION FROM NATURAL LANGUAGE:**
   Since the analyst's extraction may be in prose format (not a rigid table), search for concepts
   expressed in natural language. The information might be embedded in paragraphs.

## OUTPUT FORMAT:

You MUST output ONLY valid JSON between the XML tags below, with NO other text before or after:

<json_output>
{{
  "value": "<the extracted value - can be multi-line or long, include everything relevant>",
  "source_quote": "<exact quote from source that contains this value - max 500 chars>",
  "confidence": "HIGH|MEDIUM|LOW",
  "found_in": "teaser|analysis|both"
}}
</json_output>

Examples:

Example 1 (Simple value):
<json_output>
{{
  "value": "50,000,000",
  "source_quote": "The senior facility of 50 million...",
  "confidence": "HIGH",
  "found_in": "teaser"
}}
</json_output>

Example 2 (Complex multi-line value):
<json_output>
{{
  "value": "Item A: detail one, detail two\\nItem B: detail three, detail four\\nTotal: combined summary",
  "source_quote": "The portfolio comprises Item A (detail one)...",
  "confidence": "HIGH",
  "found_in": "teaser"
}}
</json_output>

Example 3 (Semantic match):
<json_output>
{{
  "value": "15 years of relevant experience",
  "source_quote": "The company has a 15-year track record in the sector",
  "confidence": "HIGH",
  "found_in": "analysis"
}}
</json_output>

Example 4 (Not found):
<json_output>
{{
  "value": "",
  "source_quote": "",
  "confidence": "LOW",
  "found_in": ""
}}
</json_output>

NOW: Extract the requirement "{req['name']}" from the documents above.
Remember: Use SEMANTIC MATCHING - look for the concept, not just exact word matches.
Output ONLY the JSON between <json_output></json_output> tags with NO other text before or after.
"""
    
    # Increased token budget to handle complex multi-line values (sponsor profiles, rent rolls, etc.)
    # Use backoff retry to handle rate limits gracefully
    result = call_llm_with_backoff(prompt, MODEL_PRO, 0.0, 4000, "AISuggest", tracer)
    
    # Use improved parser with XML tag support
    parsed = safe_extract_json(result.text, "object")
    
    if parsed and parsed.get("value"):
        tracer.record(
            "AISuggest", "FOUND",
            f"{req['name']}: {str(parsed['value'])[:80]}... (confidence: {parsed.get('confidence', '?')})"
        )
    else:
        tracer.record("AISuggest", "NOT_FOUND", f"{req['name']}: no value found")
    
    return parsed


def _ai_suggest_requirement_with_retry(req: dict, tracer) -> dict | None:
    """
    Search for requirement value with intelligent retry.
    
    If first attempt fails, retry with:
    1. More specific search terms
    2. Alternative field names
    3. Direct teaser search without analysis clutter
    """
    
    # Attempt 1: Standard search with semantic matching
    result = _ai_suggest_requirement(req, tracer)
    if result and result.get("value"):
        return result
    
    tracer.record("AISuggest", "RETRY", f"First attempt failed for {req['name']}, trying refined search")
    
    # Attempt 2: Refined search with explicit alternative terms
    teaser = st.session_state.teaser_text or ""
    
    # Generate alternative search terms
    alternative_terms = _generate_alternative_terms(req['name'])
    
    prompt = f"""Find information in this teaser using FLEXIBLE term matching.

## TARGET:
**Primary requirement:** {req['name']}
**Alternative terms to search for:** {', '.join(alternative_terms[:6])}
**Description:** {req.get('description', 'N/A')}
**Context:** {req.get('why_required', 'N/A')}

## INSTRUCTIONS:
1. Search for the primary term AND all alternative terms
2. Look for the underlying CONCEPT even if exact words don't match
3. Be generous in interpretation - if something seems related, include it
4. The information might be phrased differently than the requirement name

## TEASER DOCUMENT:
{teaser[:12000]}

## OUTPUT:
Return ONLY valid JSON between the XML tags with NO other text:

<json_output>
{{
  "value": "<found value or empty string>",
  "source_quote": "<quote from teaser>",
  "confidence": "HIGH|MEDIUM|LOW",
  "found_with_term": "<which term/concept matched>"
}}
</json_output>

Be flexible and generous in matching. If you find something that seems related to the requirement,
include it even if the wording is different.
"""
    
    result = call_llm_with_backoff(prompt, MODEL_PRO, 0.1, 4000, "AISuggestRetry", tracer)
    parsed = safe_extract_json(result.text, "object")
    
    if parsed and parsed.get("value"):
        tracer.record(
            "AISuggest", "RETRY_SUCCESS",
            f"Found {req['name']} using term: {parsed.get('found_with_term', 'alternative matching')}"
        )
    else:
        tracer.record("AISuggest", "RETRY_FAILED", f"Could not find {req['name']} after retry")
    
    return parsed


def _generate_alternative_terms(requirement_name: str) -> list[str]:
    """
    Generate alternative search terms for a requirement.

    Uses governance-discovered terminology when available,
    plus common banking/lending terminology synonyms to improve matching.
    """

    # Start with governance-discovered terminology if available
    gov_ctx = st.session_state.get("governance_context")
    gov_terms = {}
    if gov_ctx and gov_ctx.get("terminology_map"):
        for term, synonyms in gov_ctx["terminology_map"].items():
            if isinstance(synonyms, list):
                gov_terms[term.lower()] = synonyms

    # Generic banking/lending synonyms (no domain-specific terms)
    # Domain-specific terms are injected via governance discovery
    term_map = {
        # Financial metrics
        "ltv": ["loan to value", "leverage", "ltv ratio", "loan-to-value"],
        "dscr": ["debt service coverage", "debt service coverage ratio", "coverage ratio", "dsc"],
        "icr": ["interest coverage", "interest coverage ratio", "ebitda to interest"],
        "debt service": ["principal and interest", "p&i", "loan payments", "debt payments"],

        # Transaction-related
        "covenant": ["financial covenant", "undertaking", "agreement", "maintenance covenant"],
        "security": ["collateral", "pledge", "mortgage", "charge", "guarantee"],
        "facility": ["loan", "credit facility", "financing", "advance"],
        "purpose": ["use of proceeds", "rationale", "reason", "objective"],
        "tenor": ["term", "maturity", "duration", "loan term"],
        "pricing": ["margin", "spread", "interest rate", "rate", "cost"],
        "valuation": ["value", "appraisal", "market value", "asset value"],

        # Party-related
        "borrower": ["obligor", "debtor", "company", "entity", "spv"],
        "guarantor": ["sponsor", "parent company", "guarantee provider"],
        "sponsor": ["backer", "equity provider", "investor", "fund manager"],
    }

    # Merge governance terms into term_map (governance REPLACES defaults)
    for key, synonyms in gov_terms.items():
        # Governance-discovered synonyms fully replace hardcoded defaults
        # This ensures document-driven terminology wins over generic fallbacks
        term_map[key] = synonyms
    
    alternatives = []
    name_lower = requirement_name.lower()
    
    # Check if any mapped terms appear in the requirement name
    for key, synonyms in term_map.items():
        if key in name_lower:
            alternatives.extend(synonyms)
    
    # Add requirement name itself with variations
    alternatives.insert(0, requirement_name)
    
    # Add name with different separators
    alternatives.append(requirement_name.replace("_", " "))
    alternatives.append(requirement_name.replace("-", " "))
    alternatives.append(requirement_name.replace(" ", "_"))
    
    # Remove duplicates while preserving order
    seen = set()
    unique_alternatives = []
    for term in alternatives:
        term_lower = term.lower()
        if term_lower not in seen:
            seen.add(term_lower)
            unique_alternatives.append(term)
    
    # Return max 10 alternatives
    return unique_alternatives[:10]


def _extract_from_uploaded_file(uploaded_file, req: dict, tracer) -> dict | None:
    """
    Extract a requirement value from an uploaded file.

    1. Save uploaded bytes to temp file
    2. Parse with universal_loader
    3. LLM extracts the specific requirement value
    4. Store full file text in supplement_texts for later phases
    """
    import tempfile

    tracer.record("FileAnalysis", "START", f"Analyzing {uploaded_file.name} for '{req['name']}'")

    # Save to temp file for the loader
    suffix = Path(uploaded_file.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    try:
        # Extract text
        file_text = universal_loader(tmp_path)

        if not file_text or file_text.startswith("[ERROR]") or len(file_text.strip()) < 20:
            tracer.record("FileAnalysis", "ERROR", f"Could not extract text from {uploaded_file.name}")
            return None

        tracer.record(
            "FileAnalysis", "EXTRACTED",
            f"{uploaded_file.name}: {len(file_text)} chars extracted"
        )

        # Store full text as supplementary document for later phases
        st.session_state.supplement_texts[uploaded_file.name] = file_text

        # LLM extraction — find the specific requirement in the file
        prompt = f"""Extract a specific value from this document.

## REQUIREMENT TO FIND
Name: {req['name']}
Description: {req.get('description', '')}
Why needed: {req.get('why_required', '')}

## DOCUMENT: {uploaded_file.name}
{file_text[:8000]}

## INSTRUCTIONS
Search the document above for information matching this requirement.
This could be a financial figure, a name, a date, a description, a ratio, a table, etc.

If the document contains tabular data relevant to this requirement, you may include
a formatted table as the value.

Respond with ONLY a JSON object:
```json
{{
  "value": "<the extracted value, or empty string if truly not found>",
  "source_quote": "<exact quote from the document that contains this value>",
  "confidence": "HIGH|MEDIUM|LOW"
}}
```

Return ONLY the JSON object.
"""
        result = call_llm(prompt, MODEL_PRO, 0.0, 1500, "FileAnalysis", tracer)
        parsed = safe_extract_json(result.text, "object")

        if parsed and parsed.get("value"):
            tracer.record(
                "FileAnalysis", "COMPLETE",
                f"Found '{req['name']}' in {uploaded_file.name} [{parsed.get('confidence', '?')}]"
            )
        else:
            tracer.record(
                "FileAnalysis", "NOT_FOUND",
                f"'{req['name']}' not found in {uploaded_file.name}"
            )

        return parsed

    except Exception as e:
        tracer.record("FileAnalysis", "ERROR", str(e))
        return None
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _bulk_analyze_files(files, reqs: list[dict], tracer):
    """
    Analyze multiple uploaded files against all unfilled requirements.

    For each file:
    1. Extract text
    2. Store as supplementary document
    3. Ask LLM to match file contents against all unfilled requirements
    4. Auto-fill any matches
    """
    import tempfile

    unfilled = [r for r in reqs if r.get("status") != "filled"]
    if not unfilled:
        return

    unfilled_desc = json.dumps(
        [{"id": r["id"], "name": r["name"], "description": r.get("description", "")} for r in unfilled],
        indent=2,
    )

    for uploaded in files:
        tracer.record("BulkAnalysis", "START", f"Analyzing {uploaded.name}")

        suffix = Path(uploaded.name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded.getbuffer())
            tmp_path = tmp.name

        try:
            file_text = universal_loader(tmp_path)
            if not file_text or file_text.startswith("[ERROR]") or len(file_text.strip()) < 20:
                tracer.record("BulkAnalysis", "SKIP", f"{uploaded.name}: could not extract text")
                continue

            # Store as supplementary document
            st.session_state.supplement_texts[uploaded.name] = file_text

            tracer.record("BulkAnalysis", "EXTRACTED", f"{uploaded.name}: {len(file_text)} chars")

            # LLM: match file contents against all unfilled requirements
            prompt = f"""Analyze this document and extract values for as many requirements as possible.

## DOCUMENT: {uploaded.name}
{file_text[:10000]}

## UNFILLED REQUIREMENTS
{unfilled_desc}

## INSTRUCTIONS
For each requirement where you can find a matching value in the document, include it in the output.
Only include requirements where you found a clear match — skip any you're uncertain about.

Respond with ONLY a JSON array:
```json
[
  {{
    "id": <requirement id>,
    "value": "<extracted value>",
    "source_quote": "<exact quote from document>",
    "confidence": "HIGH|MEDIUM|LOW"
  }}
]
```

Return ONLY the JSON array. If nothing matches, return an empty array [].
"""
            result = call_llm(prompt, MODEL_PRO, 0.0, 3000, "BulkAnalysis", tracer)
            fills = safe_extract_json(result.text, "array")

            fill_count = 0
            if fills:
                for fill in fills:
                    try:
                        fill_id = int(fill.get("id", -1))
                    except (ValueError, TypeError):
                        continue
                    value = fill.get("value", "").strip()
                    if not value or value.upper() in ("NOT FOUND", "N/A", "NOT AVAILABLE", ""):
                        continue
                    for req in reqs:
                        if int(req.get("id", -1)) == fill_id and req.get("status") != "filled":
                            req["value"] = value
                            req["status"] = "filled"
                            req["source"] = f"file: {uploaded.name}"
                            req["evidence"] = fill.get("source_quote", "")
                            fill_count += 1
                            break

            tracer.record(
                "BulkAnalysis", "COMPLETE",
                f"{uploaded.name}: filled {fill_count} requirements"
            )

        except Exception as e:
            tracer.record("BulkAnalysis", "ERROR", f"{uploaded.name}: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

# =============================================================================
# Phase: COMPLIANCE
# =============================================================================

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
                result_text, checks = run_agentic_compliance(
                    requirements=st.session_state.process_requirements,
                    teaser_text=st.session_state.teaser_text,
                    extracted_data=st.session_state.extracted_data,
                    search_guidelines_fn=tool_search_guidelines,
                    tracer=get_tracer(),
                    governance_context=st.session_state.get("governance_context"),
                )
                st.session_state.compliance_result = result_text
                st.session_state.compliance_checks = checks

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
                    _advance_phase("DRAFTING")
                    st.rerun()
        else:
            if st.button("➡️ Continue to Drafting", type="primary", use_container_width=True):
                _advance_phase("DRAFTING")
                st.rerun()


# =============================================================================
# Phase: DRAFTING — Adaptive Sections
# =============================================================================

def _build_drafting_context(structure: list, drafts: dict) -> dict:
    """Build the full context for section drafting, including previously drafted sections."""
    # Collect already-drafted sections so the Writer sees what came before
    previously_drafted = ""
    for section in structure:
        name = section["name"]
        if name in drafts:
            previously_drafted += f"\n\n# {name}\n\n{drafts[name][:2000]}"

    context = {
        "teaser_text": st.session_state.teaser_text,
        "example_text": st.session_state.example_text,
        "extracted_data": st.session_state.extracted_data,
        "compliance_result": st.session_state.compliance_result,
        "requirements": st.session_state.process_requirements,
        "supplement_texts": st.session_state.supplement_texts,
        "previously_drafted": previously_drafted,
    }
    return context


def render_phase_drafting():
    st.header("✍️ Phase 4: Credit Pack Drafting")

    structure = st.session_state.proposed_structure
    drafts = st.session_state.section_drafts

    if not structure:
        # Show error from previous failed attempt
        if st.session_state.get("_structure_gen_failed"):
            st.error(
                "⚠️ **Section structure generation failed.** "
                "The LLM response could not be parsed. "
                "You can try again or add sections manually below."
            )

        if st.button("📋 Generate Section Structure", type="primary", use_container_width=True):
            with st.spinner("Generating deal-specific section structure..."):
                sections = generate_section_structure(
                    example_text=st.session_state.example_text,
                    assessment_approach=st.session_state.process_path,
                    origination_method=st.session_state.origination_method,
                    analysis_text=st.session_state.extracted_data,
                    tracer=get_tracer(),
                    search_procedure_fn=tool_search_procedure,
                    governance_context=st.session_state.get("governance_context"),
                )

                if sections:
                    st.session_state.proposed_structure = sections
                    st.session_state["_structure_gen_failed"] = False
                    st.rerun()
                else:
                    st.session_state["_structure_gen_failed"] = True
                    st.rerun()

        # Manual section builder (always available when no structure)
        st.divider()
        st.subheader("Or define sections manually:")
        sec_name = st.text_input("Section name:", key="new_sec_name_init")
        sec_desc = st.text_input("Description:", key="new_sec_desc_init")
        sec_detail = st.selectbox("Detail level:", ["Standard", "Detailed", "Brief"], key="new_sec_detail_init")
        if sec_name and st.button("➕ Add Section", key="add_sec_init"):
            st.session_state.proposed_structure.append(
                {"name": sec_name, "description": sec_desc, "detail_level": sec_detail}
            )
            st.rerun()

        return  # Don't render the drafting UI until we have sections

    if structure:
        st.caption(
            f"Structure: {len(structure)} sections "
            f"(adapted for {st.session_state.origination_method or 'this deal'})"
        )
        st.progress(len(drafts) / max(len(structure), 1))

        # Draft All button
        undrafted = [s for s in structure if s["name"] not in drafts]
        if undrafted:
            if st.button(
                f"✍️ Draft All Remaining ({len(undrafted)} sections)",
                type="primary", use_container_width=True
            ):
                for idx, section in enumerate(structure):
                    name = section["name"]
                    if name in drafts:
                        continue
                    with st.spinner(f"Drafting {idx+1}/{len(structure)}: {name}..."):
                        context = _build_drafting_context(structure, drafts)
                        draft_result = draft_section(
                            section, context,
                            agent_bus=st.session_state.agent_bus,
                            tracer=get_tracer(),
                            governance_context=st.session_state.get("governance_context"),
                        )
                        drafts[name] = draft_result.content
                st.rerun()

            st.divider()

        for i, section in enumerate(structure):
            name = section["name"]
            is_drafted = name in drafts

            with st.expander(f"{'✅' if is_drafted else '⬜'} {name}", expanded=not is_drafted):
                st.caption(section.get("description", ""))
                st.caption(f"Detail level: {section.get('detail_level', 'Standard')}")

                if is_drafted:
                    st.markdown(drafts[name])
                    edited = st.text_area("Edit:", value=drafts[name], key=f"edit_section_{i}", height=300)
                    if edited != drafts[name] and st.button("💾 Save", key=f"save_section_{i}"):
                        old = drafts[name]
                        drafts[name] = edited
                        st.session_state.change_log.record_change(
                            "section_edit", name, old[:100], edited[:100], "DRAFTING"
                        )
                        st.rerun()
                else:
                    if st.button(f"✍️ Draft {name}", key=f"draft_{i}", use_container_width=True):
                        with st.spinner(f"Writer drafting {name}..."):
                            context = _build_drafting_context(structure, drafts)
                            draft_result = draft_section(
                                section, context,
                                agent_bus=st.session_state.agent_bus,
                                tracer=get_tracer(),
                                governance_context=st.session_state.get("governance_context"),
                            )
                            drafts[name] = draft_result.content
                            st.rerun()

    # Add custom section
    with st.expander("➕ Add Custom Section"):
        sec_name = st.text_input("Section name:", key="new_sec_name")
        sec_desc = st.text_input("Description:", key="new_sec_desc")
        if sec_name and st.button("Add Section"):
            structure.append({"name": sec_name, "description": sec_desc, "detail_level": "Standard"})
            st.rerun()

    st.divider()
    if structure and len(drafts) >= len(structure):
        # AG-M8: Run Orchestrator routing check before allowing completion
        if "drafting_routing_done" not in st.session_state:
            if st.button("Run Final Review", type="secondary", use_container_width=True):
                with st.spinner("Running orchestrator final review..."):
                    tracer = get_tracer()
                    insights = run_orchestrator_decision(
                        "DRAFTING",
                        st.session_state.extracted_data or "",
                        st.session_state.compliance_result or "",
                        st.session_state.process_path or "",
                        tracer=tracer,
                        governance_context=st.session_state.get("governance_context"),
                    )
                    st.session_state["drafting_routing"] = insights
                    st.session_state["drafting_routing_done"] = True
                    st.rerun()
        else:
            routing = st.session_state.get("drafting_routing")
            if routing and routing.message_to_human:
                st.info(f"Orchestrator: {routing.message_to_human}")
            if routing and routing.flags:
                for flag in routing.flags:
                    st.warning(f"{flag.severity.value}: {flag.description}")
            can_export = True
            if routing and not routing.can_proceed:
                st.warning("Orchestrator recommends review before export.")
                can_export = st.checkbox("I have reviewed the drafts and wish to proceed", key="drafting_override")
            if can_export:
                if st.button("➡️ Continue to Export", type="primary", use_container_width=True):
                    _advance_phase("COMPLETE")
                    st.rerun()


# =============================================================================
# Phase: COMPLETE
# =============================================================================

def render_phase_complete():
    st.header("🎉 Phase 5: Complete")

    st.subheader("📊 Session Summary")
    render_agent_dashboard(get_tracer())
    st.divider()

    # ALWAYS reassemble from current drafts (fixes stale cache after edits)
    all_content = []
    for section in st.session_state.proposed_structure:
        name = section["name"]
        content = st.session_state.section_drafts.get(name, "")
        if content:
            # Use # for section title (Writer uses ## and below for sub-headings)
            all_content.append(f"# {name}\n\n{content}")
    st.session_state.final_document = "\n\n---\n\n".join(all_content)

    with st.expander("📄 Full Credit Pack Preview", expanded=True):
        st.markdown(st.session_state.final_document[:5000])
        if len(st.session_state.final_document) > 5000:
            st.caption(f"... ({len(st.session_state.final_document):,} total chars)")

    # Pre-generate DOCX and store path in session state (avoids nested button problem)
    if st.session_state.get("_docx_path"):
        docx_path = st.session_state["_docx_path"]
        docx_name = Path(docx_path).name
        st.success(f"✅ DOCX ready: {docx_name}")
        with open(docx_path, "rb") as f:
            st.download_button(
                "⬇️ Download DOCX", f, docx_name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        if st.button("🔄 Regenerate DOCX"):
            st.session_state["_docx_path"] = ""
            st.rerun()
    else:
        if st.button("📥 Generate DOCX", type="primary", use_container_width=True):
            with st.spinner("Generating professional DOCX..."):
                metadata = {
                    "deal_name": st.session_state.teaser_file,
                    "process_path": st.session_state.process_path,
                    "origination_method": st.session_state.origination_method,
                }
                filename = f"credit_pack_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
                path = generate_docx(st.session_state.final_document, filename, metadata)
                if path:
                    st.session_state["_docx_path"] = path
                    st.rerun()
                else:
                    st.error("DOCX generation failed — check python-docx installation")

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        # Audit trail — same pattern: store path, then show download
        if st.session_state.get("_audit_path"):
            audit_path = st.session_state["_audit_path"]
            with open(audit_path, "r") as f:
                st.download_button(
                    "⬇️ Download Audit Trail", f, Path(audit_path).name,
                    use_container_width=True,
                )
        else:
            if st.button("📋 Generate Audit Trail", use_container_width=True):
                with st.spinner("Generating audit trail..."):
                    path = generate_audit_trail(dict(st.session_state), get_tracer())
                    if path:
                        st.session_state["_audit_path"] = path
                        st.rerun()

    with col2:
        change_log = st.session_state.change_log
        if change_log and change_log.has_changes():
            with st.expander(f"📝 Change Log ({change_log.get_change_count()})"):
                st.markdown(change_log.generate_audit_trail())


# =============================================================================
# Main
# =============================================================================

def main():
    render_sidebar(get_tracer(), handle_orchestrator_chat)

    # AG-6: Persistent governance warning banner on every phase except SETUP
    phase = st.session_state.workflow_phase
    if phase != "SETUP":
        gov_ctx = st.session_state.get("governance_context")
        if gov_ctx:
            status = gov_ctx.get("discovery_status", "")
            if status == "partial":
                st.warning(
                    "⚠️ Governance discovery partially completed. "
                    "Some features are using default settings instead of document-derived parameters."
                )
            elif status == "failed":
                st.error(
                    "🚫 Governance documents not analyzed. "
                    "System using default settings. Consider re-running setup to analyze Procedure & Guidelines."
                )
        elif st.session_state.get("governance_discovery_done"):
            # Discovery ran but returned None
            st.error(
                "🚫 Governance discovery failed. "
                "System using default settings. Consider re-running setup."
            )

    if phase == "SETUP":
        render_phase_setup()
    elif phase == "ANALYSIS":
        render_phase_analysis()
    elif phase == "PROCESS_GAPS":
        render_phase_process_gaps()
    elif phase == "COMPLIANCE":
        render_phase_compliance()
    elif phase == "DRAFTING":
        render_phase_drafting()
    elif phase == "COMPLETE":
        render_phase_complete()
    else:
        render_phase_setup()


if __name__ == "__main__":
    main()
