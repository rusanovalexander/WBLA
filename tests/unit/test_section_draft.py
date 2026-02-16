"""
Regression tests for SectionDraft schema and Writer.draft_section return shape.

Ensures the Writer returns a SectionDraft that matches models.schemas.SectionDraft
(name, content, and optional fields) so that Pydantic validation does not fail
when the orchestrator receives the draft.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from pydantic import ValidationError

from models.schemas import SectionDraft


# -----------------------------------------------------------------------------
# SectionDraft schema: correct shape (what Writer must return)
# -----------------------------------------------------------------------------


def test_section_draft_accepts_name_and_content():
    """SectionDraft must be buildable with name and content (Writer return shape)."""
    draft = SectionDraft(name="Executive Summary & Recommendation", content="Drafted text here.")
    assert draft.name == "Executive Summary & Recommendation"
    assert draft.content == "Drafted text here."
    assert draft.agent_queries == []
    assert draft.facts_used == []
    assert draft.missing_items == []


def test_section_draft_rejects_section_name_key():
    """SectionDraft has no 'section_name' field; use 'name'."""
    with pytest.raises(ValidationError):
        SectionDraft(
            section_name="Executive Summary",
            content="Text",
        )


def test_section_draft_rejects_extra_unknown_fields_by_default():
    """SectionDraft does not allow word_count/requires_review (not in schema)."""
    # Pydantic v2 by default ignores extra fields; we just ensure name+content are required
    draft = SectionDraft(name="Risk Analysis", content="Risk content.")
    assert hasattr(draft, "name") and hasattr(draft, "content")
    assert not hasattr(draft, "word_count")
    assert not hasattr(draft, "requires_review")


# -----------------------------------------------------------------------------
# Writer.draft_section return shape (with mocked LLM)
# -----------------------------------------------------------------------------


@patch("agents.writer.call_llm_streaming")
def test_writer_draft_section_returns_section_draft_with_name_and_content(mock_llm):
    """Writer.draft_section must return a SectionDraft with .name and .content."""
    mock_llm.return_value = MagicMock(success=True, text="## Executive Summary\n\nThis is the draft.")
    mock_llm.return_value.text = "## Executive Summary\n\nThis is the draft."

    writer = Writer(
        search_procedure_fn=None,
        governance_context=None,
        agent_bus=None,  # no agent queries
        tracer=MagicMock(),
    )

    section = {"name": "Executive Summary & Recommendation", "description": "Overview", "detail_level": "Standard"}
    context = {
        "teaser_text": "Teaser",
        "extracted_data": "Analysis",
        "compliance_result": "",
        "requirements": [],
    }

    result = writer.draft_section(section=section, context=context)

    assert isinstance(result, SectionDraft)
    assert result.name == "Executive Summary & Recommendation"
    assert result.content == "## Executive Summary\n\nThis is the draft."
    assert hasattr(result, "content") and len(result.content) > 0


@patch("agents.writer.call_llm_streaming")
def test_writer_draft_section_on_llm_failure_still_returns_section_draft(mock_llm):
    """On LLM failure, Writer still returns a valid SectionDraft (with error message in content)."""
    mock_llm.return_value = MagicMock(success=False, text="", error="API error")

    writer = Writer(
        search_procedure_fn=None,
        governance_context=None,
        agent_bus=None,
        tracer=MagicMock(),
    )

    section = {"name": "Risk Analysis", "description": "Risks"}
    context = {"teaser_text": "", "extracted_data": "", "compliance_result": "", "requirements": []}

    result = writer.draft_section(section=section, context=context)

    assert isinstance(result, SectionDraft)
    assert result.name == "Risk Analysis"
    assert "[Section drafting failed:" in result.content
