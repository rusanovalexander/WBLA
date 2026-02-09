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
