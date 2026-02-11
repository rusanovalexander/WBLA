"""
Session State Management - Centralized state initialization and utilities

Extracted from app.py to provide single source of truth for session state structure.
"""

import streamlit as st
from typing import Any

# Import required for agent bus initialization
from agents import (
    AgentCommunicationBus,
    create_process_analyst_responder,
    create_compliance_advisor_responder,
)
from tools.change_tracker import ChangeLog
from tools.phase_manager import PhaseManager
from core.tracing import TraceStore, set_tracer
from core.llm_client import call_llm
from config.settings import MODEL_PRO
from tools.rag_search import tool_search_guidelines


def init_state():
    """
    Initialize all Streamlit session state variables with defaults.
    
    This function is idempotent - it only sets values that don't already exist.
    Must be called at the start of the Streamlit app.
    """
    defaults = {
        # Chat and messages
        "messages": [],
        "orch_chat_history": [],
        "orch_chat_active": False,
        
        # Workflow phase
        "workflow_phase": "SETUP",
        
        # RAG connection
        "rag_ok": None,
        
        # Document uploads
        "teaser_text": "",
        "teaser_file": "",
        "example_text": "",
        "example_file": "",
        
        # Analysis phase
        "extracted_data": "",
        "process_path": "",
        "origination_method": "",
        "assessment_reasoning": "",
        "origination_reasoning": "",
        "decision_found": False,
        "decision_confidence": "NONE",
        "procedure_sources": {},
        
        # Process decision
        "process_decision": None,
        "process_decision_locked": False,
        
        # Orchestrator outputs
        "orchestrator_insights": "",
        "orchestrator_flags": [],
        "orchestrator_recommendations": [],
        "orchestrator_routing": {},  # Routing decisions
        
        # Requirements and supplements
        "process_requirements": [],
        "supplement_texts": {},
        
        # Compliance phase
        "compliance_result": "",
        "compliance_checks": [],
        "guideline_sources": {},
        
        # Drafting phase
        "proposed_structure": [],
        "section_drafts": {},
        "final_document": "",
        
        # System components
        "agent_bus": None,
        "change_log": None,
        "phase_manager": None,
        "tracer": None,
        
        # Governance discovery
        "governance_context": None,
        "governance_discovery_done": False,
    }
    
    # Set defaults for any missing keys
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    
    # Initialize agent bus with responders
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
    
    # Initialize change log
    if st.session_state.change_log is None:
        st.session_state.change_log = ChangeLog()
    
    # Initialize phase manager
    if st.session_state.phase_manager is None:
        st.session_state.phase_manager = PhaseManager()
    
    # Initialize tracer
    if st.session_state.tracer is None:
        st.session_state.tracer = TraceStore()
    
    # AG-H2: Bind session tracer to contextvars so core modules use it
    set_tracer(st.session_state.tracer)


def get_tracer() -> TraceStore:
    """Get the current session's tracer instance."""
    return st.session_state.tracer


def advance_phase(next_phase: str):
    """
    Advance workflow phase using PhaseManager with state snapshot.
    
    Args:
        next_phase: Target phase name (e.g., "ANALYSIS", "COMPLIANCE")
    
    Blocks transition if PhaseManager validation fails.
    """
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
                "system",
                "Phase Transition Blocked",
                st.session_state.get("workflow_phase", "?"),
                next_phase,
                f"PhaseManager validation failed: {e}",
            )
        st.error(f"Phase transition blocked: {e}")
        return  # Do NOT advance
