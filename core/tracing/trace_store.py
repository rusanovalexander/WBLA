"""
Observability & Tracing for Credit Pack PoC v3.2.

Provides structured tracing of all agent activities, LLM calls,
tool invocations, and inter-agent communication.

Supports optional Langfuse integration for production observability.
Falls back to in-memory trace log for demo/local use.
"""

from __future__ import annotations

import contextvars
import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generator

logger = logging.getLogger(__name__)

from models.schemas import AgentTraceEntry


# =============================================================================
# Cost Estimation (approximate, for demo visibility)
# =============================================================================

# Approximate per-token costs (USD) — update as pricing changes.
# Keys MUST match the model names used in config/settings.py (MODEL_PRO / MODEL_FLASH).
MODEL_COSTS = {
    # Current stable model names (as of 2026-Q1)
    "gemini-2.5-pro": {"input": 1.25 / 1_000_000, "output": 10.0 / 1_000_000},
    "gemini-2.5-flash": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    # Legacy preview model names (kept for backward compatibility)
    "gemini-2.5-pro-preview-05-06": {"input": 1.25 / 1_000_000, "output": 10.0 / 1_000_000},
    "gemini-2.5-flash-preview-04-17": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    # Fallback for unknown models
    "default": {"input": 1.0 / 1_000_000, "output": 5.0 / 1_000_000},
}


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate USD cost for an LLM call."""
    costs = MODEL_COSTS.get(model, MODEL_COSTS["default"])
    return (tokens_in * costs["input"]) + (tokens_out * costs["output"])


def estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars ≈ 1 token for English)."""
    return max(1, len(text) // 4)


# =============================================================================
# Trace Store
# =============================================================================

class TraceStore:
    """
    In-memory trace store for agent activities.

    Collects structured trace entries for display in the UI dashboard
    and export in the audit trail.
    """

    MAX_ENTRIES = 2000  # Rolling cap — oldest entries trimmed when exceeded

    def __init__(self):
        self.entries: list[AgentTraceEntry] = []
        self.active_agent: str | None = None
        self._lock = threading.Lock()  # Guards all mutable state for thread safety
        self._session_start = datetime.now()
        self._total_cost: float = 0.0
        self._total_tokens_in: int = 0
        self._total_tokens_out: int = 0
        self._total_calls: int = 0
        self._langfuse = None
        self._init_langfuse()

    def _init_langfuse(self):
        """Try to initialize Langfuse if credentials are available."""
        try:
            if os.getenv("LANGFUSE_PUBLIC_KEY"):
                if not os.getenv("LANGFUSE_SECRET_KEY"):
                    logger.warning(
                        "LANGFUSE_PUBLIC_KEY is set but LANGFUSE_SECRET_KEY is missing. "
                        "Langfuse observability will be disabled."
                    )
                    return
                from langfuse import Langfuse
                self._langfuse = Langfuse()
                logger.info("Langfuse observability initialized.")
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Langfuse init failed: %s", e)

    def record(
        self,
        agent: str,
        action: str,
        detail: str = "",
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        duration_ms: int = 0,
        model: str = "",
    ) -> AgentTraceEntry:
        """Record a trace entry (thread-safe)."""
        entry = AgentTraceEntry(
            agent=agent,
            action=action,
            detail=detail[:2000] if detail else "",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            model=model,
        )

        with self._lock:
            self.entries.append(entry)
            # Trim oldest entries when cap exceeded to prevent unbounded memory growth
            if len(self.entries) > self.MAX_ENTRIES:
                self.entries = self.entries[-self.MAX_ENTRIES:]

            # Update totals
            self._total_cost += cost_usd
            self._total_tokens_in += tokens_in
            self._total_tokens_out += tokens_out
            if action == "LLM_CALL":
                self._total_calls += 1

            # Track active agent
            if action in ("START", "CALLING", "LLM_CALL"):
                self.active_agent = agent
            elif action in ("COMPLETE", "ERROR"):
                self.active_agent = None

        # Forward to Langfuse outside lock (network I/O should not block other threads)
        if self._langfuse and action == "LLM_CALL":
            try:
                self._langfuse.generation(
                    name=f"{agent}.{action}",
                    model=model,
                    input=detail[:200],
                    usage={"input": tokens_in, "output": tokens_out},
                    metadata={"cost_usd": cost_usd, "duration_ms": duration_ms},
                )
            except Exception as e:
                logger.warning("Langfuse forwarding failed: %s", e)

        return entry

    @contextmanager
    def trace_llm_call(
        self, agent: str, model: str, prompt_text: str = ""
    ) -> Generator[dict[str, Any], None, None]:
        """
        Context manager for tracing an LLM call with automatic timing and cost.

        Usage:
            with tracer.trace_llm_call("ProcessAnalyst", "gemini-2.5-pro") as ctx:
                result = call_gemini(prompt)
                ctx["tokens_in"] = result.usage.prompt_tokens
                ctx["tokens_out"] = result.usage.completion_tokens
                ctx["response_text"] = result.text
        """
        ctx: dict[str, Any] = {
            "tokens_in": estimate_tokens(prompt_text),
            "tokens_out": 0,
            "response_text": "",
        }
        start = time.time()

        self.record(agent, "LLM_CALL", f"Model: {model}", model=model)

        try:
            yield ctx
        finally:
            duration_ms = int((time.time() - start) * 1000)
            tokens_out = ctx.get("tokens_out", 0) or estimate_tokens(ctx.get("response_text", ""))
            tokens_in = ctx.get("tokens_in", 0)
            cost = estimate_cost(model, tokens_in, tokens_out)

            self.record(
                agent,
                "LLM_RESPONSE",
                f"Generated {len(ctx.get('response_text', '')):,} chars in {duration_ms}ms",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                duration_ms=duration_ms,
                model=model,
            )

    # ---- Accessors ----

    @property
    def total_cost(self) -> float:
        with self._lock:
            return self._total_cost

    @property
    def total_tokens(self) -> tuple[int, int]:
        with self._lock:
            return self._total_tokens_in, self._total_tokens_out

    @property
    def total_calls(self) -> int:
        with self._lock:
            return self._total_calls

    def get_entries(self, last_n: int = 0) -> list[AgentTraceEntry]:
        """Get a snapshot of trace entries (thread-safe), optionally last N."""
        with self._lock:
            snapshot = list(self.entries)
        if last_n > 0:
            return snapshot[-last_n:]
        return snapshot

    def get_agent_summary(self) -> dict[str, dict[str, Any]]:
        """Get per-agent summary statistics (thread-safe snapshot)."""
        summary: dict[str, dict[str, Any]] = {}
        for entry in self.get_entries():
            if entry.agent not in summary:
                summary[entry.agent] = {
                    "calls": 0, "tokens_in": 0, "tokens_out": 0,
                    "cost_usd": 0.0, "total_ms": 0,
                }
            s = summary[entry.agent]
            if entry.action == "LLM_RESPONSE":
                s["calls"] += 1
                s["tokens_in"] += entry.tokens_in
                s["tokens_out"] += entry.tokens_out
                s["cost_usd"] += entry.cost_usd
                s["total_ms"] += entry.duration_ms
        return summary

    def format_for_export(self) -> str:
        """Format trace for audit trail export (thread-safe snapshot)."""
        with self._lock:
            calls = self._total_calls
            tokens_in = self._total_tokens_in
            tokens_out = self._total_tokens_out
            cost = self._total_cost
        lines = [
            "=" * 70,
            "AGENT ACTIVITY TRACE",
            f"Session started: {self._session_start.isoformat()}",
            f"Total LLM calls: {calls}",
            f"Total tokens: {tokens_in:,} in / {tokens_out:,} out",
            f"Estimated cost: ${cost:.4f}",
            "=" * 70,
            "",
        ]
        for entry in self.get_entries():
            cost_str = f" [${entry.cost_usd:.4f}]" if entry.cost_usd > 0 else ""
            time_str = f" [{entry.duration_ms}ms]" if entry.duration_ms > 0 else ""
            lines.append(
                f"[{entry.time}] {entry.agent:20s} | {entry.action:15s}{cost_str}{time_str}"
            )
            if entry.detail:
                lines.append(f"{'':23s} └─ {entry.detail[:120]}")
        return "\n".join(lines)

    def clear(self):
        """Clear all trace entries (thread-safe)."""
        with self._lock:
            self.entries.clear()
            self._total_cost = 0.0
            self._total_tokens_in = 0
            self._total_tokens_out = 0
            self._total_calls = 0
            self.active_agent = None


# =============================================================================
# Session-scoped tracer (contextvars prevents cross-session bleed)
# =============================================================================

_tracer_var: contextvars.ContextVar[TraceStore | None] = contextvars.ContextVar("tracer", default=None)


def get_tracer() -> TraceStore:
    """Get the context-local tracer instance (session-safe)."""
    tracer = _tracer_var.get()
    if tracer is None:
        tracer = TraceStore()
        _tracer_var.set(tracer)
    return tracer


def set_tracer(tracer: TraceStore) -> None:
    """Set the context-local tracer (called from Streamlit session init)."""
    _tracer_var.set(tracer)
