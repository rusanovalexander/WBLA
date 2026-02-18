"""Compliance assessment. Uses governance (compliance framework, risk taxonomy)."""

import json
import logging
import re
from typing import Any

from . import llm
from . import governance

logger = logging.getLogger(__name__)

COMPLIANCE_PROMPT = """Assess compliance using the institution's framework where provided.

{governance_hint}

Return analysis then JSON array:
<CHECKS>
[{{"requirement_id": "...", "status": "PASS|REVIEW|FAIL", "comment": "..."}}]
</CHECKS>

Requirements: {requirements}
Teaser excerpt: {teaser_excerpt}
Analysis excerpt: {analysis_excerpt}
"""


def _governance_hint() -> str:
    ctx = governance.get_governance_context()
    parts = []
    if ctx.get("compliance_framework"):
        parts.append("Compliance framework: " + ", ".join(ctx["compliance_framework"][:15]))
    if ctx.get("risk_taxonomy"):
        parts.append("Risk taxonomy: " + ", ".join(ctx["risk_taxonomy"][:15]))
    return "\n".join(parts) if parts else ""


def assess_compliance(requirements: list, teaser: str, analysis_text: str, on_stream: bool = False) -> tuple[str, list]:
    """Returns (analysis_paragraph, list of check dicts). Uses governance context."""
    req_str = json.dumps(requirements, indent=2)[:6000]
    prompt = COMPLIANCE_PROMPT.format(
        requirements=req_str,
        teaser_excerpt=(teaser or "")[:2000],
        analysis_excerpt=(analysis_text or "")[:4000],
        governance_hint=_governance_hint() or "(No governance hint)",
    )
    text = llm.generate(prompt, max_tokens=4000)
    checks = []
    m = re.search(r"<CHECKS>\s*([\s\S]*?)\s*</CHECKS>", text, re.IGNORECASE)
    if m:
        try:
            checks = json.loads(m.group(1).strip())
            if not isinstance(checks, list):
                checks = []
        except json.JSONDecodeError:
            pass
    return (text.strip(), checks)
