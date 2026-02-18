"""
Governance discovery: RAG-query Procedure & Guidelines, then LLM extraction.
Caches result for use by analyst, compliance, and writer.
"""

import logging
from datetime import datetime
from typing import Any, Callable

from . import llm
from . import rag
from . import parsers

logger = logging.getLogger(__name__)

PROCEDURE_QUERIES = [
    "information requirements assessment methods origination",
    "required sections content structure output document",
    "assessment approach types available decision criteria",
    "origination methods types available when each applies",
    "classification categories types dimensions taxonomy",
]
GUIDELINES_QUERIES = [
    "compliance criteria categories requirements",
    "risk categories risk assessment framework appetite",
    "financial ratio requirements thresholds limits covenants",
    "security collateral requirements structural provisions",
]

GOVERNANCE_EXTRACTION_PROMPT = """You are analysing governance documents for an institution.
From the excerpts below, extract the institution's specific framework.

## PROCEDURE DOCUMENT EXCERPTS
{procedure_excerpts}

## GUIDELINES DOCUMENT EXCERPTS
{guidelines_excerpts}

## TASK
Extract the following. Only include items explicitly mentioned or clearly implied. Do NOT invent.

1. **requirement_categories** — Categories of information the Procedure says must be collected (exact names).
2. **compliance_framework** — Compliance criteria categories from Guidelines (exact names).
3. **section_templates** — For each origination method, sections required. Format: {{"method_name": [{{"name": "...", "description": "..."}}]}}
4. **risk_taxonomy** — Risk categories used.
5. **deal_taxonomy** — Classification dimensions. Format: {{"dimension_name": ["value1", ...]}}
6. **terminology_map** — Key terms and synonyms. Format: {{"term": ["synonym1", ...]}}
7. **search_vocabulary** — Key terms for future searches.

Output ONLY valid JSON between <json_output></json_output>:

<json_output>
{{
  "requirement_categories": [],
  "compliance_framework": [],
  "section_templates": {{}},
  "risk_taxonomy": [],
  "deal_taxonomy": {{}},
  "terminology_map": {{}},
  "search_vocabulary": []
}}
</json_output>
"""

_cached_context: dict[str, Any] | None = None


def _ensure_list(val: Any) -> list:
    return val if isinstance(val, list) else [val] if isinstance(val, str) else []


def _ensure_dict(val: Any) -> dict:
    return val if isinstance(val, dict) else {}


def _extract_text_from_result(result: dict) -> str:
    if not isinstance(result, dict) or result.get("status") != "OK":
        return ""
    return "\n".join((r.get("content") or "")[:2000] for r in result.get("results", []) if r.get("content"))


def run_governance_discovery(
    search_procedure_fn: Callable[[str, int], dict] | None = None,
    search_guidelines_fn: Callable[[str, int], dict] | None = None,
    tracer: Any = None,
) -> dict[str, Any]:
    """
    RAG-query Procedure & Guidelines, then LLM extraction. Returns governance context.
    Uses credit_pack.rag by default if no functions provided.
    """
    global _cached_context
    if _cached_context is not None:
        return _cached_context

    search_procedure_fn = search_procedure_fn or (lambda q, n: rag.search_procedure(q, n))
    search_guidelines_fn = search_guidelines_fn or (lambda q, n: rag.search_guidelines(q, n))

    context = {
        "requirement_categories": [],
        "compliance_framework": [],
        "section_templates": {},
        "risk_taxonomy": [],
        "deal_taxonomy": {},
        "terminology_map": {},
        "search_vocabulary": [],
        "raw_procedure_excerpts": {},
        "raw_guidelines_excerpts": {},
        "discovery_timestamp": datetime.now().isoformat(),
        "discovery_status": "pending",
    }

    procedure_results = {}
    for query in PROCEDURE_QUERIES:
        try:
            procedure_results[query] = search_procedure_fn(query, 4)
        except Exception as e:
            logger.warning("Procedure query failed %s: %s", query[:40], e)
            procedure_results[query] = {"status": "ERROR", "results": []}

    guidelines_results = {}
    for query in GUIDELINES_QUERIES:
        try:
            guidelines_results[query] = search_guidelines_fn(query, 4)
        except Exception as e:
            logger.warning("Guidelines query failed %s: %s", query[:40], e)
            guidelines_results[query] = {"status": "ERROR", "results": []}

    procedure_text = parsers.format_rag_results(procedure_results)
    guidelines_text = parsers.format_rag_results(guidelines_results)
    context["raw_procedure_excerpts"] = {q: _extract_text_from_result(r) for q, r in procedure_results.items()}
    context["raw_guidelines_excerpts"] = {q: _extract_text_from_result(r) for q, r in guidelines_results.items()}

    has_procedure = procedure_text and procedure_text != "(No RAG results)"
    has_guidelines = guidelines_text and guidelines_text != "(No RAG results)"
    if not has_procedure and not has_guidelines:
        logger.warning("Governance discovery: no RAG results")
        context["discovery_status"] = "failed"
        _cached_context = context
        return context

    prompt = GOVERNANCE_EXTRACTION_PROMPT.format(
        procedure_excerpts=(procedure_text[:8000] if has_procedure else "(No Procedure excerpts)"),
        guidelines_excerpts=(guidelines_text[:8000] if has_guidelines else "(No Guidelines excerpts)"),
    )
    text = llm.generate(prompt, max_tokens=6000)
    parsed = parsers.safe_extract_json(text, "object")
    if not parsed:
        logger.warning("Governance extraction: could not parse JSON")
        context["discovery_status"] = "partial"
        _cached_context = context
        return context

    context["requirement_categories"] = _ensure_list(parsed.get("requirement_categories"))
    context["compliance_framework"] = _ensure_list(parsed.get("compliance_framework"))
    context["section_templates"] = _ensure_dict(parsed.get("section_templates"))
    context["risk_taxonomy"] = _ensure_list(parsed.get("risk_taxonomy"))
    context["deal_taxonomy"] = _ensure_dict(parsed.get("deal_taxonomy"))
    context["terminology_map"] = _ensure_dict(parsed.get("terminology_map"))
    context["search_vocabulary"] = _ensure_list(parsed.get("search_vocabulary"))

    n = sum(1 for k in ("requirement_categories", "compliance_framework", "risk_taxonomy", "deal_taxonomy", "search_vocabulary") if context.get(k))
    context["discovery_status"] = "complete" if n >= 3 else ("partial" if n >= 1 else "failed")
    logger.info("Governance discovery %s: %d categories, %d compliance, %d risk",
                context["discovery_status"], len(context["requirement_categories"]), len(context["compliance_framework"]), len(context["risk_taxonomy"]))
    _cached_context = context
    return context


def get_governance_context() -> dict[str, Any]:
    """Return cached governance context, running discovery if needed."""
    return run_governance_discovery()
