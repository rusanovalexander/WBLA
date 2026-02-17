"""
ADK tools that call Credit Pack agents (ProcessAnalyst, ComplianceAdvisor, Writer).

State is passed via tool_context.state. Run from repo root with PYTHONPATH=. so that
agents, core, config, tools can be imported (see runner.py).
"""

import asyncio
import json
import logging
from typing import Any

from .runner import get_analyst, get_advisor, get_writer

logger = logging.getLogger(__name__)

# Fallback state when ToolContext is not injected (some ADK versions omit it from schema)
_fallback_state: dict[str, Any] = {}


def _state(tool_context: Any) -> dict:
    """Get mutable state dict from tool context or fallback."""
    if tool_context is not None and hasattr(tool_context, "state"):
        return tool_context.state
    return _fallback_state


async def analyze_deal(teaser_text: str, tool_context: Any = None) -> dict[str, Any]:
    """
    Run deal analysis on the given teaser text. Determines process path and origination method.

    Call this when the user provides a teaser or asks to analyze a deal. Store the teaser
    in state (e.g. from a previous message) or pass it here. Result is stored in state
    under 'analysis' for use by discover_requirements and later steps.

    Args:
        teaser_text: Full text of the deal teaser document to analyze.
        tool_context: ADK tool context (injected when available); used to read/write state.

    Returns:
        Dict with status, process_path, origination_method, and a short summary.
    """
    state = _state(tool_context)
    if not teaser_text or not teaser_text.strip():
        return {"status": "error", "message": "teaser_text is required and must be non-empty."}
    try:
        analyst = get_analyst()
        result = await asyncio.to_thread(
            analyst.analyze_deal, teaser_text.strip(), False
        )
        state["analysis"] = result
        state["teaser_text"] = teaser_text.strip()
        path = result.get("process_path") or "N/A"
        origin = result.get("origination_method") or "N/A"
        return {
            "status": "success",
            "process_path": path,
            "origination_method": origin,
            "summary": f"Analysis complete. Process path: {path}, Origination: {origin}. Use discover_requirements next.",
        }
    except Exception as e:
        logger.exception("analyze_deal failed")
        return {"status": "error", "message": str(e)}


async def discover_requirements(
    analysis_text: str, tool_context: Any = None
) -> dict[str, Any]:
    """
    Discover dynamic requirements from the analysis. Requires 'analysis' in state from analyze_deal.

    Call after analyze_deal. Uses assessment_approach and origination_method from the analysis.
    Result is stored in state under 'requirements'.

    Args:
        analysis_text: The full analysis text (usually from state['analysis']['full_analysis']).
        tool_context: ADK tool context for state.

    Returns:
        Dict with status and count of requirements (filled vs need data).
    """
    state = _state(tool_context)
    analysis = state.get("analysis") or {}
    if not analysis and not analysis_text:
        return {"status": "error", "message": "Run analyze_deal first or pass analysis_text."}
    text = analysis_text or analysis.get("full_analysis", "")
    if not text:
        return {"status": "error", "message": "No analysis text available."}
    assessment = analysis.get("process_path") or analysis.get("assessment_approach") or ""
    origin = analysis.get("origination_method") or ""
    try:
        analyst = get_analyst()
        requirements = await asyncio.to_thread(
            analyst.discover_requirements, text, assessment, origin
        )
        state["requirements"] = requirements
        filled = sum(1 for r in requirements if r.get("status") == "filled")
        return {
            "status": "success",
            "total": len(requirements),
            "filled": filled,
            "summary": f"Discovered {len(requirements)} requirements ({filled} pre-filled). Use check_compliance next.",
        }
    except Exception as e:
        logger.exception("discover_requirements failed")
        return {"status": "error", "message": str(e)}


async def check_compliance(
    requirements_json: str, tool_context: Any = None
) -> dict[str, Any]:
    """
    Run compliance assessment using filled requirements and analysis. Requires 'analysis'
    and 'requirements' in state from previous steps.

    Args:
        requirements_json: Optional JSON array of requirements; if empty, state['requirements'] is used.
        tool_context: ADK tool context for state.

    Returns:
        Dict with status and short compliance summary.
    """
    state = _state(tool_context)
    analysis = state.get("analysis") or {}
    requirements = state.get("requirements") or []
    if requirements_json and requirements_json.strip():
        try:
            requirements = json.loads(requirements_json)
        except json.JSONDecodeError:
            pass
    if not requirements:
        return {"status": "error", "message": "No requirements in state. Run discover_requirements first."}
    teaser = state.get("teaser_text", "")
    extracted = analysis.get("full_analysis", "")
    try:
        advisor = get_advisor()
        analysis_text, checks = await asyncio.to_thread(
            advisor.assess_compliance, requirements, teaser, extracted, False
        )
        state["compliance_analysis"] = analysis_text
        state["compliance_checks"] = checks
        return {
            "status": "success",
            "checks_count": len(checks),
            "summary": f"Compliance assessment complete ({len(checks)} checks). Use generate_structure next.",
        }
    except Exception as e:
        logger.exception("check_compliance failed")
        return {"status": "error", "message": str(e)}


