"""
Agent Orchestration for Credit Pack PoC v3.2 — AUTONOMY FIXED.

All hardcoded fallbacks replaced with:
- Structured JSON extraction via dedicated extraction calls
- Visible fallback warnings (never silent)
- Dynamic compliance criteria (agent decides what to check)
- Orchestrator routing decisions that actually affect workflow

Changes from previous version:
- Removed hardcoded RAG query injection
- Removed 7-criteria hardcoded compliance parser
- Added structured extraction step after each analysis
- Orchestrator returns actionable routing decisions
- All fallbacks are visible in trace and UI
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from config.settings import MODEL_PRO, MODEL_FLASH, AGENT_MODELS, PRODUCT_NAME, THINKING_BUDGET_NONE, THINKING_BUDGET_LIGHT, THINKING_BUDGET_STANDARD
from core.llm_client import call_llm, call_llm_with_tools, call_llm_streaming, require_success
from core.tracing import TraceStore, get_tracer
from core.parsers import (
    parse_tool_calls,
    parse_agent_queries,
    format_rag_results,
    format_requirements_for_context,
    safe_extract_json,
)
from models.schemas import (
    LLMCallResult,
    OrchestratorInsights,
    ProcessDecision,
    ProcessDecisionEvidence,
    ComplianceCheck,
    RiskFlag,
    RiskSeverity,
    SectionDraft,
    AgentMessage,
)
from agents.orchestrator import ORCHESTRATOR_INSTRUCTION, get_orchestrator_instruction
from agents.process_analyst import PROCESS_ANALYST_INSTRUCTION, get_process_analyst_instruction
from agents.compliance_advisor import COMPLIANCE_ADVISOR_INSTRUCTION, get_compliance_advisor_instruction
from agents.writer import WRITER_INSTRUCTION, get_writer_instruction

logger = logging.getLogger(__name__)


# =============================================================================
# Structured Decision Extraction (replaces keyword parsing)
# =============================================================================

PROCESS_DECISION_EXTRACTION_PROMPT = """You are a JSON extraction assistant. Extract the process path decision from the analysis below.

## ANALYSIS TEXT
{analysis_text}

## TASK
Extract the agent's decision into EXACTLY this JSON format. Use ONLY what the agent explicitly stated.

