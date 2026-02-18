"""Deal analysis and requirements discovery. Self-contained."""

import json
import logging
import re
from typing import Any, Callable

from . import rag
from . import llm

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """You are a credit process analyst. Analyze the following deal teaser and determine:
1. Assessment approach (process path)
2. Origination method

Output your full analysis, then at the end a JSON block:
<RESULT_JSON>
{"assessment_approach": "...", "origination_method": "...", "assessment_reasoning": "...", "origination_reasoning": "..."}
</RESULT_JSON>

TEASER:
{teaser}
"""

REQUIREMENTS_PROMPT = """List dynamic requirements for this credit pack as JSON.
Output only: { "requirements": [ { "id": "...", "label": "...", "value": "...", "status": "filled" or "empty" } ] }

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


def analyze_deal(teaser_text: str, use_native_tools: bool = True, on_stream: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Full deal analysis."""
    procedure_ctx = rag.search_procedure("assessment approach origination", 3)
    prompt = ANALYSIS_PROMPT.format(teaser=teaser_text)
    if procedure_ctx:
        prompt = "Procedure context:\n" + procedure_ctx + "\n\n" + prompt
    answer, thinking = llm.generate_with_thinking(prompt, max_tokens=16000)
    decision = _extract_json(answer) or _extract_json(teaser_text[:5000] + "\n" + answer)
    result = {"full_analysis": answer, "process_path": "", "origination_method": "", "llm_thinking": thinking}
    if decision:
        result["process_path"] = decision.get("assessment_approach") or ""
        result["origination_method"] = decision.get("origination_method") or ""
    return result


def discover_requirements(analysis_text: str, assessment_approach: str, origination_method: str) -> list[dict[str, Any]]:
    """Discover requirements list."""
    prompt = REQUIREMENTS_PROMPT.format(
        analysis_text=analysis_text[:12000],
        assessment_approach=assessment_approach or "Standard",
        origination_method=origination_method or "Bilateral",
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
