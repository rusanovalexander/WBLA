"""
Credit Pack root agent for ADK Web.

Phase 2: Root agent with tools that call ProcessAnalyst, ComplianceAdvisor, Writer.
Run from repo root with PYTHONPATH=. so runner and tools can import agents, core, config.
"""

import os

from google.adk.agents import LlmAgent

from .prompts import get_root_instruction
from .tools import (
    analyze_deal,
    discover_requirements,
    check_compliance,
    generate_structure,
    draft_section,
    set_teaser,
    set_example,
    export_credit_pack,
)

# Model: use env or default
_model = os.getenv("ADK_CREDIT_PACK_MODEL", "gemini-2.0-flash")

root_agent = LlmAgent(
    model=_model,
    name="credit_pack_root",
    description="Orchestrates credit pack drafting: deal analysis, requirements, compliance, structure, and section drafting. Use set_teaser/analyze_deal first, then requirements, compliance, structure, draft_section.",
    instruction=get_root_instruction(),
    tools=[
        set_teaser,
        set_example,
        analyze_deal,
        discover_requirements,
        check_compliance,
        generate_structure,
        draft_section,
        export_credit_pack,
    ],
)