CRITICAL FORMATTING RULES:
- You MUST output ONLY valid JSON with NO text before or after
- Do NOT include markdown code fences like ```json
- Do NOT include explanations, preambles, or any other text
- Output ONLY the JSON object between the <json_output></json_output> tags below

<json_output>
{{
  "assessment_approach": "<exact approach name the agent recommended>",
  "origination_method": "<exact origination method the agent recommended>",
  "assessment_reasoning": "<1-2 sentence summary of WHY this assessment approach>",
  "origination_reasoning": "<1-2 sentence summary of WHY this origination method>",
  "procedure_sections_cited": ["Section X.X", "Section Y.Y"],
  "confidence": "HIGH",
  "decision_found": true
}}
</json_output>

EXTRACTION RULES:
- If the agent did NOT clearly state an assessment approach, set "decision_found": false
- Do NOT invent or assume an approach — only use what the agent explicitly recommended
- Copy the agent's EXACT wording for the approach and method names
- confidence must be exactly one of: "HIGH", "MEDIUM", "LOW"
- decision_found must be exactly: true or false (boolean, not string)

NOW: Extract the decision from the analysis text above. Output ONLY the JSON between <json_output></json_output> tags with NO other text.
"""

COMPLIANCE_EXTRACTION_PROMPT = """Extract ALL compliance checks from the text below into a JSON array. Do NOT think or explain — go straight to the JSON output.

## COMPLIANCE ANALYSIS TEXT
{compliance_text}

## TASK — DIRECT EXTRACTION, NO REASONING

Scan the ENTIRE text above. For every criterion the agent assessed, emit one JSON object.

Look for compliance checks in ALL formats:
- Tables: Criterion | Limit | Value | Status
- Bullets with PASS/FAIL/REVIEW
- Narrative: "meets requirement", "exceeds limit", "compliant", "breaches"
- Emojis: ✅ = PASS, ❌ = FAIL, ⚠️ = REVIEW, ℹ️ = N/A

RULES:
- Output ONLY JSON between <json_output></json_output> tags — NO other text, NO reasoning
- status: exactly "PASS", "FAIL", "REVIEW", or "N/A"
- severity: exactly "MUST" or "SHOULD"
- You MUST extract at least one check if ANY compliance assessment exists in the text
- Only return [] if the text contains absolutely ZERO compliance assessments

<json_output>
[
  {{
    "criterion": "<criterion name>",
    "guideline_limit": "<guideline limit/requirement>",
    "deal_value": "<actual deal value>",
    "status": "PASS",
    "evidence": "<brief reasoning>",
    "reference": "<section ref if available>",
    "severity": "MUST"
  }}
]
</json_output>

NOW: Extract ALL checks. Output ONLY <json_output> tags with JSON array inside.
"""


def _extract_structured_decision(
    analysis_text: str,
    tracer: TraceStore,
) -> dict | None:
    """
    Use a dedicated LLM call to extract structured decision with retry.
    """
    tracer.record("Extraction", "START", "Extracting structured decision")
    
    prompt = PROCESS_DECISION_EXTRACTION_PROMPT.format(
        analysis_text=analysis_text[:12000]
    )
    
    # Try up to 2 times with different temperatures
    for attempt in range(2):
        temperature = 0.0 if attempt == 0 else 0.1

        tracer.record("Extraction", "ATTEMPT", f"Attempt {attempt + 1}/2 (temp={temperature})")

        result = call_llm(prompt, MODEL_FLASH, temperature, 4000, "Extraction", tracer, thinking_budget=THINKING_BUDGET_NONE)
        # AG-H3: Check LLM success before using output
        if not result.success:
            tracer.record("Extraction", "LLM_FAIL", result.error or "Unknown")
            continue
        parsed = safe_extract_json(result.text, "object")

        if parsed and "decision_found" in parsed:
            # AG-H4: Validate through Pydantic if decision found
            if parsed.get("decision_found"):
                try:
                    # Ensure None values get replaced with defaults (LLM sometimes returns None)
                    validated = ProcessDecision.model_validate({
                        "assessment_approach": parsed.get("assessment_approach") or "Unknown",
                        "origination_method": parsed.get("origination_method") or "Unknown",
                        "procedure_section": parsed.get("procedure_section") or "",
                    })
                    parsed["assessment_approach"] = validated.assessment_approach
                    parsed["origination_method"] = validated.origination_method
                except Exception as e:
                    logger.warning("Pydantic validation failed for ProcessDecision: %s", e)
                    tracer.record("Extraction", "VALIDATION_WARN", f"Pydantic validation skipped: {e}")
                tracer.record("Extraction", "SUCCESS", f"Found: {parsed.get('assessment_approach', '?')}")
                return parsed
            else:
                tracer.record("Extraction", "NO_DECISION", "Agent did not make clear decision")
                return parsed

    # Both attempts failed
    tracer.record("Extraction", "FAILED", f"Could not extract after 2 attempts. Output length: {len(result.text)}")
    logger.error("Extraction failed. Last output (first 1000 chars): %s", result.text[:1000])
    return None


def _extract_compliance_checks(
    compliance_text: str,
    tracer: TraceStore,
) -> list[dict]:
    """
    Use a dedicated LLM call to extract compliance checks with retry.

    Strategy:
    1. Try LLM extraction on full text (up to 30k chars) — 3 attempts
    2. If LLM extraction fails, fall back to regex-based table parsing
    """
    tracer.record("Extraction", "START", "Extracting compliance checks")

    # Use more of the compliance text — the checks are often near the end
    text_for_extraction = compliance_text[:30000]
    tracer.record("Extraction", "INPUT_SIZE", f"{len(compliance_text)} chars total, using {len(text_for_extraction)}")

    prompt = COMPLIANCE_EXTRACTION_PROMPT.format(
        compliance_text=text_for_extraction
    )

    # --- Strategy 1: Full-text LLM extraction (3 attempts with increasing tokens) ---
    last_output = ""
    # gemini-2.5-pro uses "thinking" tokens within the budget, so we need generous limits
    token_budgets = [16000, 24000, 32000]
    for attempt in range(3):
        temperature = [0.0, 0.1, 0.2][attempt]
        max_tok = token_budgets[attempt]

        tracer.record("Extraction", "ATTEMPT", f"Attempt {attempt + 1}/3 (temp={temperature}, max_tokens={max_tok})")

        result = call_llm(prompt, MODEL_FLASH, temperature, max_tok, "Extraction", tracer, thinking_budget=THINKING_BUDGET_NONE)
        # AG-H3: Check LLM success before using output
        if not result.success:
            tracer.record("Extraction", "LLM_FAIL", result.error or "Unknown")
            continue
        last_output = result.text
        parsed = safe_extract_json(result.text, "array")

        if parsed is not None and isinstance(parsed, list) and len(parsed) > 0:
            # AG-H4: Validate each check through Pydantic
            validated_checks = []
            for check_data in parsed:
                try:
                    # Pre-process: convert null values to defaults
                    if isinstance(check_data, dict):
                        if check_data.get("reference") is None:
                            check_data["reference"] = ""
                        if check_data.get("severity") is None:
                            check_data["severity"] = "MUST"
                    validated = ComplianceCheck.model_validate(check_data)
                    validated_checks.append(validated.model_dump())
                except Exception as e:
                    logger.warning("Pydantic validation failed for ComplianceCheck: %s", e)
                    # Pre-process before adding raw data
                    if isinstance(check_data, dict):
                        if check_data.get("reference") is None:
                            check_data["reference"] = ""
                        if check_data.get("severity") is None:
                            check_data["severity"] = "MUST"
                    validated_checks.append(check_data)  # Keep raw if validation fails
            tracer.record("Extraction", "SUCCESS", f"Extracted {len(validated_checks)} checks")
            return validated_checks

        # If LLM returned empty array explicitly, try with a shorter text chunk
        # (shorter input = less thinking = more room for actual output)
        if parsed is not None and isinstance(parsed, list) and len(parsed) == 0 and attempt < 2:
            tracer.record("Extraction", "EMPTY_ARRAY", f"LLM returned [] on attempt {attempt + 1}, will retry with more tokens")

    # --- Strategy 2: Chunk-based extraction (last resort before regex) ---
    # If full text failed, try extracting from the LAST portion of the text
    # (compliance matrices / summary tables are typically at the end)
    if len(compliance_text) > 8000:
        tracer.record("Extraction", "CHUNK_FALLBACK", "Trying extraction from last 15k chars only")
        tail_text = compliance_text[-15000:]
        tail_prompt = COMPLIANCE_EXTRACTION_PROMPT.format(compliance_text=tail_text)
        tail_result = call_llm(tail_prompt, MODEL_FLASH, 0.0, 24000, "Extraction", tracer, thinking_budget=THINKING_BUDGET_NONE)
        if tail_result.success:
            last_output = tail_result.text
            tail_parsed = safe_extract_json(tail_result.text, "array")
            if tail_parsed and isinstance(tail_parsed, list) and len(tail_parsed) > 0:
                validated_checks = []
                for check_data in tail_parsed:
                    try:
                        # Pre-process: convert null values to defaults
                        if isinstance(check_data, dict):
                            if check_data.get("reference") is None:
                                check_data["reference"] = ""
                            if check_data.get("severity") is None:
                                check_data["severity"] = "MUST"
                        validated = ComplianceCheck.model_validate(check_data)
                        validated_checks.append(validated.model_dump())
                    except Exception:
                        # Pre-process before adding raw data
                        if isinstance(check_data, dict):
                            if check_data.get("reference") is None:
                                check_data["reference"] = ""
                            if check_data.get("severity") is None:
                                check_data["severity"] = "MUST"
                        validated_checks.append(check_data)
                tracer.record("Extraction", "CHUNK_SUCCESS", f"Tail extraction got {len(validated_checks)} checks")
                return validated_checks

    # --- Strategy 3: Regex fallback on markdown tables ---
    tracer.record("Extraction", "FALLBACK", "LLM extraction failed, trying regex table parse")
    fallback_checks = _regex_extract_compliance_table(compliance_text, tracer)
    if fallback_checks:
        tracer.record("Extraction", "FALLBACK_SUCCESS", f"Regex extracted {len(fallback_checks)} checks")
        return fallback_checks

    # Everything failed
    tracer.record("Extraction", "FAILED", "Could not extract checks after LLM + chunk + regex fallback")
    logger.error("Compliance extraction failed. Last LLM output (first 1000 chars): %s", last_output[:1000])
    return []


def _regex_extract_compliance_table(compliance_text: str, tracer: TraceStore) -> list[dict]:
    """
    Fallback: extract compliance checks from markdown tables in the agent's output.

    The compliance agent outputs tables like:
    | Criterion | Guideline Limit | Deal Value | Status | Evidence | Reference |
    |-----------|-----------------|------------|--------|----------|-----------|
    | Some criterion | MUST: some limit | some value | ✅/⚠️/❌ | reasoning | Section X |
    """
    checks = []

    # Find all markdown table rows (skip header and separator rows)
    # Match rows with at least 5 pipe-separated columns
    row_pattern = re.compile(
        r'^\s*\|(.+?)\|(.+?)\|(.+?)\|(.+?)\|(.+?)(?:\|(.+?))?(?:\|(.+?))?\|\s*$',
        re.MULTILINE,
    )

    for match in row_pattern.finditer(compliance_text):
        cols = [c.strip() for c in match.groups() if c is not None]

        # Skip header rows and separator rows
        if not cols or all(c.startswith('-') or c.startswith('=') for c in cols):
            continue
        if cols[0].lower() in ("criterion", "category", "check", "**total**", "total"):
            continue
        # Skip rows that are template placeholders
        if "[criterion" in cols[0].lower() or "[category" in cols[0].lower():
            continue

        # Map emoji status to enum values
        status_col = cols[3] if len(cols) > 3 else ""
        if "✅" in status_col or "PASS" in status_col.upper():
            status = "PASS"
        elif "❌" in status_col or "FAIL" in status_col.upper():
            status = "FAIL"
        elif "ℹ" in status_col or "N/A" in status_col.upper():
            status = "N/A"
        else:
            status = "REVIEW"

        # Determine severity
        limit_col = cols[1] if len(cols) > 1 else ""
        severity = "MUST" if "MUST" in limit_col.upper() else "SHOULD"

        check = {
            "criterion": cols[0].strip("* "),
            "guideline_limit": limit_col,
            "deal_value": cols[2] if len(cols) > 2 else "",
            "status": status,
            "evidence": cols[4] if len(cols) > 4 else "",
            "reference": cols[5] if len(cols) > 5 else "",
            "severity": severity,
        }

        # Only add if criterion looks real (not empty or placeholder)
        if check["criterion"] and len(check["criterion"]) > 2:
            checks.append(check)

    if checks:
        tracer.record("Extraction", "REGEX_PARSE", f"Found {len(checks)} checks from markdown tables")
        return checks

    # If no table rows found, try extracting from emoji-based narrative lines
    # e.g., "✅ LTV: 65% (limit: 80%) - PASS" or "❌ DSCR: 1.1x (minimum: 1.2x)"
    emoji_pattern = re.compile(
        r'[✅⚠️❌ℹ️]\s*\**([^:|\n]+?)\**\s*[:—–-]\s*(.+)',
        re.MULTILINE,
    )
    for match in emoji_pattern.finditer(compliance_text):
        criterion = match.group(1).strip().strip("*")
        detail = match.group(2).strip()
        line_full = match.group(0)

        if "✅" in line_full:
            status = "PASS"
        elif "❌" in line_full:
            status = "FAIL"
        elif "⚠" in line_full:
            status = "REVIEW"
        else:
            status = "N/A"

        if criterion and len(criterion) > 2 and len(criterion) < 200:
            checks.append({
                "criterion": criterion,
                "guideline_limit": "",
                "deal_value": detail[:200],
                "status": status,
                "evidence": detail[:300],
                "reference": "",
                "severity": "MUST" if "must" in detail.lower() else "SHOULD",
            })

    if checks:
        tracer.record("Extraction", "REGEX_NARRATIVE", f"Found {len(checks)} checks from narrative lines")

    return checks


# =============================================================================
# Phase 1: Agentic Analysis
# =============================================================================

def run_agentic_analysis(
    teaser_text: str,
    search_procedure_fn: Callable,
    tracer: TraceStore | None = None,
    use_native_tools: bool = True,
    governance_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Agentic analysis — Process Analyst autonomously searches Procedure.

    Returns dict with: full_analysis, process_path, origination_method,
    procedure_sources, assessment_reasoning, origination_reasoning,
    decision_found, decision_confidence, fallback_used
    """
    if tracer is None:
        tracer = get_tracer()

    tracer.record("ProcessAnalyst", "START", "Beginning agentic teaser analysis")

    # Build governance-aware instruction
    pa_instruction = get_process_analyst_instruction(governance_context)

    # Try native function calling first
    if use_native_tools:
        try:
            raw = _run_analysis_native(teaser_text, search_procedure_fn, tracer, pa_instruction, governance_context)
        except Exception as e:
            logger.warning("Native tool calling failed, falling back to text-based: %s", e)
            tracer.record("ProcessAnalyst", "FALLBACK", f"Native tools failed: {e}")
            raw = _run_analysis_text_based(teaser_text, search_procedure_fn, tracer, pa_instruction)
    else:
        raw = _run_analysis_text_based(teaser_text, search_procedure_fn, tracer, pa_instruction)

    # Structured extraction — replaces keyword parsing
    decision = _extract_structured_decision(raw["full_analysis"], tracer)

    if decision:
        raw["process_path"] = decision.get("assessment_approach") or ""
        raw["origination_method"] = decision.get("origination_method") or ""
        raw["assessment_reasoning"] = decision.get("assessment_reasoning") or ""
        raw["origination_reasoning"] = decision.get("origination_reasoning") or ""
        raw["decision_found"] = bool(raw["process_path"] and raw["origination_method"])
        raw["decision_confidence"] = decision.get("confidence") or "MEDIUM"
        raw["fallback_used"] = False
    else:
        # NO SILENT DEFAULT — flag it clearly
        raw["process_path"] = ""
        raw["origination_method"] = ""
        raw["assessment_reasoning"] = ""
        raw["origination_reasoning"] = ""
        raw["decision_found"] = False
        raw["decision_confidence"] = "NONE"
        raw["fallback_used"] = False
        tracer.record(
            "ProcessAnalyst", "WARNING",
            "Agent did not produce a clear process path decision — human must decide"
        )

    return raw


def _run_analysis_native(
    teaser_text: str,
    search_procedure_fn: Callable,
    tracer: TraceStore,
    instruction: str = "",
    governance_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analysis using native Gemini function calling."""
    from tools.function_declarations import get_agent_tools, create_tool_executor

    tools = get_agent_tools("ProcessAnalyst", governance_context=governance_context)
    if not tools:
        raise RuntimeError("No native tool declarations available")

    executor = create_tool_executor(
        search_procedure_fn=search_procedure_fn,
        search_guidelines_fn=lambda q, n=3: {"status": "ERROR", "results": []},
        search_rag_fn=lambda q, n=3: {"status": "ERROR", "results": []},
    )

    pa_instr = instruction or PROCESS_ANALYST_INSTRUCTION

    prompt = f"""{pa_instr}

## YOUR TASK NOW

Analyze this teaser document completely.

<TEASER_DOCUMENT>
{teaser_text}
</TEASER_DOCUMENT>

## CRITICAL INSTRUCTIONS — READ BEFORE RESPONDING

**YOU MUST SEARCH THE PROCEDURE DOCUMENT BEFORE PRODUCING YOUR ANALYSIS.**

Do NOT write your analysis first. Instead:
1. FIRST, call the search_procedure tool AT LEAST 3 TIMES to find relevant rules, thresholds, and requirements
2. Read the search results carefully
3. THEN AND ONLY THEN produce your full analysis with the search results incorporated

If you produce an analysis without calling search_procedure first, your analysis will be REJECTED.

Suggested initial searches:
- search_procedure("assessment approach criteria thresholds")
- search_procedure("origination methods document types")
- search_procedure("proportionality criteria deal size")

After searching, produce your FULL analysis following the OUTPUT_STRUCTURE.
"""

    result = call_llm_with_tools(
        prompt=prompt,
        tools=tools,
        tool_executor=executor,
        model=AGENT_MODELS.get("process_analyst", MODEL_PRO),
        temperature=0.0,
        max_tokens=32000,
        agent_name="ProcessAnalyst",
        max_tool_rounds=8,
        tracer=tracer,
        thinking_budget=THINKING_BUDGET_LIGHT,
    )

    tracer.record("ProcessAnalyst", "ANALYSIS_DONE", f"Generated {len(result.text)} chars")

    return {
        "full_analysis": result.text,
        "process_path": "",
        "origination_method": "",
        "procedure_sources": {},
        "assessment_reasoning": "",
        "origination_reasoning": "",
    }


def _run_analysis_text_based(
    teaser_text: str,
    search_procedure_fn: Callable,
    tracer: TraceStore,
    instruction: str = "",
) -> dict[str, Any]:
    """Analysis using text-based tool calls (fallback)."""

    pa_instr = instruction or PROCESS_ANALYST_INSTRUCTION

    # Step 1: Planning — agent decides what to search
    planning_prompt = f"""{pa_instr}

## YOUR TASK NOW

Analyze this teaser and identify what Procedure sections you need to search.

<TEASER_DOCUMENT>
{teaser_text}
</TEASER_DOCUMENT>

## STEP 1: PLANNING

Read the teaser and plan your RAG searches:
1. What type of deal is this?
2. What Procedure sections do you need to verify?
3. What specific queries will you make?

You MUST plan at least 2 searches. If you're unsure, search broadly.

Output your analysis and list your RAG queries using:
<TOOL>search_procedure: "your query"</TOOL>
"""

    planning = call_llm(planning_prompt, MODEL_PRO, 0.0, 3000, "ProcessAnalyst", tracer, thinking_budget=THINKING_BUDGET_LIGHT)
    if not planning.success:
        tracer.record("ProcessAnalyst", "LLM_FAIL", f"Planning call failed: {planning.error or 'Unknown'}")
        return {"full_analysis": f"[Analysis failed: {planning.error}]", "process_path": "", "origination_method": "",
                "procedure_sources": {}, "assessment_reasoning": "", "rag_query_count": 0}

    # Step 2: Execute RAG — use agent's queries, NO hardcoded injection
    tool_calls = parse_tool_calls(planning.text, "search_procedure")

    agent_planned_queries = len(tool_calls)
    if agent_planned_queries == 0:
        tracer.record(
            "ProcessAnalyst", "WARNING",
            "Agent planned 0 RAG queries — retrying with explicit instruction"
        )
        retry_prompt = f"""You MUST search the Procedure document before making any determination.

Based on this teaser, generate 3-5 search queries for the Procedure document.
Each query should target a specific rule, threshold, or requirement.

<TEASER_DOCUMENT>
{teaser_text[:3000]}
</TEASER_DOCUMENT>

Output ONLY your queries, one per line, using this format:
<TOOL>search_procedure: "your specific query"</TOOL>
"""
        retry = call_llm(retry_prompt, MODEL_FLASH, 0.0, 1000, "ProcessAnalyst", tracer, thinking_budget=THINKING_BUDGET_NONE)
        tool_calls = parse_tool_calls(retry.text, "search_procedure")
        tracer.record(
            "ProcessAnalyst", "RETRY_RESULT",
            f"Retry produced {len(tool_calls)} queries (original: {agent_planned_queries})"
        )

    procedure_results: dict[str, Any] = {}
    for query in tool_calls[:7]:
        tracer.record("ProcessAnalyst", "RAG_SEARCH", f"Agent-planned: {query[:60]}...")
        result = search_procedure_fn(query, num_results=4)
        procedure_results[query] = result

    rag_context = format_rag_results(procedure_results)

    analysis_prompt = f"""{pa_instr}

## TEASER DOCUMENT

{teaser_text}

## YOUR INITIAL ANALYSIS

{planning.text}

## PROCEDURE SEARCH RESULTS

{rag_context}

## NOW: COMPLETE YOUR ANALYSIS

Using the teaser AND the Procedure search results:
1. Complete your data extraction
2. Determine the assessment approach — cite the SPECIFIC Procedure thresholds from the search results
3. Determine the origination method — cite the SPECIFIC Procedure criteria
4. If the search results don't contain what you need, say so explicitly

You MUST cite specific Procedure sections. Do NOT guess limits — only use values from the search results above.
"""

    final = call_llm(analysis_prompt, MODEL_PRO, 0.0, 16384, "ProcessAnalyst", tracer, thinking_budget=THINKING_BUDGET_STANDARD)
    if not final.success:
        tracer.record("ProcessAnalyst", "LLM_FAIL", f"Analysis call failed: {final.error or 'Unknown'}")
        return {"full_analysis": f"[Analysis failed: {final.error}]", "process_path": "", "origination_method": "",
                "procedure_sources": procedure_results, "assessment_reasoning": "", "rag_query_count": len(tool_calls)}

    tracer.record("ProcessAnalyst", "ANALYSIS_DONE", f"Generated {len(final.text)} chars")

    return {
        "full_analysis": final.text,
        "process_path": "",
        "origination_method": "",
        "procedure_sources": procedure_results,
        "assessment_reasoning": "",
        "origination_reasoning": "",
    }


# =============================================================================
# Dynamic Requirements Discovery (replaces static 28 fields)
# =============================================================================

REQUIREMENTS_DISCOVERY_PROMPT = """You are an analyst. Based on this deal analysis, the determined process path, and the governance document context below, identify ALL information requirements needed for the output document.

## DEAL ANALYSIS
{analysis_text}

## PROCESS PATH
Assessment Approach: {assessment_approach}
Origination Method: {origination_method}

## GOVERNANCE CONTEXT (from Procedure document)
{procedure_rag_context}

{governance_categories}

## INSTRUCTIONS

Identify requirements SPECIFIC to this deal. You MUST ground your requirements
in the Procedure document context above:
1. What does the Procedure say is required for THIS origination method / assessment approach?
2. What additional information is needed given the deal's asset class and parties?
3. What does the process path require? (More comprehensive = more data)
4. What special features exist that trigger additional requirements?
5. Only add fields beyond what the Procedure mandates if deal characteristics clearly require them.

For EACH requirement, explain WHY it's needed for THIS specific deal.

## OUTPUT FORMAT

You MUST output ONLY valid JSON between XML tags, with NO other text:

<json_output>
[
  {{
    "category": "<category name from Procedure or deal analysis>",
    "fields": [
      {{
        "id": 1,
        "name": "<field name>",
        "description": "<what this field captures>",
        "why_required": "<why needed for THIS deal, citing Procedure if possible>",
        "priority": "CRITICAL",
        "typical_source": "teaser"
      }}
    ]
  }}
]
</json_output>

RULES:
- Only include categories that apply to THIS deal
- Only include fields that are needed for the determined process path
- Every field must have a "why_required" explaining its relevance to THIS deal
- Mark priority as CRITICAL (blocks assessment), IMPORTANT (needed for quality), or SUPPORTING (nice to have)
- Do NOT include a fixed template — adapt to the deal
- If Procedure context is available, use its categories and terminology

CRITICAL:
- Output ONLY the JSON array between <json_output></json_output> tags
- NO markdown code fences like ```json
- NO preambles or explanations
- NO text before or after the tags

