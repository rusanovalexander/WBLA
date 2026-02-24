"""
Unit tests for chat action schema and hybrid routing.

- Action schema (ChatAction, ChatRoutingResult)
- Routing precedence: chat actions override workflow intents when ENABLE_CHAT_ACTIONS
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from models.schemas import ChatAction, ChatRoutingResult, OrchestratorResponse


def test_chat_action_enum_values():
    """ChatAction enum includes all planned commands."""
    assert ChatAction.GET_TEASER_DETAIL.value == "get_teaser_detail"
    assert ChatAction.GET_PROCEDURE_DETAIL.value == "get_procedure_detail"
    assert ChatAction.GET_GUIDELINE_DETAIL.value == "get_guideline_detail"
    assert ChatAction.ADD_FACT.value == "add_fact"
    assert ChatAction.UPDATE_FACT.value == "update_fact"
    assert ChatAction.OVERRIDE_DECISION.value == "override_decision"
    assert ChatAction.EDIT_REQUIREMENT.value == "edit_requirement"
    assert ChatAction.EDIT_SECTION.value == "edit_section"
    assert ChatAction.SHOW_STATE.value == "show_state"
    assert ChatAction.NONE.value == "none"


def test_chat_routing_result_defaults():
    """ChatRoutingResult defaults to NONE action and general intent."""
    r = ChatRoutingResult()
    assert r.action == ChatAction.NONE
    assert r.intent == "general"
    assert r.action_query == ""


def test_chat_routing_result_with_action():
    """ChatRoutingResult can hold action and extracted query."""
    r = ChatRoutingResult(
        action=ChatAction.GET_TEASER_DETAIL,
        intent="general",
        action_query="loan amount",
    )
    assert r.action == ChatAction.GET_TEASER_DETAIL
    assert r.action_query == "loan amount"


def test_orchestrator_response_has_rationale_and_steps():
    """OrchestratorResponse includes thinking_steps, rationale, content."""
    resp = OrchestratorResponse(
        thinking_steps=["Step 1", "Step 2"],
        rationale=["Reason A", "Reason B"],
        content="Final answer",
    )
    assert resp.thinking_steps == ["Step 1", "Step 2"]
    assert resp.rationale == ["Reason A", "Reason B"]
    assert resp.content == "Final answer"


def test_orchestrator_response_defaults():
    """OrchestratorResponse has safe defaults."""
    resp = OrchestratorResponse()
    assert resp.thinking_steps == []
    assert resp.rationale == []
    assert resp.content == ""
    assert resp.citations == []


@pytest.mark.parametrize("message,expected_action", [
    ("what does the teaser say about pricing", ChatAction.GET_TEASER_DETAIL),
    ("teaser detail on sponsor", ChatAction.GET_TEASER_DETAIL),
    ("what do procedures say about LTV", ChatAction.GET_PROCEDURE_DETAIL),
    ("procedure detail for assessment", ChatAction.GET_PROCEDURE_DETAIL),
    ("what do guidelines say about limits", ChatAction.GET_GUIDELINE_DETAIL),
    ("show state", ChatAction.SHOW_STATE),
    ("current state", ChatAction.SHOW_STATE),
    ("add this fact: borrower is corporate", ChatAction.ADD_FACT),
    ("override decision", ChatAction.OVERRIDE_DECISION),
    ("edit section Executive Summary", ChatAction.EDIT_SECTION),
])
def test_detect_chat_action_triggers(message: str, expected_action: ChatAction):
    """Orchestrator _detect_chat_action returns expected action for trigger phrases."""
    with patch("core.conversational_orchestrator_v2.ENABLE_CHAT_ACTIONS", True), \
         patch("core.conversational_orchestrator_v2.run_governance_discovery") as mock_gov:
        mock_gov.return_value = {"discovery_status": "complete", "requirement_categories": [], "compliance_framework": [], "risk_taxonomy": [], "search_vocabulary": []}
        from core.conversational_orchestrator_v2 import ConversationalOrchestratorV2
        orch = ConversationalOrchestratorV2()
        thinking = []
        routing = orch._detect_chat_action(message, thinking)
        assert routing.action == expected_action, f"message={message!r}"


def test_detect_chat_action_disabled_returns_none():
    """When ENABLE_CHAT_ACTIONS is False, _detect_chat_action always returns NONE."""
    with patch("core.conversational_orchestrator_v2.ENABLE_CHAT_ACTIONS", False), \
         patch("core.conversational_orchestrator_v2.run_governance_discovery") as mock_gov:
        mock_gov.return_value = {"discovery_status": "complete", "requirement_categories": [], "compliance_framework": [], "risk_taxonomy": [], "search_vocabulary": []}
        from core.conversational_orchestrator_v2 import ConversationalOrchestratorV2
        orch = ConversationalOrchestratorV2()
        thinking = []
        routing = orch._detect_chat_action("what does the teaser say", thinking)
        assert routing.action == ChatAction.NONE