async def generate_structure(
    example_text: str, tool_context: Any = None
) -> dict[str, Any]:
    """
    Generate the document section structure. Requires 'analysis' in state. Optionally
    use example_text from state or from a previous step.

    Args:
        example_text: Optional example document text for style; can be empty to use state or defaults.
        tool_context: ADK tool context for state.

    Returns:
        Dict with status and list of section names.
    """
    state = _state(tool_context)
    analysis = state.get("analysis") or {}
    if not analysis:
        return {"status": "error", "message": "Run analyze_deal first."}
    example = example_text.strip() or state.get("example_text", "")
    assessment = analysis.get("process_path") or analysis.get("assessment_approach") or ""
    origin = analysis.get("origination_method") or ""
    full_analysis = analysis.get("full_analysis", "")
    try:
        writer = get_writer()
        structure = await asyncio.to_thread(
            writer.generate_structure,
            example, assessment, origin, full_analysis,
        )
        state["structure"] = structure
        state["example_text"] = example or state.get("example_text", "")
        names = [s.get("name", "?") for s in structure]
        return {
            "status": "success",
            "sections": names,
            "summary": f"Generated {len(structure)} sections: " + ", ".join(names[:8]) + ("..." if len(names) > 8 else ""),
        }
    except Exception as e:
        logger.exception("generate_structure failed")
        return {"status": "error", "message": str(e)}


async def draft_section(
    section_name: str, tool_context: Any = None
) -> dict[str, Any]:
    """
    Draft one section of the document by name. Requires 'structure', 'analysis',
    'requirements', and optionally 'compliance_checks' and previously drafted sections in state.

    Args:
        section_name: Exact or partial name of the section to draft (e.g. 'Executive Summary').
        tool_context: ADK tool context for state.

    Returns:
        Dict with status and draft text preview.
    """
    state = _state(tool_context)
    structure = state.get("structure") or []
    if not structure:
        return {"status": "error", "message": "Run generate_structure first."}
    section = None
    for s in structure:
        if section_name.lower() in (s.get("name") or "").lower():
            section = s
            break
    if not section:
        return {"status": "error", "message": f"No section matching '{section_name}'. Available: {[s.get('name') for s in structure]}."}
    analysis = state.get("analysis") or {}
    requirements = state.get("requirements") or []
    compliance_checks = state.get("compliance_checks") or []
    drafts = state.get("drafts") or []
    example = state.get("example_text", "")
    previously_drafted = "\n\n".join(
        f"## {d.name}\n\n{d.content}" for d in drafts if getattr(d, "name", None) and getattr(d, "content", None)
    )
    teaser = state.get("teaser_text", "")
    compliance_analysis = state.get("compliance_analysis", "")
    context = {
        "teaser_text": teaser,
        "example_text": example,
        "extracted_data": analysis.get("full_analysis", ""),
        "compliance_result": compliance_analysis,
        "requirements": requirements,
        "compliance_checks": compliance_checks,
        "structure": structure,
        "previously_drafted": previously_drafted,
    }
    try:
        writer = get_writer()
        draft = await asyncio.to_thread(
            writer.draft_section, section, context, None
        )
        if not drafts:
            state["drafts"] = [draft]
        else:
            state["drafts"] = drafts + [draft]
        preview = (draft.content or "")[:300] + ("..." if len(draft.content or "") > 300 else "")
        return {
            "status": "success",
            "section": section.get("name"),
            "preview": preview,
            "summary": f"Drafted section '{section.get('name')}'. You can draft more sections or export.",
        }
    except Exception as e:
        logger.exception("draft_section failed")
        return {"status": "error", "message": str(e)}


async def set_teaser(teaser_text: str, tool_context: Any = None) -> dict[str, Any]:
    """
    Store the user's teaser text in state so analyze_deal can use it. Call when the user
    pastes or uploads a teaser document.

    Args:
        teaser_text: Full text of the teaser document.
        tool_context: ADK tool context for state.

    Returns:
        Dict with status.
    """
    state = _state(tool_context)
    state["teaser_text"] = teaser_text.strip() if teaser_text else ""
    return {"status": "success", "message": "Teaser text stored. Call analyze_deal next."}


async def set_example(example_text: str, tool_context: Any = None) -> dict[str, Any]:
    """
    Store example document text for structure and drafting style. Call when the user
    provides an example credit pack.

    Args:
        example_text: Full text of the example document.
        tool_context: ADK tool context for state.

    Returns:
        Dict with status.
    """
    state = _state(tool_context)
    state["example_text"] = example_text.strip() if example_text else ""
    return {"status": "success", "message": "Example text stored for structure and drafting."}