NOW: Generate requirements for this specific deal in the exact format above.
"""


def discover_requirements(
    analysis_text: str,
    assessment_approach: str,
    origination_method: str,
    tracer: TraceStore | None = None,
    search_procedure_fn: Callable | None = None,
    governance_context: dict | None = None,
) -> list[dict]:
    """
    Dynamically discover requirements based on deal analysis, process path,
    and governance documents (via RAG).

    Returns flat list of requirement dicts ready for the UI.
    """
    if tracer is None:
        tracer = get_tracer()

    tracer.record("RequirementsDiscovery", "START", "Discovering deal-specific requirements")

    # --- RAG grounding: search Procedure for requirements specific to this path ---
    procedure_rag_context = "(No Procedure context available — using general knowledge.)"
    if search_procedure_fn:
        om = origination_method or "assessment"
        aa = assessment_approach or "assessment"
        rag_queries = [
            f"information requirements for {om}",
            f"required data fields {aa} assessment",
            f"what information must be provided for {om} origination",
        ]
        rag_results: dict[str, Any] = {}
        rag_failures = 0
        for query in rag_queries:
            tracer.record("RequirementsDiscovery", "RAG_SEARCH", f"Procedure: {query[:60]}")
            try:
                rag_results[query] = search_procedure_fn(query, 3)
            except Exception as e:
                rag_failures += 1
                logger.warning("Requirements RAG query failed: %s", e)
        if rag_results:
            procedure_rag_context = format_rag_results(rag_results)
        # AG-M7: Warn if ALL RAG queries failed
        if rag_failures == len(rag_queries):
            procedure_rag_context += "\n\nWARNING: All RAG searches failed. Results may not be grounded in governance documents."
            tracer.record("RequirementsDiscovery", "RAG_ALL_FAILED", f"All {rag_failures} queries failed")

    # --- Inject governance-discovered categories if available ---
    governance_categories = ""
    if governance_context and governance_context.get("discovery_status") in ("complete", "partial"):
        cats = governance_context.get("requirement_categories", [])
        if cats:
            governance_categories = (
                "Known requirement categories from Procedure: " + ", ".join(cats)
            )

    prompt = REQUIREMENTS_DISCOVERY_PROMPT.format(
        analysis_text=analysis_text[:8000],
        assessment_approach=assessment_approach or "Not yet determined",
        origination_method=origination_method or "Not yet determined",
        procedure_rag_context=procedure_rag_context,
        governance_categories=governance_categories,
    )

    result = call_llm(prompt, MODEL_PRO, 0.0, 5000, "RequirementsDiscovery", tracer, thinking_budget=THINKING_BUDGET_LIGHT)
    if not result.success:
        tracer.record("RequirementsDiscovery", "LLM_FAIL", f"LLM call failed: {result.error or 'Unknown'}")
        return []

    field_groups = safe_extract_json(result.text, "array")

    if not field_groups:
        tracer.record("RequirementsDiscovery", "PARSE_FAIL",
                      "Could not parse requirements — human must define them")
        return []

    requirements = []
    for group in field_groups:
        category = group.get("category", "GENERAL")
        for field in group.get("fields", []):
            requirements.append({
                "id": field.get("id", len(requirements) + 1),
                "name": field.get("name", "Unknown"),
                "description": field.get("description", ""),
                "why_required": field.get("why_required", ""),
                "priority": field.get("priority", "IMPORTANT"),
                "typical_source": field.get("typical_source", "teaser"),
                "category": category,
                "status": "pending",
                "value": "",
                "source": "",
                "evidence": "",
                "suggestion_detail": "",
            })

    for i, req in enumerate(requirements):
        req["id"] = i + 1

    tracer.record(
        "RequirementsDiscovery", "COMPLETE",
        f"Discovered {len(requirements)} requirements across {len(field_groups)} categories"
    )
    return requirements


# =============================================================================
# =============================================================================
# Phase 3: Agentic Compliance (CLASS-BASED)
# =============================================================================

def run_agentic_compliance(
    requirements: list[dict],
    teaser_text: str,
    extracted_data: str,
    search_guidelines_fn: Callable,
    tracer: TraceStore | None = None,
    use_native_tools: bool = True,
    governance_context: dict[str, Any] | None = None,
) -> tuple[str, list[dict]]:
    """
    Agentic compliance — uses ComplianceAdvisor class.

    This is a backward-compatible wrapper that instantiates the ComplianceAdvisor
    class and delegates to its assess_compliance() method.

    The agent decides which criteria to check based on the deal.
    Structured extraction then pulls out ALL criteria it assessed.
    """
    from agents.compliance_advisor import ComplianceAdvisor

    if tracer is None:
        tracer = get_tracer()

    # Instantiate ComplianceAdvisor with governance context
    advisor = ComplianceAdvisor(
        search_guidelines_fn=search_guidelines_fn,
        governance_context=governance_context,
        tracer=tracer,
    )

    # Delegate to class method
    return advisor.assess_compliance(
        requirements=requirements,
        teaser_text=teaser_text,
        extracted_data=extracted_data,
        use_native_tools=use_native_tools,
    )



# =============================================================================
# Orchestrator Decision Points — Now with Routing Decisions
# =============================================================================

ORCHESTRATOR_ROUTING_PROMPT = """You are the Orchestrator. Based on your analysis, make routing decisions.

