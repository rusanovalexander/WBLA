"""
Sidebar component for Credit Pack PoC v3.2.

Displays workflow navigation, system status, orchestrator insights,
agent dashboard, change tracking, and orchestrator chat.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st
from core.tracing import TraceStore
from ui.components.agent_dashboard import render_agent_dashboard_compact


def render_sidebar(tracer: TraceStore, handle_chat_fn):
    """Render the complete sidebar."""
    with st.sidebar:
        st.title("🏦 CPS")
        st.caption("Multi-Agent System with Native Tool Use")

        st.divider()

        # ---- Process Decision Lock ----
        _render_process_lock()

        st.divider()

        # ---- System Status ----
        _render_system_status()

        st.divider()

        # ---- Workflow Navigation ----
        _render_workflow_nav()

        st.divider()

        # ---- Agent Dashboard (compact) ----
        st.subheader("📊 Agent Activity")
        render_agent_dashboard_compact(tracer)

        st.divider()

        # ---- Orchestrator Insights ----
        _render_orchestrator_insights()

        st.divider()

        # ---- Orchestrator Chat ----
        _render_orchestrator_chat(handle_chat_fn)

        st.divider()

        # ---- Change Tracking ----
        _render_change_tracking()

        st.divider()

        # ---- Documents ----
        _render_documents()

        st.divider()

        # ---- Agent Communication Log ----
        _render_agent_comm_log()

        st.divider()

        # ---- Reset ----
        # AG-L1: Require confirmation before resetting
        confirm_reset = st.checkbox("I understand this will delete all progress", key="confirm_reset")
        if st.button("Reset All", use_container_width=True, disabled=not confirm_reset):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


def _render_process_lock():
    decision = st.session_state.get("process_decision")
    if decision and decision.get("locked"):
        st.success("🔒 **Process Path Locked**")
        st.caption(f"✓ {decision['assessment_approach']}")
        st.caption(f"✓ {decision['origination_method']}")


def _render_system_status():
    st.subheader("System Status")
    col1, col2 = st.columns(2)
    with col1:
        rag = st.session_state.get("rag_ok")
        if rag:
            st.success("RAG ✓")
        elif rag is False:
            st.error("RAG ✗")
        else:
            st.warning("RAG ?")
    with col2:
        st.success("Agents ✓")


def _render_workflow_nav():
    st.subheader("Workflow")
    phases = [
        ("SETUP", "Setup"),
        ("ANALYSIS", "Analysis"),
        ("PROCESS_GAPS", "Requirements"),
        ("COMPLIANCE", "Compliance"),
        ("DRAFTING", "Drafting"),
        ("COMPLETE", "Complete"),
    ]
    current = st.session_state.get("workflow_phase", "SETUP")
    current_idx = next((i for i, (p, _) in enumerate(phases) if p == current), 0)

    for i, (key, name) in enumerate(phases):
        col1, col2 = st.columns([3, 1])
        with col1:
            if i < current_idx:
                st.write(f"✅ {name}")
            elif i == current_idx:
                st.write(f"▶️ **{name}**")
            else:
                st.write(f"⬜ {name}")
        with col2:
            if 0 < i < current_idx:
                if st.button("↩️", key=f"back_to_{key}", help=f"Go back to {name}"):
                    phase_mgr = st.session_state.get("phase_manager")
                    if phase_mgr:
                        phase_mgr.go_back_to(key)
                    st.session_state["workflow_phase"] = key
                    st.rerun()

    # Progress bars
    if current == "PROCESS_GAPS":
        reqs = st.session_state.get("process_requirements", [])
        if reqs:
            filled = sum(1 for r in reqs if r.get("status") == "filled")
            st.progress(filled / len(reqs))
            st.caption(f"{filled}/{len(reqs)} filled")

    if current == "DRAFTING":
        structure = st.session_state.get("proposed_structure", [])
        drafts = st.session_state.get("section_drafts", {})
        if structure:
            st.progress(len(drafts) / len(structure) if structure else 0)
            st.caption(f"{len(drafts)}/{len(structure)} sections")


def _render_orchestrator_insights():
    insights = st.session_state.get("orchestrator_insights", "")
    flags = st.session_state.get("orchestrator_flags", [])

    if insights:
        st.subheader("🎯 Orchestrator")
        with st.expander("Full Insights", expanded=False):
            st.markdown(insights)

        for flag in flags[:3]:
            severity = flag.get("severity", "MEDIUM")
            text = flag.get("text", "")[:60]
            if severity == "HIGH":
                st.error(f"⚠️ {text}")
            elif severity == "MEDIUM":
                st.warning(f"⚠️ {text}")
            else:
                st.info(f"ℹ️ {text}")


def _render_orchestrator_chat(handle_chat_fn):
    st.subheader("💬 Ask Orchestrator")

    if st.button("Start Chat", use_container_width=True, key="toggle_chat"):
        st.session_state["orch_chat_active"] = not st.session_state.get("orch_chat_active", False)

    if st.session_state.get("orch_chat_active"):
        question = st.text_input("Your question:", key="orch_chat_input")

        if question and st.button("Ask", use_container_width=True, key="send_chat"):
            with st.spinner("Orchestrator thinking..."):
                response = handle_chat_fn(question)
                history = st.session_state.get("orch_chat_history", [])
                history.append({
                    "q": question, "a": response,
                    "timestamp": datetime.now().isoformat(),
                })
                st.session_state["orch_chat_history"] = history
                st.rerun()

        history = st.session_state.get("orch_chat_history", [])
        if history:
            with st.expander(f"Chat History ({len(history)})"):
                for entry in reversed(history[-5:]):
                    st.markdown(f"**Q:** {entry['q']}")
                    st.markdown(f"**A:** {entry['a'][:300]}...")
                    st.divider()


def _render_change_tracking():
    change_log = st.session_state.get("change_log")
    if change_log and hasattr(change_log, "has_changes") and change_log.has_changes():
        st.subheader("📝 Changes")
        st.metric("Human Edits", change_log.get_change_count())
        with st.expander("View Changes"):
            for c in change_log.get_all_changes()[-5:]:
                st.caption(f"[{c['type']}] {c['field']}")


def _render_documents():
    st.subheader("Documents")
    teaser = st.session_state.get("teaser_file")
    example = st.session_state.get("example_file")
    supplements = st.session_state.get("supplement_texts", {})

    if teaser:
        st.write(f"📄 {teaser}")
    if example:
        st.write(f"📄 {example}")
    for f in list(supplements.keys())[:3]:
        st.write(f"📎 {f}")


def _render_agent_comm_log():
    agent_bus = st.session_state.get("agent_bus")
    if agent_bus and hasattr(agent_bus, "message_count") and agent_bus.message_count > 0:
        with st.expander(f"💬 Agent Communication ({agent_bus.message_count})"):
            for msg in agent_bus.message_log[-5:]:
                st.caption(f"`{msg.timestamp}` {msg.from_agent}→{msg.to_agent}")
                st.caption(f"  _{msg.query[:40]}..._")
