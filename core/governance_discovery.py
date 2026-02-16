"""
Governance Discovery Module — Credit Pack Multi-Agent PoC v3.2.

Runs at startup to RAG-query the Procedure & Guidelines documents,
discovers the institution's specific terminology, categories,
compliance framework, and section structures, then caches the
results for injection into all agent prompts.

This makes the system document-driven: prompts adapt to whatever
governance framework is loaded, without code changes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable

from core.llm_client import call_llm
from core.parsers import format_rag_results, safe_extract_json
from config.settings import MODEL_PRO

logger = logging.getLogger(__name__)


# =============================================================================
# Discovery Queries — intentionally broad to work with any governance docs
# =============================================================================

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


# =============================================================================
# Extraction Prompt
# =============================================================================

GOVERNANCE_EXTRACTION_PROMPT = """You are analysing governance documents for an institution.
From the excerpts below, extract the institution's specific framework.

## PROCEDURE DOCUMENT EXCERPTS
{procedure_excerpts}

## GUIDELINES DOCUMENT EXCERPTS
{guidelines_excerpts}

## TASK

Extract the following from the excerpts above. Only include items that are
explicitly mentioned or clearly implied. Do NOT invent items.

1. **requirement_categories** — What categories of information does the Procedure
   say must be collected? (e.g., "Category A", "Category B", etc. — use exact
   names from the document)

2. **compliance_framework** — What categories of compliance criteria does the
   Guidelines document define? (e.g., "Criteria Group 1", "Criteria Group 2",
   etc. — use exact names from the document)

3. **section_templates** — For each origination method mentioned, what sections
   does the Procedure say must be included in the output document?
   Format: {{"method_name": [{{"name": "Section Name", "description": "..."}}]}}

4. **risk_taxonomy** — What risk categories does the governance framework use?
   (use exact category names from the document)

5. **deal_taxonomy** — What classification dimensions are used?
   Format: {{"dimension_name": ["value1", "value2", ...], ...}}
   (use exact dimension names and values from the document)

6. **terminology_map** — Key domain terms and their synonyms used in the documents.
   Format: {{"term": ["synonym1", "synonym2"]}}

7. **search_vocabulary** — Key terms and phrases that appear frequently in the
   documents, useful for future searches.

## OUTPUT FORMAT

Output ONLY valid JSON between <json_output></json_output> tags:

<json_output>
{{
  "requirement_categories": ["category1", "category2"],
  "compliance_framework": ["criteria1", "criteria2"],
  "section_templates": {{}},
  "risk_taxonomy": ["risk1", "risk2"],
  "deal_taxonomy": {{}},
  "terminology_map": {{}},
  "search_vocabulary": ["term1", "term2"]
}}
</json_output>