## YOUR ANALYSIS
{analysis_text}

## CURRENT PHASE
{phase}

## TASK
Analyze the findings above and provide routing decisions.

ROUTING RULES:
- If ANY risk flag is HIGH severity → set requires_human_review: true
- If critical data is missing → set can_proceed: false with block_reason
- If compliance has FAIL status → set can_proceed: false
- suggested_additional_steps: list any relevant follow-up actions based on the analysis (e.g., additional checks, verification, escalation)

## OUTPUT FORMAT

You MUST output ONLY valid JSON between XML tags, with NO other text:

<json_output>
{{
  "risk_flags": [
    {{"text": "<risk description>", "severity": "HIGH|MEDIUM|LOW"}}
  ],
  "observations": ["<observation 1>", "<observation 2>"],
  "recommendations": ["<recommendation 1>"],
  "routing": {{
    "can_proceed": true,
    "requires_human_review": false,
    "suggested_additional_steps": [],
    "block_reason": ""
  }},
  "message_to_human": "<1-2 sentence summary>"
}}
</json_output>

CRITICAL:
- Output ONLY the JSON object between <json_output></json_output> tags
- NO markdown code fences like ```json
- NO preambles or explanations
- NO text before or after the tags

NOW: Analyze and return routing decisions in the exact format above.
"""


def run_orchestrator_decision(
    phase: str,
    findings: dict[str, str],
    context: dict[str, str],
    tracer: TraceStore | None = None,
    governance_context: dict[str, Any] | None = None,
) -> OrchestratorInsights:
    """
    Orchestrator analyzes findings and provides ACTIONABLE routing decisions.
    """
    if tracer is None:
        tracer = get_tracer()

    tracer.record("Orchestrator", "DECISION_POINT", f"Phase: {phase}")

    orch_instr = get_orchestrator_instruction(governance_context)

    analysis_prompt = f"""{orch_instr}

## CURRENT PHASE: {phase}

## FINDINGS TO ANALYZE

"""
    for key, value in findings.items():
        content = value[:3000] if isinstance(value, str) else str(value)[:3000]
        analysis_prompt += f"### {key}\n{content}\n\n"

    for key, value in context.items():
        content = value[:1500] if isinstance(value, str) else str(value)[:1500]
        analysis_prompt += f"### {key}\n{content}\n\n"

    analysis_prompt += "\nProvide your complete analysis: observations, risk flags, plan adjustments, and recommendations.\n"

    analysis_result = call_llm(analysis_prompt, MODEL_PRO, 0.1, 3000, "Orchestrator", tracer, thinking_budget=THINKING_BUDGET_LIGHT)
    if not analysis_result.success:
        tracer.record("Orchestrator", "LLM_FAIL", f"Analysis call failed: {analysis_result.error or 'Unknown'}")
        return OrchestratorInsights(
            full_text=f"[Orchestrator analysis failed: {analysis_result.error}]",
            can_proceed=False, requires_human_review=True,
            message_to_human="Orchestrator analysis failed — manual review required.",
        )

    routing_prompt = ORCHESTRATOR_ROUTING_PROMPT.format(
        analysis_text=analysis_result.text,
        phase=phase,
    )
    routing_result = call_llm(routing_prompt, MODEL_FLASH, 0.0, 3000, "Orchestrator", tracer, thinking_budget=THINKING_BUDGET_NONE)
    if not routing_result.success:
        tracer.record("Orchestrator", "LLM_FAIL", f"Routing call failed: {routing_result.error or 'Unknown'}")
        return OrchestratorInsights(
            full_text=analysis_result.text,
            can_proceed=False, requires_human_review=True,
            message_to_human="Orchestrator routing failed — manual review required.",
        )

    routing = safe_extract_json(routing_result.text, "object")

    insights = OrchestratorInsights(full_text=analysis_result.text)

    if routing:
        insights.observations = routing.get("observations", [])
        insights.recommendations = routing.get("recommendations", [])
        insights.message_to_human = routing.get("message_to_human", "")

        for flag_data in routing.get("risk_flags", []):
            try:
                severity = RiskSeverity(flag_data.get("severity", "MEDIUM"))
            except ValueError:
                severity = RiskSeverity.MEDIUM
            insights.flags.append(RiskFlag(
                text=flag_data.get("text", ""),
                severity=severity,
            ))

        routing_decisions = routing.get("routing", {})
        insights.can_proceed = routing_decisions.get("can_proceed", True)
        insights.requires_human_review = routing_decisions.get("requires_human_review", False)
        insights.suggested_additional_steps = routing_decisions.get("suggested_additional_steps", [])
        insights.block_reason = routing_decisions.get("block_reason", "")
    else:
        # AG-M3: Default-block on parse failure (conservative)
        insights.can_proceed = False
        insights.requires_human_review = True
        insights.message_to_human = "Orchestrator analysis could not be parsed — manual review required before proceeding."
        tracer.record("Orchestrator", "PARSE_FAIL", "Could not extract routing decisions — blocked by default")

    tracer.record(
        "Orchestrator", "DECISION_COMPLETE",
        f"Can proceed: {insights.can_proceed}, Requires review: {insights.requires_human_review}, "
        f"Flags: {len(insights.flags)}"
    )
    return insights


# =============================================================================
# Adaptive Section Structure
# =============================================================================

def generate_section_structure(
    example_text: str,
    assessment_approach: str,
    origination_method: str,
    analysis_text: str,
    tracer: TraceStore | None = None,
    search_procedure_fn: Callable | None = None,
    governance_context: dict | None = None,
) -> list[dict]:
    """
    Generate document section structure adapted to process path and deal type.
    Now grounded in Procedure document via RAG.
    """
    if tracer is None:
        tracer = get_tracer()

    tracer.record("StructureGen", "START", f"Generating structure for {origination_method}")

    # --- RAG grounding: search Procedure for section requirements ---
    procedure_sections_context = "(No Procedure context available — using general knowledge.)"
    if search_procedure_fn:
        om = origination_method or "document"
        aa = assessment_approach or "assessment"
        rag_queries = [
            f"required sections for {om} document",
            f"content structure {om} origination method",
            f"section requirements {aa} assessment approach",
        ]
        rag_results: dict[str, Any] = {}
        rag_failures = 0
        for query in rag_queries:
            tracer.record("StructureGen", "RAG_SEARCH", f"Procedure: {query[:60]}")
            try:
                rag_results[query] = search_procedure_fn(query, 3)
            except Exception as e:
                rag_failures += 1
                logger.warning("Structure RAG query failed: %s", e)
        if rag_results:
            procedure_sections_context = format_rag_results(rag_results)
        # AG-M7: Warn if ALL RAG queries failed
        if rag_failures == len(rag_queries):
            procedure_sections_context += "\n\nWARNING: All RAG searches failed. Section structure may not match governance requirements."
            tracer.record("StructureGen", "RAG_ALL_FAILED", f"All {rag_failures} queries failed")

    # --- Inject governance-discovered section templates if available ---
    gov_sections_str = ""
    if governance_context and governance_context.get("discovery_status") in ("complete", "partial"):
        templates = governance_context.get("section_templates", {})
        om_key = origination_method or ""
        # Try exact match first, then partial match
        matched_template = templates.get(om_key)
        if not matched_template:
            for key, val in templates.items():
                if key.lower() in om_key.lower() or om_key.lower() in key.lower():
                    matched_template = val
                    break
        if matched_template:
            gov_sections_str = (
                f"Procedure-defined sections for '{om_key}': "
                + json.dumps(matched_template, indent=2)
            )

    prompt = f"""Determine the section structure for this {PRODUCT_NAME}.

## PROCESS PATH
Assessment Approach: {assessment_approach}
Origination Method: {origination_method}

## PROCEDURE CONTEXT (from governance documents)
{procedure_sections_context}

{gov_sections_str}

## DEAL ANALYSIS (excerpt)
{analysis_text[:3000]}

## EXAMPLE DOCUMENT (for reference)
{example_text[:5000] if example_text else "(No example provided)"}

## INSTRUCTIONS

Design the section structure for THIS specific {PRODUCT_NAME}:

1. **Use the Procedure document above as primary guide:**
   - If the Procedure specifies required sections for this origination method, use those
   - The Procedure determines both the NUMBER of sections and their NAMES
   - Only deviate from the Procedure if the deal has unusual features not covered

2. **If the Procedure does not specify sections**, judge scope from the origination method name
   (more comprehensive origination = more sections, condensed = fewer)

3. **Adapt section content to the specific deal characteristics** found in the analysis

4. **Use the example for style reference, not as a rigid template**

## OUTPUT FORMAT

Return a JSON array:
```json
[{{"name": "Section Name", "description": "What this section covers for THIS deal", "detail_level": "Detailed|Standard|Brief"}}]
```

Return ONLY the JSON array.
"""

    result = call_llm(prompt, MODEL_PRO, 0.0, 4000, "StructureGen", tracer, thinking_budget=THINKING_BUDGET_LIGHT)
    if not result.success:
        tracer.record("StructureGen", "LLM_FAIL", f"Structure generation failed: {result.error or 'Unknown'}")
        return []

    sections = safe_extract_json(result.text, "array")

    if sections and len(sections) >= 2:
        tracer.record("StructureGen", "COMPLETE", f"Generated {len(sections)} sections")
        return sections

    # AG-1: Retry with simplified prompt using MODEL_FLASH at temperature 0.0
    tracer.record("StructureGen", "RETRY", "First attempt failed JSON extraction — retrying with simplified prompt")
    logger.warning("Section structure first attempt failed, retrying with MODEL_FLASH")

    retry_prompt = f"""Generate a JSON array of {PRODUCT_NAME} sections for this deal.

Assessment Approach: {assessment_approach}
Origination Method: {origination_method}

Deal excerpt: {analysis_text[:2000]}

Return ONLY a valid JSON array. Each element must have "name", "description", and "detail_level" fields.
Example: [{{"name": "Executive Summary", "description": "Overview of the deal", "detail_level": "Standard"}}]

Return ONLY the JSON array, no other text.
"""
    retry_result = call_llm(retry_prompt, MODEL_FLASH, 0.0, 3000, "StructureGen", tracer, thinking_budget=THINKING_BUDGET_NONE)
    retry_sections = safe_extract_json(retry_result.text, "array")

    if retry_sections and len(retry_sections) >= 2:
        tracer.record("StructureGen", "RETRY_SUCCESS", f"Retry generated {len(retry_sections)} sections")
        return retry_sections

    tracer.record("StructureGen", "PARSE_FAIL", "Could not generate section structure after 2 attempts")
    logger.error("Section structure generation failed after retry. Last output: %s", retry_result.text[:500])
    return []


# =============================================================================
# Section Drafting with Agent Communication
# =============================================================================

def draft_section(
    section: dict[str, str],
    context: dict[str, Any],
    agent_bus: Any = None,
    tracer: TraceStore | None = None,
    governance_context: dict[str, Any] | None = None,
) -> SectionDraft:
    """Draft a document section with full context."""
    if tracer is None:
        tracer = get_tracer()

    section_name = section.get("name", "Section")
    tracer.record("Writer", "START", f"Drafting: {section_name}")

    teaser_text = context.get("teaser_text", "")
    example_text = context.get("example_text", "")
    extracted_data = context.get("extracted_data", "")
    compliance_result = context.get("compliance_result", "")
    requirements = context.get("requirements", [])
    supplement_texts = context.get("supplement_texts", {})
    previously_drafted = context.get("previously_drafted", "")

    filled_context = format_requirements_for_context(
        requirements if isinstance(requirements, list) else []
    )

    supplement_context = ""
    if supplement_texts:
        for fname, ftext in supplement_texts.items():
            supplement_context += f"\n### Supplementary: {fname}\n{ftext[:3000]}\n"

    previously_context = ""
    if previously_drafted:
        previously_context = f"""
### Previously Drafted Sections (for consistency — do NOT repeat their content):
{previously_drafted[:6000]}
"""

    writer_instr = get_writer_instruction(governance_context)

    prompt = f"""{writer_instr}

## SECTION TO DRAFT: {section_name}

Description: {section.get('description', '')}
Detail Level: {section.get('detail_level', 'Standard')}

## COMPLETE CONTEXT

### Teaser Document (FULL — use for ALL facts):
{teaser_text}

### Extracted Data Analysis (FULL):
{extracted_data}

### Filled Requirements:
{filled_context}

### Compliance Assessment (FULL):
{compliance_result}

{f"### Supplementary Documents:{supplement_context}" if supplement_context else ""}

{previously_context}

### Example Document (STYLE REFERENCE ONLY — never copy facts):
{example_text}

## NOW: DRAFT THIS SECTION

Remember:
- Use example for STYLE and STRUCTURE only
- ALL facts from teaser/data/compliance — never from example
- Mark missing info as **[INFORMATION REQUIRED: description]**
- Be precise: exact figures, full names, specific dates
- Use ## and ### for sub-headings WITHIN this section (not # which is reserved for section titles)
- Do NOT repeat content already covered in previously drafted sections
"""

    result = call_llm_streaming(
        prompt, MODEL_PRO, 0.3, 8000, "Writer", tracer=tracer, thinking_budget=THINKING_BUDGET_STANDARD
    )
    if not result.success:
        tracer.record("Writer", "LLM_FAIL", f"Drafting call failed: {result.error or 'Unknown'}")

    agent_queries_used: list[AgentMessage] = []
    if agent_bus:
        queries = parse_agent_queries(result.text)
        for q in queries:
            tracer.record("Writer", "AGENT_QUERY", f"→ {q['to']}: {q['query'][:60]}...")
            response = agent_bus.query("Writer", q["to"], q["query"], context)
            agent_queries_used.append(AgentMessage(
                from_agent="Writer",
                to_agent=q["to"],
                query=q["query"],
                response=response[:500],
            ))

        # AG-F1: Feed agent responses back into a refinement call
        if agent_queries_used:
            tracer.record("Writer", "REFINEMENT", f"Refining draft with {len(agent_queries_used)} agent responses")
            agent_responses_text = "\n\n".join(
                f"**From {aq.to_agent}** (re: {aq.query[:80]}):\n{aq.response}"
                for aq in agent_queries_used
            )
            refinement_prompt = f"""{writer_instr}

## SECTION TO REFINE: {section_name}

## YOUR INITIAL DRAFT
{result.text[:6000]}

## AGENT RESPONSES TO YOUR QUERIES
{agent_responses_text}

## INSTRUCTIONS
Refine your draft by incorporating the information from the agent responses above.
- Integrate the new information naturally into the section
- Keep the same structure and style
- Output ONLY the refined section text — no metadata or thinking
"""
            refined = call_llm_streaming(
                refinement_prompt, MODEL_PRO, 0.2, 8000, "Writer", tracer=tracer, thinking_budget=THINKING_BUDGET_STANDARD
            )
            if refined.success and len(refined.text.strip()) > 100:
                tracer.record("Writer", "REFINEMENT_OK", f"Refined draft: {len(refined.text)} chars")
                result = refined
            else:
                tracer.record("Writer", "REFINEMENT_SKIP", "Refinement output insufficient, using original")

    draft_content = result.text
    if "### 📝 DRAFTED SECTION" in draft_content:
        parts = draft_content.split("### 📝 DRAFTED SECTION")
        if len(parts) > 1:
            section_part = parts[1]
            if "### 📋 SECTION METADATA" in section_part:
                section_part = section_part.split("### 📋 SECTION METADATA")[0]
            draft_content = section_part.strip()

    # AG-3: Validate Writer output — retry if content is too short or missing
    min_content_length = 100  # Minimum chars for a valid section draft
    if len(draft_content.strip()) < min_content_length:
        tracer.record(
            "Writer", "VALIDATION_FAIL",
            f"Draft too short ({len(draft_content.strip())} chars < {min_content_length}). Retrying with focused prompt."
        )
        logger.warning("Writer output validation failed for '%s' — retrying", section_name)

        retry_prompt = f"""Draft ONLY the section content for "{section_name}".

Description: {section.get('description', '')}

Use ONLY the following data sources:

Teaser: {teaser_text[:4000]}

Extracted Data: {extracted_data[:3000]}

Requirements: {filled_context[:2000]}

INSTRUCTIONS:
- Write the section content directly — no metadata, no thinking process
- Use exact figures and names from the data sources
- Mark missing information as **[INFORMATION REQUIRED: description]**
- Output ONLY the section text
"""
        retry_result = call_llm_streaming(
            retry_prompt, MODEL_PRO, 0.2, 6000, "Writer", tracer=tracer, thinking_budget=THINKING_BUDGET_STANDARD
        )
        retry_content = retry_result.text.strip()

        if len(retry_content) >= min_content_length:
            tracer.record("Writer", "RETRY_SUCCESS", f"Retry produced {len(retry_content)} chars")
            draft_content = retry_content
        else:
            tracer.record("Writer", "RETRY_FAILED", f"Retry also too short ({len(retry_content)} chars)")
            logger.error("Writer retry also failed for '%s'", section_name)

    tracer.record("Writer", "COMPLETE", f"Drafted: {section_name} ({len(draft_content)} chars)")

    return SectionDraft(
        name=section_name,
        content=draft_content,
        agent_queries=agent_queries_used,
    )


# =============================================================================
# Process Decision Lock
# =============================================================================

def create_process_decision(
    process_path: str,
    origination_method: str,
    extracted_data: str,
    procedure_sources: dict,
    assessment_reasoning: str = "",
    origination_reasoning: str = "",
    decision_found: bool = True,
    decision_confidence: str = "MEDIUM",
) -> ProcessDecision:
    """Create a ProcessDecision object for locking."""

    deal_size = "Unknown"
    matches = re.findall(
        r"(?:EUR|€|USD|\$|GBP|£|CHF|JPY|¥|AUD|CAD|SGD|HKD|SEK|NOK|DKK|PLN|CZK|AED|SAR|[A-Z]{3})\s*[\d,\.]+\s*(?:million|mln|M|billion|bln|B|thousand|K)?",
        extracted_data,
        re.IGNORECASE,
    )
    if matches:
        deal_size = matches[0]

    reasoning = ""
    if assessment_reasoning:
        reasoning += f"Assessment: {assessment_reasoning}"
    if origination_reasoning:
        reasoning += f"\nOrigination: {origination_reasoning}"
    if not reasoning:
        if decision_found:
            reasoning = "Process Analyst determined based on deal characteristics"
        else:
            reasoning = "Agent could not determine — requires human decision"

    return ProcessDecision(
        assessment_approach=process_path or "Unknown — requires human decision",
        origination_method=origination_method or "Unknown — requires human decision",
        evidence=ProcessDecisionEvidence(
            deal_size=deal_size,
            reasoning=reasoning,
            rag_sources=list(procedure_sources.keys())[:5],
        ),
    )
