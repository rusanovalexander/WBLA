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

_fallback_state: dict[str, Any] = {}


def _state(tool_context: Any) -> dict:
    if tool_context is not None and hasattr(tool_context, "state"):
        return tool_context.state
    return _fallback_state


async def set_teaser(teaser_text: str, tool_context: Any = None) -> dict[str, Any]:
    """Store the user's teaser text in state. Call when the user pastes or uploads a teaser."""
    state = _state(tool_context)
    state["teaser_text"] = (teaser_text or "").strip()
    return {"status": "success", "message": "Teaser text stored. Call analyze_deal next."}


async def set_example(example_text: str, tool_context: Any = None) -> dict[str, Any]:
    """Store example document text for structure and drafting style."""
    state = _state(tool_context)
    state["example_text"] = (example_text or "").strip()
    return {"status": "success", "message": "Example text stored for structure and drafting."}


async def analyze_deal(teaser_text: str = "", tool_context: Any = None) -> dict[str, Any]:
    """
    Run deal analysis on teaser text. Determines process path and origination method.
    Pass teaser_text or use stored state. Result stored in state. Include thinking in your reply.
    """
    state = _state(tool_context)
    provided_teaser = (teaser_text or "").strip()
    stored_teaser = (state.get("teaser_text") or "").strip()
    effective_teaser = provided_teaser or stored_teaser
    if not effective_teaser:
        return {
            "status": "error",
            "message": "No teaser available. Provide teaser_text or call set_teaser first.",
        }
    thinking_parts: list[str] = [
        "⏳ Starting deal analysis.",
        "Planning procedure searches.",
        "Searching procedure documents (RAG).",
        "Running full analysis (model output below).",
    ]
    streamed: list[str] = []
    try:
        analyst = get_analyst()

        def collect_stream(chunk: str) -> None:
            streamed.append(chunk)

        result = await asyncio.to_thread(
            analyst.analyze_deal, effective_teaser, False, collect_stream
        )
        state["analysis"] = result
        state["teaser_text"] = effective_teaser
        path = result.get("process_path") or "N/A"
        origin = result.get("origination_method") or "N/A"
        llm_thinking = result.get("llm_thinking")
        if llm_thinking and llm_thinking.strip():
            thinking_parts = [llm_thinking.strip()]
        else:
            model_output = "".join(streamed)
            if len(model_output) > 8000:
                model_output = model_output[:8000] + "\n\n[... truncated for display ...]"
            if model_output.strip():
                thinking_parts.append("--- Model output ---\n" + model_output.strip())
        thinking_parts.append(f"✓ Extracted decision: process path={path}, origination={origin}.")
        thinking_text = "\n\n".join(thinking_parts)
        return {
            "status": "success",
            "process_path": path,
            "origination_method": origin,
            "summary": f"Analysis complete. Process path: {path}, Origination: {origin}. Use discover_requirements next.",
            "thinking": thinking_text,
        }
    except Exception as e:
        logger.exception("analyze_deal failed")
        return {"status": "error", "message": str(e), "thinking": "\n".join(thinking_parts)}


async def discover_requirements(
    analysis_text: str = "", tool_context: Any = None
) -> dict[str, Any]:
    """
    Discover dynamic requirements from the analysis. Requires 'analysis' in state from analyze_deal.
    Call after analyze_deal. Result stored in state under 'requirements'.
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
    requirements_json: str = "", tool_context: Any = None
) -> dict[str, Any]:
    """
    Run compliance assessment using requirements and analysis. Requires 'analysis' and 'requirements' in state.
    Pass requirements_json or use state['requirements'].
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
    example_text: str = "", tool_context: Any = None
) -> dict[str, Any]:
    """
    Generate the document section structure. Requires 'analysis' in state. Optionally use example_text from state.
    """
    state = _state(tool_context)
    analysis = state.get("analysis") or {}
    if not analysis:
        return {"status": "error", "message": "Run analyze_deal first."}
    example = (example_text or "").strip() or state.get("example_text", "")
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
    Draft one section by name. Requires 'structure', 'analysis', 'requirements' in state.
    """
    state = _state(tool_context)
    structure = state.get("structure") or []
    if not structure:
        return {"status": "error", "message": "Run generate_structure first."}
    section = None
    for s in structure:
        if (section_name or "").lower() in (s.get("name") or "").lower():
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


async def export_credit_pack(filename: str = "", tool_context: Any = None) -> dict[str, Any]:
    """
    Export the current credit pack to a DOCX file. Uses structure and drafts from state.
    Call after at least one section has been drafted.
    """
    from datetime import datetime

    state = _state(tool_context)
    structure = state.get("structure") or []
    drafts = state.get("drafts") or []
    if not structure or not drafts:
        return {
            "status": "error",
            "message": "No structure or drafts in state. Generate structure and draft at least one section first.",
        }
    parts = []
    draft_by_name = {getattr(d, "name", ""): d for d in drafts if getattr(d, "name", None)}
    for sec in structure:
        name = sec.get("name", "")
        d = draft_by_name.get(name)
        if d is None:
            continue
        content = getattr(d, "content", "") or ""
        if content:
            parts.append(f"# {name}\n\n{content}")
    if not parts:
        return {"status": "error", "message": "No draft content to export."}
    final_document = "\n\n---\n\n".join(parts)
    analysis = state.get("analysis") or {}
    metadata = {}
    if analysis.get("process_path"):
        metadata["process_path"] = analysis["process_path"]
    if analysis.get("origination_method"):
        metadata["origination_method"] = analysis["origination_method"]
    try:
        from config.settings import PRODUCT_NAME
        from core.export import generate_docx

        if not filename or not filename.strip():
            filename = f"{PRODUCT_NAME.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
        elif not filename.lower().endswith(".docx"):
            filename = filename.rstrip() + ".docx"
        path = generate_docx(final_document, filename.strip(), metadata)
        if path:
            return {
                "status": "success",
                "path": path,
                "message": f"Credit pack exported to {path}",
            }
        return {"status": "error", "message": "DOCX generation failed."}
    except Exception as e:
        logger.exception("export_credit_pack failed")
        return {"status": "error", "message": str(e)}
