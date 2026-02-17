"""
Process step history for Cursor-like UX: checkpoints, re-run from step, visible thought.

Each step records: phase, label, full thinking, response, and a snapshot of persistent_context
so the user can "go back" and re-run from that point with additional instructions.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, Field


# Keys we snapshot/restore for replay (subset of persistent_context)
CONTEXT_SNAPSHOT_KEYS = [
    "uploaded_files",
    "teaser_text",
    "teaser_filename",
    "example_text",
    "example_filename",
    "analysis",
    "requirements",
    "compliance_result",
    "compliance_checks",
    "structure",
    "drafts",
    "current_section_index",
    "user_comments",
    "rag_searches_done",
    "examples_used",
]


def snapshot_context(context: dict[str, Any]) -> dict[str, Any]:
    """Deep copy the replay-relevant part of persistent_context."""
    out: dict[str, Any] = {}
    for key in CONTEXT_SNAPSHOT_KEYS:
        if key in context:
            try:
                out[key] = copy.deepcopy(context[key])
            except Exception:
                out[key] = context[key]  # fallback shallow
    return out


def restore_context(target: dict[str, Any], snapshot: dict[str, Any]) -> None:
    """Overwrite target's replay-relevant keys from snapshot (in-place)."""
    for key in CONTEXT_SNAPSHOT_KEYS:
        if key in snapshot:
            try:
                target[key] = copy.deepcopy(snapshot[key])
            except Exception:
                target[key] = snapshot[key]


class ProcessStepRecord(BaseModel):
    """Single step in the process timeline (Cursor-style: visible thought, re-runnable)."""

    step_index: int = 0
    phase: str = ""  # analyze_deal | discover_requirements | check_compliance | generate_structure | draft_section | enhance_analysis
    label: str = ""  # e.g. "Deal analysis", "Compliance check", "Draft: Executive Summary"
    thinking: list[str] = Field(default_factory=list)
    response: str = ""
    response_preview: str = ""  # first ~200 chars for timeline list
    context_after: dict[str, Any] = Field(default_factory=dict)  # checkpoint for replay

    class Config:
        arbitrary_types_allowed = True
