"""
Credit Pack root agent — ADK Samples style.

Run from repo root: PYTHONPATH=. uv run --project credit-pack adk web
"""

import os

from google.adk.agents import LlmAgent

from .prompt import get_root_instruction
from .tools import (
    analyze_deal,
    check_compliance,
    discover_requirements,
    draft_section,
    export_credit_pack,
    generate_structure,
    set_example,
    set_teaser,
)

_model = os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash")

root_agent = LlmAgent(
    model=_model,
    name="credit_pack_root",
    description="Orchestrates credit pack: analyze deal, requirements, compliance, structure, drafting. Use set_teaser then analyze_deal first.",
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
