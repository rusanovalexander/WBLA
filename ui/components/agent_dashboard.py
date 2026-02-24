"""
Agent Activity Dashboard for Credit Pack PoC v3.2.

Live visualization of agent activities, costs, and communication.
This is the key "demo-sexy" component — shows the system thinking.
"""

from __future__ import annotations

import streamlit as st
from core.tracing import TraceStore


def render_agent_dashboard(tracer: TraceStore):
    """Render the live agent activity dashboard."""

    # ---- Header Metrics ----
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("🤖 LLM Calls", tracer.total_calls)
    with col2:
        tokens_in, tokens_out = tracer.total_tokens
        st.metric("📊 Tokens", f"{(tokens_in + tokens_out):,}")
    with col3:
        st.metric("💰 Est. Cost", f"${tracer.total_cost:.3f}")
    with col4:
        active = tracer.active_agent or "—"
        st.metric("⚡ Active", active)

    # ---- Per-Agent Breakdown ----
    summary = tracer.get_agent_summary()
    if summary:
        st.markdown("##### Agent Performance")

        agent_colors = {
            "ProcessAnalyst": "🔵",
            "ComplianceAdvisor": "🟣",
            "Writer": "🟢",
            "Orchestrator": "🟠",
            "FieldDiscovery": "🔷",
            "OrchestratorChat": "💬",
        }

        for agent, stats in summary.items():
            emoji = agent_colors.get(agent, "⬜")
            cost = stats["cost_usd"]
            calls = stats["calls"]
            avg_ms = stats["total_ms"] // max(calls, 1)

            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            with col1:
                st.caption(f"{emoji} **{agent}**")
            with col2:
                st.caption(f"{calls} calls")
            with col3:
                st.caption(f"~{avg_ms}ms avg")
            with col4:
                st.caption(f"${cost:.3f}")

    # ---- Key Findings (what agents CONCLUDED, not just what they did) ----
    finding_actions = {"COMPLETE", "FOUND", "BATCH_COMPLETE", "DECISION_COMPLETE", "RETRY_SUCCESS"}
    findings = [
        e for e in tracer.get_entries(last_n=50)
        if e.action in finding_actions and len(e.detail) > 15
    ]
    if findings:
        st.markdown("##### Key Findings")
        for entry in findings[-6:]:  # Last 6 key findings
            icon = _action_icon(entry.action)
            detail = entry.detail[:120] + "..." if len(entry.detail) > 120 else entry.detail
            st.success(f"{icon} **{entry.agent}**: {detail}")

    # ---- Live Activity Feed ----
    st.markdown("##### Activity Feed")
    entries = tracer.get_entries(last_n=12)

    for entry in reversed(entries):
        icon = _action_icon(entry.action)
        cost_badge = f" `${entry.cost_usd:.4f}`" if entry.cost_usd > 0 else ""
        time_badge = f" `{entry.duration_ms}ms`" if entry.duration_ms > 0 else ""

        detail_preview = entry.detail[:80] + "..." if len(entry.detail) > 80 else entry.detail
        st.caption(
            f"`{entry.time}` {icon} **{entry.agent}** → {entry.action}"
            f"{cost_badge}{time_badge}"
        )
        if detail_preview:
            st.caption(f"{'':4s}└─ {detail_preview}")


def render_agent_dashboard_compact(tracer: TraceStore):
    """Compact version for sidebar."""
    tokens_in, tokens_out = tracer.total_tokens
    st.caption(
        f"📊 {tracer.total_calls} calls · "
        f"{(tokens_in + tokens_out):,} tokens · "
        f"${tracer.total_cost:.3f}"
    )

    if tracer.active_agent:
        st.info(f"⚡ **{tracer.active_agent}** working...")

    entries = tracer.get_entries(last_n=5)
    for entry in reversed(entries):
        icon = _action_icon(entry.action)
        st.caption(f"`{entry.time}` {icon} {entry.agent}: {entry.action}")


def _action_icon(action: str) -> str:
    """Get icon for trace action type."""
    icons = {
        "START": "▶️",
        "LLM_CALL": "🧠",
        "LLM_RESPONSE": "✅",
        "RAG_SEARCH": "🔍",
        "TOOL_CALL": "🔧",
        "TOOL_RESULT": "📋",
        "TOOL_ROUND": "🔄",
        "AGENT_QUERY": "💬",
        "DECISION_POINT": "🎯",
        "DECISION_COMPLETE": "🎯",
        "COMPLETE": "✅",
        "ERROR": "❌",
        "FALLBACK": "⚠️",
        "WARNING": "⚠️",
    }
    return icons.get(action, "•")
