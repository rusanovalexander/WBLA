"""Format RAG results and safe JSON extraction. No external schema deps."""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def format_rag_results(rag_results: dict[str, Any]) -> str:
    """Format RAG search results for inclusion in prompts."""
    if not rag_results:
        return "(No RAG results)"
    formatted = []
    for query, result in rag_results.items():
        if not isinstance(result, dict):
            continue
        if result.get("status") != "OK":
            formatted.append(f'\n### Query: "{query}"\n(No results found)')
            continue
        formatted.append(f'\n### Query: "{query}"\n')
        for r in result.get("results", [])[:3]:
            doc_type = r.get("doc_type", "Document")
            title = r.get("title", "Untitled")
            content = (r.get("content") or "")[:1500]
            formatted.append(f"**[{doc_type}] {title}**\n{content}\n")
    return "\n".join(formatted) if formatted else "(No results)"


def _try_parse_json(s: str) -> Any:
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


def safe_extract_json(text: str, expect_type: str = "object") -> Any:
    """Extract JSON from LLM output (XML tags, markdown fences, etc.)."""
    if not text or not isinstance(text, str):
        return None
    cleaned = text.strip()
    m = re.search(r"<json_output>\s*([\s\S]*?)\s*</json_output>", cleaned, re.IGNORECASE)
    if m:
        cleaned = m.group(1).strip()
    cleaned = re.sub(r"```\s*(?:json|JSON)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?\s*```\s*$", "", cleaned).strip()
    start_char, end_char = ("[", "]") if expect_type == "array" else ("{", "}")
    start = cleaned.find(start_char)
    if start < 0:
        return None
    end = cleaned.rfind(end_char)
    if end > start:
        out = _try_parse_json(cleaned[start : end + 1])
        if out is not None:
            return out
    return _try_parse_json(cleaned[start:])
