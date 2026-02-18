"""Compliance assessment. Self-contained."""

import json
import logging
import re
from typing import Any

from . import llm

logger = logging.getLogger(__name__)

COMPLIANCE_PROMPT = """Assess compliance. Return analysis then JSON array:
<CHECKS>
[{"requirement_id": "...", "status": "PASS|REVIEW|FAIL", "comment": "..."}]
</CHECKS>

Requirements: {requirements}
Teaser excerpt: {teaser_excerpt}
Analysis excerpt: {analysis_excerpt}
"""


def assess_compliance(requirements: list, teaser: str, analysis_text: str, on_stream: bool = False) -> tuple[str, list]:
    """Returns (analysis_paragraph, list of check dicts)."""
    req_str = json.dumps(requirements, indent=2)[:6000]
    prompt = COMPLIANCE_PROMPT.format(
        requirements=req_str,
        teaser_excerpt=(teaser or "")[:2000],
        analysis_excerpt=(analysis_text or "")[:4000],
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
