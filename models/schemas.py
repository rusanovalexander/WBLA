"""
Pydantic models for Credit Pack PoC v3.2.

Replaces raw dicts with validated, self-documenting data structures.
Every data boundary (LLM output, session state, agent communication)
should flow through these models.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

class WorkflowPhase(str, Enum):
    SETUP = "SETUP"
    ANALYSIS = "ANALYSIS"
    PROCESS_GAPS = "PROCESS_GAPS"
    COMPLIANCE = "COMPLIANCE"
    DRAFTING = "DRAFTING"
    COMPLETE = "COMPLETE"


class RiskSeverity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ComplianceStatus(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"
    NA = "N/A"


class RequirementStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    SKIPPED = "skipped"


class ChangeType(str, Enum):
    REQUIREMENT_EDIT = "requirement_edit"
    SECTION_EDIT = "section_edit"
    MANUAL_INPUT = "manual_input"
    AI_SUGGESTION_ACCEPTED = "ai_suggestion_accepted"
    FILE_ANALYSIS_ACCEPTED = "file_analysis_accepted"


# =============================================================================
# Agent Communication
# =============================================================================

class AgentMessage(BaseModel):
    """Record of agent-to-agent communication."""
    timestamp: str = Field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    from_agent: str
    to_agent: str
    query: str
    response: str = ""


class AgentTraceEntry(BaseModel):
    """Single entry in the agent activity trace."""
    time: str = Field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    agent: str
    action: str
    detail: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    model: str = ""


# =============================================================================
# LLM
# =============================================================================

class LLMCallResult(BaseModel):
    """Result from an LLM call with metadata."""
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    agent_name: str = "LLM"
    success: bool = True
    error: str | None = None
    reasoning: str | None = None  # Extended thinking / rationale from model


# =============================================================================
# Chat action schema and routing
# =============================================================================

class ChatAction(str, Enum):
    """Free-form chat commands; take precedence over workflow intents when detected."""
    GET_TEASER_DETAIL = "get_teaser_detail"
    GET_PROCEDURE_DETAIL = "get_procedure_detail"
    GET_GUIDELINE_DETAIL = "get_guideline_detail"
    ADD_FACT = "add_fact"
    UPDATE_FACT = "update_fact"
    OVERRIDE_DECISION = "override_decision"
    EDIT_REQUIREMENT = "edit_requirement"
    EDIT_SECTION = "edit_section"
    SHOW_STATE = "show_state"
    NONE = "none"  # No chat action; use workflow intent


class ChatRoutingResult(BaseModel):
    """Result of hybrid router: chat action (if any) and workflow intent."""
    action: ChatAction = ChatAction.NONE
    intent: str = "general"  # analyze_deal, discover_requirements, etc.
    action_query: str = ""  # Extracted query for get_teaser_detail / get_procedure_detail / etc.
    reasoning: str | None = None


class OrchestratorResponse(BaseModel):
    """Structured response from orchestrator for UI: steps, rationale, content."""
    thinking_steps: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)  # 2-6 bullets
    content: str = ""
    response: str = ""  # Alias for content (backward compat)
    action: str | None = None
    requires_approval: bool = False
    next_suggestion: str | None = None
    agent_communication: str | None = None
    sources_used: dict[str, Any] = Field(default_factory=dict)
    citations: list[dict[str, Any]] = Field(default_factory=list)  # For retrieval-on-demand


# =============================================================================
# Process Decision
# =============================================================================

class ProcessDecisionEvidence(BaseModel):
    """Evidence supporting a process path decision."""
    deal_size: str = "Unknown"
    reasoning: str = ""
    rag_sources: list[str] = Field(default_factory=list)


class ProcessDecision(BaseModel):
    """Locked process path decision from Phase 1."""
    assessment_approach: str
    origination_method: str
    procedure_section: str = ""
    determined_by: str = "Process Analyst Agent"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    evidence: ProcessDecisionEvidence = Field(default_factory=ProcessDecisionEvidence)
    locked: bool = False



# =============================================================================
# Requirements
# =============================================================================

class Requirement(BaseModel):
    """A single data requirement for the credit pack."""
    id: int
    name: str
    description: str = ""
    why_required: str = ""
    typical_source: str = "teaser"
    priority: str = "IMPORTANT"  # CRITICAL, IMPORTANT, SUPPORTING
    status: RequirementStatus = RequirementStatus.PENDING
    value: str = ""
    source: str = ""
    evidence: str = ""
    suggestion_detail: str = ""
    category: str = ""


# =============================================================================
# Compliance
# =============================================================================

class ComplianceCheck(BaseModel):
    """Single compliance criterion check."""
    criterion: str
    guideline_limit: str = ""
    deal_value: str = ""
    status: ComplianceStatus = ComplianceStatus.REVIEW
    evidence: str = ""
    reference: str = ""
    severity: str = "MUST"  # MUST or SHOULD


# =============================================================================
# Drafting
# =============================================================================

class SectionDefinition(BaseModel):
    """Definition of a credit pack section to draft."""
    name: str
    description: str = ""
    detail_level: str = "Standard"


class SectionDraft(BaseModel):
    """A drafted section with metadata."""
    name: str
    content: str
    agent_queries: list[AgentMessage] = Field(default_factory=list)
    facts_used: list[dict[str, str]] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)


# =============================================================================
# Change Tracking
# =============================================================================

class ChangeEntry(BaseModel):
    """A single change record in the audit trail."""
    id: int
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    type: ChangeType
    field: str
    old_value: str = ""
    new_value: str = ""
    phase: str = ""
    user_note: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Risk Flags
# =============================================================================

class RiskFlag(BaseModel):
    """A risk flag raised by the orchestrator."""
    text: str
    severity: RiskSeverity = RiskSeverity.MEDIUM


class OrchestratorInsights(BaseModel):
    """Structured insights from an orchestrator decision point."""
    full_text: str = ""
    observations: list[str] = Field(default_factory=list)
    flags: list[RiskFlag] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    message_to_human: str = ""
    # Routing decisions — these MUST affect workflow
    can_proceed: bool = True
    requires_human_review: bool = False
    suggested_additional_steps: list[str] = Field(default_factory=list)
    block_reason: str = ""


# =============================================================================
# RAG
# =============================================================================

class RAGResult(BaseModel):
    """A single RAG search result."""
    id: str = ""
    uri: str = ""
    doc_type: str = "Unknown"
    title: str = ""
    content: str = ""


class RAGSearchResponse(BaseModel):
    """Response from a RAG search."""
    status: str = "OK"
    query: str = ""
    num_results: int = 0
    results: list[RAGResult] = Field(default_factory=list)
    error: str | None = None


# =============================================================================
# Field Discovery
# =============================================================================

class DealCharacteristics(BaseModel):
    """Analyzed deal characteristics for dynamic field discovery."""
    transaction_type: str = "new"
    structure: str = "secured"
    asset_class: str = "real_estate"
    asset_subtype: str = "N/A"
    special_features: list[str] = Field(default_factory=list)
    parties: list[str] = Field(default_factory=list)
    jurisdiction: str = "Unknown"
    regulatory_context: str = "standard"
    complexity_indicators: list[str] = Field(default_factory=list)


class DiscoveredField(BaseModel):
    """A field discovered through dynamic analysis."""
    name: str
    description: str = ""
    why_required: str = ""
    data_type: str = "text"
    typical_source: str = "teaser"
    priority: str = "IMPORTANT"


class FieldGroup(BaseModel):
    """A group of discovered fields under a category."""
    category: str
    fields: list[DiscoveredField] = Field(default_factory=list)


# =============================================================================
# Governance Discovery
# =============================================================================

class GovernanceContext(BaseModel):
    """
    Discovered governance context from Procedure & Guidelines documents.

    Populated at startup via RAG queries. Used to parameterize all agent
    prompts so the system adapts to ANY bank's governance framework
    without code changes.
    """
    requirement_categories: list[str] = Field(default_factory=list)
    compliance_framework: list[str] = Field(default_factory=list)
    section_templates: dict[str, list[dict[str, str]]] = Field(default_factory=dict)
    risk_taxonomy: list[str] = Field(default_factory=list)
    deal_taxonomy: dict[str, list[str]] = Field(default_factory=dict)
    terminology_map: dict[str, list[str]] = Field(default_factory=dict)
    search_vocabulary: list[str] = Field(default_factory=list)
    raw_procedure_excerpts: dict[str, str] = Field(default_factory=dict)
    raw_guidelines_excerpts: dict[str, str] = Field(default_factory=dict)
    discovery_timestamp: str = ""
    discovery_status: str = "pending"  # pending | complete | partial | failed
