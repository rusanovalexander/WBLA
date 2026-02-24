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
# =============================================================================
# Phase 1: Agentic Analysis (CLASS-BASED)
# =============================================================================

def run_agentic_analysis(
    teaser_text: str,
    search_procedure_fn: Callable,
    tracer: TraceStore | None = None,
    use_native_tools: bool = True,
    governance_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Agentic analysis — uses ProcessAnalyst class.
    
    Backward-compatible wrapper.
    """
    from agents.process_analyst import ProcessAnalyst
    
    if tracer is None:
        tracer = get_tracer()
    
    analyst = ProcessAnalyst(
        search_procedure_fn=search_procedure_fn,
        governance_context=governance_context,
        tracer=tracer,
    )
    
    return analyst.analyze_deal(teaser_text, use_native_tools)


# =============================================================================
# Dynamic Requirements Discovery (CLASS-BASED)
# =============================================================================

def discover_requirements(
    analysis_text: str,
    assessment_approach: str,
    origination_method: str,
    tracer: TraceStore | None = None,
    search_procedure_fn: Callable | None = None,
    governance_context: dict | None = None,
) -> list[dict]:
    """
    Dynamic requirements discovery — uses ProcessAnalyst class.
    
    Backward-compatible wrapper.
    """
    from agents.process_analyst import ProcessAnalyst
    
    if tracer is None:
        tracer = get_tracer()
    
    analyst = ProcessAnalyst(
        search_procedure_fn=search_procedure_fn,
        governance_context=governance_context,
        tracer=tracer,
    )
    
    return analyst.discover_requirements(analysis_text, assessment_approach, origination_method)


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
    Generate document section structure - uses Writer class.
    
    Backward-compatible wrapper.
    """
    from agents.writer import Writer
    
    if tracer is None:
        tracer = get_tracer()
    
    writer = Writer(
        search_procedure_fn=search_procedure_fn,
        governance_context=governance_context,
        tracer=tracer,
    )
    
    return writer.generate_structure(example_text, assessment_approach, origination_method, analysis_text)


def draft_section(
    section: dict[str, str],
    context: dict[str, Any],
    agent_bus: Any = None,
    tracer: TraceStore | None = None,
    governance_context: dict[str, Any] | None = None,
) -> SectionDraft:
    """
    Draft a document section - uses Writer class.
    
    Backward-compatible wrapper.
    """
    from agents.writer import Writer
    
    if tracer is None:
        tracer = get_tracer()
    
    writer = Writer(
        search_procedure_fn=context.get("search_procedure_fn"),
        governance_context=governance_context,
        agent_bus=agent_bus,
        tracer=tracer,
    )
    
    return writer.draft_section(section, context)


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
