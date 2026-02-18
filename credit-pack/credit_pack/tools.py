"""
ADK tools for Credit Pack. Self-contained: uses only credit_pack.analyst, .compliance, .writer, .export_docx.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from . import analyst
from . import compliance
from . import writer
from . import export_docx
from . import config

logger = logging.getLogger(__name__)
_fallback_state: dict[str, Any] = {}


def _state(tool_context: Any) -> dict:
    if tool_context is not None and hasattr(tool_context, "state"):
        return tool_context.state
    return _fallback_state


async def set_teaser(teaser_text: str, tool_context: Any = None) -> dict[str, Any]:
    """Store the user's teaser text in state."""
    state = _state(tool_context)
    state["teaser_text"] = (teaser_text or "").strip()
    return {"status": "success", "message": "Teaser text stored. Call analyze_deal next."}


async def set_example(example_text: str, tool_context: Any = None) -> dict[str, Any]:
    """Store example document text for structure and drafting style."""
    state = _state(tool_context)
    state["example_text"] = (example_text or "").strip()
    return {"status": "success", "message": "Example text stored for structure and drafting."}


async def analyze_deal(teaser_text: str = "", tool_context: Any = None) -> dict[str, Any]:
    """Run deal analysis. Pass teaser_text or use stored state. Include thinking in your reply."""
    state = _state(tool_context)
    effective_teaser = (teaser_text or "").strip() or (state.get("teaser_text") or "").strip()
    if not effective_teaser:
        return {"status": "error", "message": "No teaser available. Provide teaser_text or call set_teaser first."}
    thinking_parts = ["⏳ Starting deal analysis.", "Running full analysis (model output below)."]
    try:
        result = await asyncio.to_thread(analyst.analyze_deal, effective_teaser, False, None)
        state["analysis"] = result
        state["teaser_text"] = effective_teaser
        path = result.get("process_path") or "N/A"
        origin = result.get("origination_method") or "N/A"
        llm_thinking = result.get("llm_thinking")
        if llm_thinking and llm_thinking.strip():
            thinking_parts = [llm_thinking.strip()]
        else:
            full = result.get("full_analysis", "")
            if full:
                thinking_parts.append("--- Model output ---\n" + (full[:8000] + "\n\n[... truncated ...]" if len(full) > 8000 else full))
        thinking_parts.append(f"✓ Extracted decision: process path={path}, origination={origin}.")
        return {
            "status": "success",
            "process_path": path,
            "origination_method": origin,
            "summary": f"Analysis complete. Process path: {path}, Origination: {origin}. Use discover_requirements next.",
            "thinking": "\n\n".join(thinking_parts),
        }
    except Exception as e:
        logger.exception("analyze_deal failed")
        return {"status": "error", "message": str(e), "thinking": "\n".join(thinking_parts)}


async def discover_requirements(analysis_text: str = "", tool_context: Any = None) -> dict[str, Any]:
    """Discover dynamic requirements from the analysis. Call after analyze_deal."""
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
        requirements = await asyncio.to_thread(analyst.discover_requirements, text, assessment, origin)
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


async def check_compliance(requirements_json: str = "", tool_context: Any = None) -> dict[str, Any]:
    """Run compliance assessment. Call after discover_requirements."""
    state = _state(tool_context)
    requirements = state.get("requirements") or []
    if requirements_json and requirements_json.strip():
        try:
            requirements = json.loads(requirements_json)
        except json.JSONDecodeError:
            pass
    if not requirements:
        return {"status": "error", "message": "No requirements in state. Run discover_requirements first."}
    teaser = state.get("teaser_text", "")
    analysis = state.get("analysis") or {}
    extracted = analysis.get("full_analysis", "")
    try:
        analysis_text, checks = await asyncio.to_thread(
            compliance.assess_compliance, requirements, teaser, extracted, False
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


async def generate_structure(example_text: str = "", tool_context: Any = None) -> dict[str, Any]:
    """Generate document section structure. Call after analyze_deal."""
    state = _state(tool_context)
    analysis = state.get("analysis") or {}
    if not analysis:
        return {"status": "error", "message": "Run analyze_deal first."}
    example = (example_text or "").strip() or state.get("example_text", "")
    assessment = analysis.get("process_path") or analysis.get("assessment_approach") or ""
    origin = analysis.get("origination_method") or ""
    full_analysis = analysis.get("full_analysis", "")
    try:
        structure = await asyncio.to_thread(
            writer.generate_structure, example, assessment, origin, full_analysis
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


async def draft_section(section_name: str, tool_context: Any = None) -> dict[str, Any]:
    """Draft one section by name. Call after generate_structure."""
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
        f"## {getattr(d, 'name', '')}\n\n{getattr(d, 'content', '')}" for d in drafts if getattr(d, "name", None)
    )
    ctx = {
        "teaser_text": state.get("teaser_text", ""),
        "example_text": example,
        "extracted_data": analysis.get("full_analysis", ""),
        "compliance_result": state.get("compliance_analysis", ""),
        "requirements": requirements,
        "compliance_checks": compliance_checks,
        "structure": structure,
        "previously_drafted": previously_drafted,
    }
    try:
        draft = await asyncio.to_thread(writer.draft_section, section, ctx, None)
        if not drafts:
            state["drafts"] = [draft]
        else:
            state["drafts"] = list(drafts) + [draft]
        preview = (getattr(draft, "content", "") or "")[:300] + ("..." if len(getattr(draft, "content", "") or "") > 300 else "")
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
    """Export credit pack to DOCX. Call after at least one section drafted."""
    state = _state(tool_context)
    structure = state.get("structure") or []
    drafts = state.get("drafts") or []
    if not structure or not drafts:
        return {"status": "error", "message": "No structure or drafts in state. Generate structure and draft at least one section first."}
    parts = []
    draft_by_name = {getattr(d, "name", ""): d for d in drafts if getattr(d, "name", None)}
    for sec in structure:
        name = sec.get("name", "")
        d = draft_by_name.get(name)
        if d is None:
            continue
        content = getattr(d, "content", "") or ""
        if content:
            parts.append("# " + name + "\n\n" + content)
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
        if not filename or not filename.strip():
            filename = config.PRODUCT_NAME.replace(" ", "_") + "_" + datetime.now().strftime("%Y%m%d_%H%M") + ".docx"
        elif not filename.lower().endswith(".docx"):
            filename = filename.rstrip() + ".docx"
        path = export_docx.generate_docx(final_document, filename.strip(), metadata)
        if path:
            return {"status": "success", "path": path, "message": f"Credit pack exported to {path}"}
        return {"status": "error", "message": "DOCX generation failed."}
    except Exception as e:
        logger.exception("export_credit_pack failed")
        return {"status": "error", "message": str(e)}
