"""Deal analysis and requirements discovery. Uses RAG (procedure) and governance."""

import json
import logging
import re
from typing import Any, Callable

from . import rag
from . import llm
from . import governance

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """You are a credit process analyst. Analyze the following deal teaser and determine:
1. Assessment approach (process path)
2. Origination method

Use the procedure context below to align with the institution's framework where relevant.

{procedure_context}

Output your full analysis, then at the end a JSON block:
<RESULT_JSON>
{{"assessment_approach": "...", "origination_method": "...", "assessment_reasoning": "...", "origination_reasoning": "..."}}
</RESULT_JSON>

TEASER:
{teaser}
"""

REQUIREMENTS_PROMPT = """List dynamic requirements for this credit pack as JSON.
Use the institution's requirement categories and vocabulary where provided below.

{governance_hint}

Output only: {{ "requirements": [ {{ "id": "...", "label": "...", "value": "...", "status": "filled" or "empty" }} ] }}

Assessment: {assessment_approach}, Origination: {origination_method}

ANALYSIS:
{analysis_text}
"""


def _extract_json(text: str) -> dict | None:
    m = re.search(r"<RESULT_JSON>\s*([\s\S]*?)\s*</RESULT_JSON>", text, re.IGNORECASE)
    if not m:
        return None
    try:
        return json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return None


def _procedure_context_for_prompt() -> str:
    r = rag.search_procedure("assessment approach origination decision criteria", 4)
    if r.get("status") != "OK" or not r.get("results"):
        return ""
    return "\n\n".join((x.get("content") or "")[:2000] for x in r["results"] if x.get("content"))


def analyze_deal(teaser_text: str, use_native_tools: bool = True, on_stream: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Full deal analysis. Uses procedure RAG and governance."""
    procedure_context = _procedure_context_for_prompt()
    prompt = ANALYSIS_PROMPT.format(
        teaser=teaser_text,
        procedure_context=procedure_context or "(No procedure context available)",
    )
    answer, thinking = llm.generate_with_thinking(prompt, max_tokens=16000)
    decision = _extract_json(answer) or _extract_json(teaser_text[:5000] + "\n" + answer)
    result = {"full_analysis": answer, "process_path": "", "origination_method": "", "llm_thinking": thinking}
    if decision:
        result["process_path"] = decision.get("assessment_approach") or ""
        result["origination_method"] = decision.get("origination_method") or ""
    return result


def _governance_hint() -> str:
    ctx = governance.get_governance_context()
    parts = []
    if ctx.get("requirement_categories"):
        parts.append("Requirement categories: " + ", ".join(ctx["requirement_categories"][:15]))
    if ctx.get("search_vocabulary"):
        parts.append("Vocabulary: " + ", ".join(ctx["search_vocabulary"][:20]))
    return "\n".join(parts) if parts else ""


def discover_requirements(analysis_text: str, assessment_approach: str, origination_method: str) -> list[dict[str, Any]]:
    """Discover requirements list. Uses governance context."""
    hint = _governance_hint()
    prompt = REQUIREMENTS_PROMPT.format(
        analysis_text=analysis_text[:12000],
        assessment_approach=assessment_approach or "Standard",
        origination_method=origination_method or "Bilateral",
        governance_hint=hint or "(No governance hint)",
    )
    text = llm.generate(prompt, max_tokens=8000)
    try:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            parsed = json.loads(m.group(0))
            reqs = parsed.get("requirements", []) if isinstance(parsed, dict) else []
            if isinstance(reqs, list):
                out = []
                for r in reqs:
                    if isinstance(r, dict):
                        out.append({
                            "id": r.get("id", ""),
                            "label": r.get("label", ""),
                            "value": r.get("value", ""),
                            "status": "filled" if (r.get("value") or "").strip() else "empty",
                        })
                return out
    except json.JSONDecodeError:
        pass
    return []
