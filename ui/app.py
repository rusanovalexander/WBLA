"""
Credit Pack Multi-Agent PoC v3.2 — Streamlit Application (AUTONOMY FIXED)

Key changes from previous version:
- Orchestrator routing decisions gate phase transitions (not just display)
- Requirements are dynamically discovered per deal (no static 28-field schema)
- Section structure adapts to process path (lighter methods ≠ comprehensive methods)
- No silent fallbacks — all failures are visible to the user
- Process path defaults removed — agent must decide or human must choose
"""

import logging
import streamlit as st
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Setup
PROJECT_ROOT = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    PROJECT_ID, MODEL_PRO, MODEL_FLASH, VERSION,
    DATA_STORE_ID, TEASERS_FOLDER, EXAMPLES_FOLDER,
    PRODUCT_NAME, THINKING_BUDGET_NONE, THINKING_BUDGET_LIGHT,
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
    page_title=f"CP PoC v{VERSION}",
    page_icon="📋",
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
    result = call_llm(prompt, MODEL_PRO, 0.1, 2000, "OrchestratorChat", tracer, thinking_budget=THINKING_BUDGET_LIGHT)
    return result.text


# =============================================================================
# Phase: SETUP
# =============================================================================


# UI module imports
from ui.utils.session_state import init_state, get_tracer, advance_phase
from ui.components.sidebar import render_sidebar
from ui.phases import (
    render_phase_setup,
    render_phase_analysis,
    render_phase_process_gaps,
    render_phase_compliance,
    render_phase_drafting,
    render_phase_complete,
)

# Initialize session state
init_state()

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
