"""
Root-level tools for Credit Pack (ADK Samples style).

Phase 1: Stubs that use tool_context.state. Phase 2 will delegate to sub-agents
(AgentTool) or existing ProcessAnalyst/ComplianceAdvisor/Writer.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_fallback_state: dict[str, Any] = {}


def _state(tool_context: Any) -> dict:
    if tool_context is not None and hasattr(tool_context, "state"):
        return tool_context.state
    return _fallback_state


async def set_teaser(teaser_text: str, tool_context: Any = None) -> dict[str, Any]:
    """Store the user's teaser text in state. Call when the user pastes or uploads a teaser."""
    s = _state(tool_context)
    s["teaser_text"] = (teaser_text or "").strip()
    return {"status": "success", "message": "Teaser stored. Call analyze_deal next."}


async def set_example(example_text: str, tool_context: Any = None) -> dict[str, Any]:
    """Store example credit pack text for structure and style."""
    s = _state(tool_context)
    s["example_text"] = (example_text or "").strip()
    return {"status": "success", "message": "Example stored for structure and drafting."}


async def analyze_deal(teaser_text: str = "", tool_context: Any = None) -> dict[str, Any]:
    """Run deal analysis. Pass teaser_text or use stored state. Result stored in state."""
    s = _state(tool_context)
    text = (teaser_text or "").strip() or (s.get("teaser_text") or "").strip()
    if not text:
        return {"status": "error", "message": "No teaser. Use set_teaser first or pass teaser_text."}
    # Phase 2: delegate to ProcessAnalyst sub-agent or existing analyst
    return {"status": "ok", "message": "Phase 2: will run ProcessAnalyst; state ready.", "thinking": "Stub."}


async def discover_requirements(analysis_text: str = "", tool_context: Any = None) -> dict[str, Any]:
    """Discover requirements from analysis. Use after analyze_deal."""
    s = _state(tool_context)
    if not s.get("analysis") and not analysis_text:
        return {"status": "error", "message": "Run analyze_deal first."}
    return {"status": "ok", "message": "Phase 2: will run requirements discovery."}


async def check_compliance(requirements_json: str = "", tool_context: Any = None) -> dict[str, Any]:
    """Check compliance. Use after discover_requirements."""
    s = _state(tool_context)
    if not s.get("requirements"):
        return {"status": "error", "message": "Run discover_requirements first."}
    return {"status": "ok", "message": "Phase 2: will run ComplianceAdvisor."}


async def generate_structure(example_text: str = "", tool_context: Any = None) -> dict[str, Any]:
    """Generate document section list. Use after analyze_deal."""
    s = _state(tool_context)
    if not s.get("analysis"):
        return {"status": "error", "message": "Run analyze_deal first."}
    return {"status": "ok", "message": "Phase 2: will run structure generation."}


async def draft_section(section_name: str, tool_context: Any = None) -> dict[str, Any]:
    """Draft one section. Use after generate_structure."""
    s = _state(tool_context)
    if not s.get("structure"):
        return {"status": "error", "message": "Run generate_structure first."}
    return {"status": "ok", "message": f"Phase 2: will draft section '{section_name}'."}


async def export_credit_pack(filename: str = "", tool_context: Any = None) -> dict[str, Any]:
    """Export credit pack to DOCX. Use after at least one section drafted."""
    s = _state(tool_context)
    if not s.get("drafts"):
        return {"status": "error", "message": "Draft at least one section first."}
    return {"status": "ok", "message": "Phase 2: will export DOCX."}
