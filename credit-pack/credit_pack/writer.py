"""Structure generation and section drafting. Self-contained."""

import json
import logging
import re
from typing import Any

from . import llm

logger = logging.getLogger(__name__)


def generate_structure(
    example_text: str,
    assessment_approach: str,
    origination_method: str,
    full_analysis: str,
) -> list[dict[str, Any]]:
    """Return list of section dicts with at least 'name'."""
    prompt = f"""Generate the list of sections for a credit pack document as JSON.
Assessment: {assessment_approach}. Origination: {origination_method}
Output only a JSON array of objects with "name" and optional "description", e.g.:
[{{"name": "Executive Summary", "description": "..."}}, ...]

Analysis excerpt:
{full_analysis[:6000]}
"""
    text = llm.generate(prompt, max_tokens=4000)
    try:
        m = re.search(r"\[[\s\S]*\]", text)
        if m:
            arr = json.loads(m.group(0))
            if isinstance(arr, list):
                return [{"name": x.get("name", "Section"), "description": x.get("description", "")} for x in arr if isinstance(x, dict)]
    except json.JSONDecodeError:
        pass
    return [
        {"name": "Executive Summary", "description": ""},
        {"name": "Transaction Overview", "description": ""},
        {"name": "Credit Analysis", "description": ""},
    ]


def draft_section(
    section: dict[str, Any],
    context: dict[str, Any],
    on_stream: Any = None,
) -> Any:
    """Draft one section. Returns object with .name and .content."""
    name = section.get("name", "Section")
    prompt = f"""Write the section "{name}" for a credit pack document.

Context:
- Teaser: {str(context.get('teaser_text', ''))[:1500]}
- Requirements: {str(context.get('requirements', []))[:2000]}
- Compliance: {str(context.get('compliance_result', ''))[:1500]}
- Previously drafted sections: {str(context.get('previously_drafted', ''))[:2000]}

Write professional, concise content for this section only. Use markdown if helpful.
"""
    content = llm.generate(prompt, max_tokens=4000)
    return _Section(name=name, content=content or "")


class _Section:
    def __init__(self, name: str, content: str):
        self.name = name
        self.content = content
