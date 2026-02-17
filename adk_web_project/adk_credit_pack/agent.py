"""
Credit Pack root agent for ADK Web.

Phase 1: Shell only. Tools and sub-agents (ProcessAnalyst, ComplianceAdvisor, Writer)
will be added in later phases. See MIGRATION_PLAN_ADK_DATA_SCIENCE.md in repo root.
"""

import os

from google.adk.agents import LlmAgent

from .prompts import get_root_instruction

# Model: use env or default to a common Vertex/Gemini model
_model = os.getenv("ADK_CREDIT_PACK_MODEL", "gemini-2.0-flash")

root_agent = LlmAgent(
    model=_model,
    name="credit_pack_root",
    description="Orchestrates credit pack drafting: deal analysis, requirements, compliance, structure, and section drafting.",
    instruction=get_root_instruction(),
    tools=[],  # Phase 2: add AgentTools for ProcessAnalyst, ComplianceAdvisor, Writer
)