IMPORTANT:
- Only extract what is ACTUALLY in the document excerpts
- If a category has no data in the excerpts, return an empty list/dict for it
- Do NOT make up categories, criteria, or terms not found in the excerpts
- Output ONLY the JSON between the XML tags, nothing else
"""


# =============================================================================
# Main Discovery Function
# =============================================================================

def run_governance_discovery(
    search_procedure_fn: Callable | None = None,
    search_guidelines_fn: Callable | None = None,
    tracer: Any = None,
) -> dict[str, Any]:
    """
    Discover governance context by RAG-querying Procedure & Guidelines.

    Returns a dict matching GovernanceContext schema. All fields default
    to empty — consumers fall back to current behavior when empty.

    Args:
        search_procedure_fn: Callable(query, num_results) -> dict with RAG results
        search_guidelines_fn: Callable(query, num_results) -> dict with RAG results
        tracer: TraceStore instance for observability

    Returns:
        Dict with governance context (discovery_status: complete|partial|failed)
    """
    if tracer:
        tracer.record("GovernanceDiscovery", "START", "Discovering governance framework from documents")

    context: dict[str, Any] = {
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

    # -------------------------------------------------------------------
    # Step 1: RAG-query the Procedure document
    # -------------------------------------------------------------------
    procedure_results: dict[str, Any] = {}
    if search_procedure_fn:
        for query in PROCEDURE_QUERIES:
            try:
                if tracer:
                    tracer.record("GovernanceDiscovery", "RAG_SEARCH", f"Procedure: {query[:60]}")
                result = search_procedure_fn(query, 4)
                procedure_results[query] = result
            except Exception as e:
                logger.warning("Procedure query failed for '%s': %s", query, e)
                procedure_results[query] = {"status": "ERROR", "results": []}

    # -------------------------------------------------------------------
    # Step 2: RAG-query the Guidelines document
    # -------------------------------------------------------------------
    guidelines_results: dict[str, Any] = {}
    if search_guidelines_fn:
        for query in GUIDELINES_QUERIES:
            try:
                if tracer:
                    tracer.record("GovernanceDiscovery", "RAG_SEARCH", f"Guidelines: {query[:60]}")
                result = search_guidelines_fn(query, 4)
                guidelines_results[query] = result
            except Exception as e:
                logger.warning("Guidelines query failed for '%s': %s", query, e)
                guidelines_results[query] = {"status": "ERROR", "results": []}

    # Cache raw excerpts
    procedure_text = format_rag_results(procedure_results)
    guidelines_text = format_rag_results(guidelines_results)
    context["raw_procedure_excerpts"] = {
        q: _extract_text_from_result(r) for q, r in procedure_results.items()
    }
    context["raw_guidelines_excerpts"] = {
        q: _extract_text_from_result(r) for q, r in guidelines_results.items()
    }

    # Diagnostic: log per-query status
    for query, result in procedure_results.items():
        status = result.get("status", "UNKNOWN") if isinstance(result, dict) else "BAD_TYPE"
        n_results = len(result.get("results", [])) if isinstance(result, dict) else 0
        has_content = any(
            r.get("content") and len(r["content"]) > 20
            for r in (result.get("results", []) if isinstance(result, dict) else [])
        )
        logger.info(
            "GovernanceDiscovery PROCEDURE query='%s' → status=%s, results=%d, has_content=%s",
            query[:60], status, n_results, has_content
        )

    for query, result in guidelines_results.items():
        status = result.get("status", "UNKNOWN") if isinstance(result, dict) else "BAD_TYPE"
        n_results = len(result.get("results", [])) if isinstance(result, dict) else 0
        has_content = any(
            r.get("content") and len(r["content"]) > 20
            for r in (result.get("results", []) if isinstance(result, dict) else [])
        )
        logger.info(
            "GovernanceDiscovery GUIDELINES query='%s' → status=%s, results=%d, has_content=%s",
            query[:60], status, n_results, has_content
        )

    # Check if we got any content at all
    has_procedure = procedure_text and procedure_text != "(No RAG results)"
    has_guidelines = guidelines_text and guidelines_text != "(No RAG results)"

    if not has_procedure and not has_guidelines:
        logger.warning("Governance discovery: no RAG results from either document")
        if tracer:
            tracer.record("GovernanceDiscovery", "FAILED", "No RAG results from either document")
        context["discovery_status"] = "failed"
        return context

    # -------------------------------------------------------------------
    # Step 3: LLM extraction — one call to structure everything
    # -------------------------------------------------------------------
    prompt = GOVERNANCE_EXTRACTION_PROMPT.format(
        procedure_excerpts=procedure_text[:8000] if has_procedure else "(No Procedure excerpts available)",
        guidelines_excerpts=guidelines_text[:8000] if has_guidelines else "(No Guidelines excerpts available)",
    )

    if tracer:
        tracer.record("GovernanceDiscovery", "LLM_CALL", "Extracting structured governance context")

    result = call_llm(prompt, MODEL_PRO, 0.0, 6000, "GovernanceDiscovery", tracer)

    if not result.success:
        logger.warning("Governance extraction LLM call failed: %s", result.error)
        if tracer:
            tracer.record("GovernanceDiscovery", "LLM_FAIL", f"LLM call failed: {result.error}")
        context["discovery_status"] = "partial" if (has_procedure or has_guidelines) else "failed"
        return context

    # -------------------------------------------------------------------
    # Step 4: Parse and populate context
    # -------------------------------------------------------------------
    parsed = safe_extract_json(result.text, "object")

    if not parsed:
        logger.warning("Governance extraction: could not parse LLM output as JSON")
        if tracer:
            tracer.record("GovernanceDiscovery", "PARSE_FAIL", "Could not parse extraction result")
        context["discovery_status"] = "partial"
        return context

    # Populate context from parsed result (with type safety)
    context["requirement_categories"] = _ensure_list(parsed.get("requirement_categories"))
    context["compliance_framework"] = _ensure_list(parsed.get("compliance_framework"))
    context["section_templates"] = _ensure_dict(parsed.get("section_templates"))
    context["risk_taxonomy"] = _ensure_list(parsed.get("risk_taxonomy"))
    context["deal_taxonomy"] = _ensure_dict(parsed.get("deal_taxonomy"))
    context["terminology_map"] = _ensure_dict(parsed.get("terminology_map"))
    context["search_vocabulary"] = _ensure_list(parsed.get("search_vocabulary"))

    # Determine completeness
    populated_fields = sum(1 for k in [
        "requirement_categories", "compliance_framework", "risk_taxonomy",
        "deal_taxonomy", "search_vocabulary",
    ] if context.get(k))

    if populated_fields >= 3:
        context["discovery_status"] = "complete"
    elif populated_fields >= 1:
        context["discovery_status"] = "partial"
    else:
        context["discovery_status"] = "failed"

    if tracer:
        tracer.record(
            "GovernanceDiscovery", "COMPLETE",
            f"Discovered: {len(context['requirement_categories'])} categories, "
            f"{len(context['compliance_framework'])} compliance criteria, "
            f"{len(context['risk_taxonomy'])} risk categories, "
            f"status={context['discovery_status']}"
        )

    logger.info(
        "Governance discovery %s: %d categories, %d compliance, %d risk, %d vocab",
        context["discovery_status"],
        len(context["requirement_categories"]),
        len(context["compliance_framework"]),
        len(context["risk_taxonomy"]),
        len(context["search_vocabulary"]),
    )

    return context


# =============================================================================
# Terminology Synonyms Helper (used by UI prompts — M15)
# =============================================================================

def get_terminology_synonyms(governance_context: dict | None = None) -> str:
    """
    Return synonym mapping string for use in extraction prompts.

    If governance context has a terminology_map, use it.
    Otherwise return sensible defaults.
    """
    if governance_context and governance_context.get("terminology_map"):
        lines = []
        for term, synonyms in governance_context["terminology_map"].items():
            if isinstance(synonyms, list) and synonyms:
                syn_str = " = ".join(f'"{s}"' for s in synonyms)
                lines.append(f'   - "{term}" = {syn_str}')
        if lines:
            return "\n".join(lines)

    # No hardcoded synonyms — governance discovery provides domain-specific terms
    # The LLM will use its own semantic understanding for synonym matching
    return ""


# =============================================================================
# Internal Helpers
# =============================================================================

def _extract_text_from_result(result: dict[str, Any]) -> str:
    """Extract concatenated text content from a single RAG result."""
    if not isinstance(result, dict) or result.get("status") != "OK":
        return ""
    parts = []
    for r in result.get("results", []):
        content = r.get("content", "")
        if content:
            parts.append(content[:2000])
    return "\n".join(parts)


def _ensure_list(val: Any) -> list:
    """Safely coerce to list."""
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        return [val]
    return []


def _ensure_dict(val: Any) -> dict:
    """Safely coerce to dict."""
    if isinstance(val, dict):
        return val
    return {}
