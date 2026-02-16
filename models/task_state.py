from __future__ import annotations

"""
TaskState models: high-level view of the conversational workflow.

This provides an ADK-style typed snapshot of where the user is in the
end-to-end flow (setup → analysis → requirements → compliance → drafting),
derived from the orchestrator's persistent_context and conversation.
"""

from typing import Any

from pydantic import BaseModel, Field

from .schemas import WorkflowPhase


class TaskStepState(BaseModel):
    """Status for a single logical step in the workflow."""

    name: str
    done: bool = False
    details: str = ""


class TaskState(BaseModel):
    """
    High-level task state for the current conversation.

    This is intentionally coarse-grained so it can be safely computed from
    existing context without changing behaviour, and used by the UI and
    higher-level planners for visualization and control.
    """

    phase: WorkflowPhase = WorkflowPhase.SETUP
    steps: list[TaskStepState] = Field(default_factory=list)

    # Simple progress flags
    teaser_uploaded: bool = False
    analysis_done: bool = False
    requirements_done: bool = False
    compliance_done: bool = False
    structure_done: bool = False
    drafting_started: bool = False
    drafting_completed: bool = False

    conversation_turns: int = 0

    @classmethod
    def from_context(
        cls,
        persistent_context: dict[str, Any],
        conversation_turns: int,
    ) -> "TaskState":
        """Build a TaskState snapshot from orchestrator context."""
        teaser_uploaded = bool(persistent_context.get("teaser_text"))
        analysis = persistent_context.get("analysis")
        requirements = persistent_context.get("requirements") or []
        compliance_checks = persistent_context.get("compliance_checks") or []
        structure = persistent_context.get("structure") or []
        drafts = persistent_context.get("drafts") or {}
        current_idx = persistent_context.get("current_section_index", 0)

        analysis_done = bool(analysis)
        requirements_done = len(requirements) > 0
        compliance_done = len(compliance_checks) > 0
        structure_done = len(structure) > 0
        drafting_started = len(drafts) > 0
        drafting_completed = bool(
            structure_done and current_idx >= len(structure) and len(drafts) >= len(structure)
        )

        # Determine coarse phase
        if not teaser_uploaded:
            phase = WorkflowPhase.SETUP
        elif not analysis_done:
            phase = WorkflowPhase.ANALYSIS
        elif not requirements_done:
            phase = WorkflowPhase.PROCESS_GAPS
        elif not compliance_done:
            phase = WorkflowPhase.COMPLIANCE
        elif not drafting_completed:
            phase = WorkflowPhase.DRAFTING
        else:
            phase = WorkflowPhase.COMPLETE

        steps: list[TaskStepState] = [
            TaskStepState(name="Upload teaser", done=teaser_uploaded),
            TaskStepState(name="Analyze deal", done=analysis_done),
            TaskStepState(name="Discover requirements", done=requirements_done),
            TaskStepState(name="Run compliance checks", done=compliance_done),
            TaskStepState(name="Generate structure", done=structure_done),
            TaskStepState(name="Draft sections", done=drafting_completed),
        ]

        return cls(
            phase=phase,
            steps=steps,
            teaser_uploaded=teaser_uploaded,
            analysis_done=analysis_done,
            requirements_done=requirements_done,
            compliance_done=compliance_done,
            structure_done=structure_done,
            drafting_started=drafting_started,
            drafting_completed=drafting_completed,
            conversation_turns=conversation_turns,
        )

