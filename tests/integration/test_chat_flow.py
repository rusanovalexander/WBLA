"""
Integration tests for chat flow: key intents and response shape.

- show state returns rationale and thinking_steps
- get_teaser_detail returns citations when teaser present
- Response dict always has thinking_steps, rationale, content (normalized)
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_governance():
    """Mock governance discovery for orchestrator init."""
    with patch("core.conversational_orchestrator_v2.run_governance_discovery") as m:
        m.return_value = {
            "discovery_status": "complete",
            "requirement_categories": [],
            "compliance_framework": [],
            "risk_taxonomy": [],
            "search_vocabulary": [],
        }
        yield m


@pytest.fixture
def orchestrator(mock_governance):
    """Orchestrator with mocked governance (no RAG/LLM for these tests)."""
    with patch("core.conversational_orchestrator_v2.ENABLE_CHAT_ACTIONS", True), \
         patch("core.conversational_orchestrator_v2.ENABLE_PERSISTENT_MEMORY", False):
        from core.conversational_orchestrator_v2 import ConversationalOrchestratorV2
        return ConversationalOrchestratorV2()


def test_show_state_returns_rationale_and_steps(orchestrator):
    """Show state intent returns response with rationale and thinking_steps."""
    result = orchestrator._handle_show_state([])
    assert "response" in result
    assert "rationale" in result
    assert "thinking" in result
    assert isinstance(result["rationale"], list)
    assert len(result["rationale"]) >= 1
    assert "Phase" in result["response"] or "phase" in result["response"].lower()


def test_get_teaser_detail_no_teaser_returns_error(orchestrator):
    """Get teaser detail without teaser returns error and rationale."""
    result = orchestrator._handle_get_teaser_detail("loan amount", [])
    assert "response" in result
    assert "rationale" in result
    assert "No teaser" in result["response"] or "teaser" in result["response"].lower()


def test_get_teaser_detail_with_teaser_returns_citations(orchestrator):
    """Get teaser detail with teaser set returns content and citations."""
    orchestrator.persistent_context["teaser_text"] = "The loan amount is 50 million. Sponsor is ABC Corp."
    orchestrator.persistent_context["teaser_filename"] = "teaser.pdf"
    result = orchestrator._handle_get_teaser_detail("loan amount", [])
    assert "response" in result
    assert "rationale" in result
    assert result.get("citations") is not None
    assert "50" in result["response"] or "loan" in result["response"].lower()


def test_process_message_normalizes_result(orchestrator):
    """process_message result includes thinking_steps, rationale, content (normalized)."""
    with patch.object(orchestrator, "_detect_chat_action") as mock_detect:
        from models.schemas import ChatAction, ChatRoutingResult
        mock_detect.return_value = ChatRoutingResult(action=ChatAction.SHOW_STATE, intent="general")
        result = orchestrator.process_message("show state", {}, None, None)
    assert "thinking_steps" in result
    assert "rationale" in result
    assert "content" in result
    assert result["content"] == result["response"]


def test_feature_flag_disable_chat_actions(mock_governance):
    """When ENABLE_CHAT_ACTIONS is False, show state is not routed as chat action."""
    with patch("core.conversational_orchestrator_v2.ENABLE_CHAT_ACTIONS", False), \
         patch("core.conversational_orchestrator_v2.ENABLE_PERSISTENT_MEMORY", False):
        from core.conversational_orchestrator_v2 import ConversationalOrchestratorV2
        orch = ConversationalOrchestratorV2()
        routing = orch._detect_chat_action("show state", [])
        assert routing.action.value == "none"
