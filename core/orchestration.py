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

from config.settings import MODEL_PRO, MODEL_FLASH, AGENT_MODELS
from core.llm_client import call_llm, call_llm_with_tools, call_llm_streaming
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
    RiskFlag,
    RiskSeverity,
    SectionDraft,
    AgentMessage,
)
from agents.orchestrator import ORCHESTRATOR_INSTRUCTION
from agents.process_analyst import PROCESS_ANALYST_INSTRUCTION
from agents.compliance_advisor import COMPLIANCE_ADVISOR_INSTRUCTION
from agents.writer import WRITER_INSTRUCTION

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

COMPLIANCE_EXTRACTION_PROMPT = """You are a JSON extraction assistant. Extract ALL compliance checks from the analysis below.

## COMPLIANCE ANALYSIS TEXT
{compliance_text}

## TASK
Extract every compliance criterion the agent checked into a JSON array.

CRITICAL FORMATTING RULES:
- You MUST output ONLY valid JSON with NO text before or after
- Do NOT include markdown code fences like ```json
- Do NOT include explanations, preambles, or any other text
- Output ONLY the JSON array between the <json_output></json_output> tags below

<json_output>
[
  {{
    "criterion": "<name of the criterion>",
    "guideline_limit": "<the limit from the Guidelines>",
    "deal_value": "<the deal's actual value>",
    "status": "PASS",
    "evidence": "<brief reasoning>",
    "reference": "<Guidelines section>",
    "severity": "MUST"
  }}
]
</json_output>

EXTRACTION RULES:
- Include EVERY criterion the agent assessed
- status must be exactly one of: "PASS", "FAIL", "REVIEW", "N/A"
- severity must be exactly one of: "MUST", "SHOULD"
- If no compliance checks found, return empty array: []

NOW: Extract ALL compliance checks. Output ONLY the JSON array between <json_output></json_output> tags with NO other text.
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
        
        result = call_llm(prompt, MODEL_FLASH, temperature, 4000, "Extraction", tracer)
        parsed = safe_extract_json(result.text, "object")
        
        if parsed and "decision_found" in parsed:
            if parsed.get("decision_found"):
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
    """
    tracer.record("Extraction", "START", "Extracting compliance checks")
    
    prompt = COMPLIANCE_EXTRACTION_PROMPT.format(
        compliance_text=compliance_text[:12000]
    )
    
    # Try up to 2 times
    for attempt in range(2):
        temperature = 0.0 if attempt == 0 else 0.1
        
        tracer.record("Extraction", "ATTEMPT", f"Attempt {attempt + 1}/2 (temp={temperature})")
        
        result = call_llm(prompt, MODEL_FLASH, temperature, 6000, "Extraction", tracer)
        parsed = safe_extract_json(result.text, "array")
        
        if parsed is not None and isinstance(parsed, list):
            tracer.record("Extraction", "SUCCESS", f"Extracted {len(parsed)} checks")
            return parsed
    
    # Both attempts failed
    tracer.record("Extraction", "FAILED", "Could not extract checks after 2 attempts")
    logger.error("Compliance extraction failed. Last output (first 1000 chars): %s", result.text[:1000])
    return []


# =============================================================================
# Phase 1: Agentic Analysis
# =============================================================================

def run_agentic_analysis(
    teaser_text: str,
    search_procedure_fn: Callable,
    tracer: TraceStore | None = None,
    use_native_tools: bool = True,
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

    # Try native function calling first
    if use_native_tools:
        try:
            raw = _run_analysis_native(teaser_text, search_procedure_fn, tracer)
        except Exception as e:
            logger.warning("Native tool calling failed, falling back to text-based: %s", e)
            tracer.record("ProcessAnalyst", "FALLBACK", f"Native tools failed: {e}")
            raw = _run_analysis_text_based(teaser_text, search_procedure_fn, tracer)
    else:
        raw = _run_analysis_text_based(teaser_text, search_procedure_fn, tracer)

    # Structured extraction — replaces keyword parsing
    decision = _extract_structured_decision(raw["full_analysis"], tracer)

    if decision:
        raw["process_path"] = decision["assessment_approach"]
        raw["origination_method"] = decision["origination_method"]
        raw["assessment_reasoning"] = decision.get("assessment_reasoning", "")
        raw["origination_reasoning"] = decision.get("origination_reasoning", "")
        raw["decision_found"] = True
        raw["decision_confidence"] = decision.get("confidence", "MEDIUM")
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
) -> dict[str, Any]:
    """Analysis using native Gemini function calling."""
    from tools.function_declarations import get_agent_tools, create_tool_executor

    tools = get_agent_tools("ProcessAnalyst")
    if not tools:
        raise RuntimeError("No native tool declarations available")

    executor = create_tool_executor(
        search_procedure_fn=search_procedure_fn,
        search_guidelines_fn=lambda q, n=3: {"status": "ERROR", "results": []},
        search_rag_fn=lambda q, n=3: {"status": "ERROR", "results": []},
    )

    prompt = f"""{PROCESS_ANALYST_INSTRUCTION}

## YOUR TASK NOW

Analyze this teaser document completely.

<TEASER_DOCUMENT>
{teaser_text}
</TEASER_DOCUMENT>

## INSTRUCTIONS

1. Read the teaser carefully
2. Use the search_procedure tool to look up relevant Procedure sections
3. Produce your FULL analysis following the OUTPUT_STRUCTURE

Be thorough. Search the Procedure for thresholds and requirements before making your determination.
"""

    result = call_llm_with_tools(
        prompt=prompt,
        tools=tools,
        tool_executor=executor,
        model=AGENT_MODELS.get("process_analyst", MODEL_PRO),
        temperature=0.0,
        max_tokens=16384,
        agent_name="ProcessAnalyst",
        max_tool_rounds=5,
        tracer=tracer,
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
) -> dict[str, Any]:
    """Analysis using text-based tool calls (fallback)."""

    # Step 1: Planning — agent decides what to search
    planning_prompt = f"""{PROCESS_ANALYST_INSTRUCTION}

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

    planning = call_llm(planning_prompt, MODEL_PRO, 0.0, 3000, "ProcessAnalyst", tracer)

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
        retry = call_llm(retry_prompt, MODEL_FLASH, 0.0, 1000, "ProcessAnalyst", tracer)
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

    analysis_prompt = f"""{PROCESS_ANALYST_INSTRUCTION}

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

    final = call_llm(analysis_prompt, MODEL_PRO, 0.0, 16384, "ProcessAnalyst", tracer)

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

REQUIREMENTS_DISCOVERY_PROMPT = """You are a credit analyst. Based on this deal analysis and the determined process path, identify ALL information requirements needed for the credit pack.

## DEAL ANALYSIS
{analysis_text}

## PROCESS PATH
Assessment Approach: {assessment_approach}
Origination Method: {origination_method}

## INSTRUCTIONS

Identify requirements SPECIFIC to this deal. Consider:
1. What does the process path require? (A more comprehensive assessment needs more data than a lighter one)
2. What asset class is this? (A hotel deal needs ADR/RevPAR; an office deal needs rent roll/WAULT)
3. What parties are involved? (Sponsor-backed? Guarantors? JV partners?)
4. What special features exist? (Construction? Acquisition? Refinancing? Multi-asset?)
5. What jurisdiction? (Different regulatory requirements)

For EACH requirement, explain WHY it's needed for THIS specific deal.

## OUTPUT FORMAT

You MUST output ONLY valid JSON between XML tags, with NO other text:

<json_output>
[
  {{
    "category": "DEAL INFORMATION",
    "fields": [
      {{
        "id": 1,
        "name": "Facility Amount",
        "description": "Total facility amount with currency",
        "why_required": "Core parameter for all credit assessments",
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
) -> list[dict]:
    """
    Dynamically discover requirements based on deal analysis and process path.

    Returns flat list of requirement dicts ready for the UI.
    """
    if tracer is None:
        tracer = get_tracer()

    tracer.record("RequirementsDiscovery", "START", "Discovering deal-specific requirements")

    prompt = REQUIREMENTS_DISCOVERY_PROMPT.format(
        analysis_text=analysis_text[:8000],
        assessment_approach=assessment_approach or "Not yet determined",
        origination_method=origination_method or "Not yet determined",
    )

    result = call_llm(prompt, MODEL_PRO, 0.0, 5000, "RequirementsDiscovery", tracer)
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
# Phase 3: Agentic Compliance
# =============================================================================

def run_agentic_compliance(
    requirements: list[dict],
    teaser_text: str,
    extracted_data: str,
    search_guidelines_fn: Callable,
    tracer: TraceStore | None = None,
    use_native_tools: bool = True,
) -> tuple[str, list[dict]]:
    """
    Agentic compliance — Compliance Advisor autonomously searches Guidelines.

    The agent decides which criteria to check based on the deal.
    Structured extraction then pulls out ALL criteria it assessed.
    """
    if tracer is None:
        tracer = get_tracer()

    tracer.record("ComplianceAdvisor", "START", "Beginning agentic compliance check")

    filled_data = "\n".join([
        f"**{r['name']}:** {r['value']}"
        for r in requirements if r.get("status") == "filled"
    ])

    if use_native_tools:
        try:
            result_text = _run_compliance_native(
                filled_data, teaser_text, extracted_data,
                search_guidelines_fn, tracer
            )
        except Exception as e:
            logger.warning("Native compliance tools failed: %s", e)
            tracer.record("ComplianceAdvisor", "FALLBACK", str(e))
            result_text = _run_compliance_text_based(
                filled_data, teaser_text, extracted_data,
                search_guidelines_fn, tracer
            )
    else:
        result_text = _run_compliance_text_based(
            filled_data, teaser_text, extracted_data,
            search_guidelines_fn, tracer
        )

    # Dynamic extraction — captures ALL criteria the agent checked
    checks = _extract_compliance_checks(result_text, tracer)

    tracer.record("ComplianceAdvisor", "COMPLETE", f"Checks extracted: {len(checks)}")
    return result_text, checks


def _run_compliance_native(
    filled_data: str,
    teaser_text: str,
    extracted_data: str,
    search_guidelines_fn: Callable,
    tracer: TraceStore,
) -> str:
    """Compliance using native function calling. Returns raw analysis text."""
    from tools.function_declarations import get_agent_tools, create_tool_executor

    tools = get_agent_tools("ComplianceAdvisor")
    if not tools:
        raise RuntimeError("No native tool declarations available")

    executor = create_tool_executor(
        search_procedure_fn=lambda q, n=3: {"status": "ERROR", "results": []},
        search_guidelines_fn=search_guidelines_fn,
        search_rag_fn=lambda q, n=3: {"status": "ERROR", "results": []},
    )

    prompt = f"""{COMPLIANCE_ADVISOR_INSTRUCTION}

## DEAL DATA

### Filled Requirements:
{filled_data}

### Extracted Analysis:
{extracted_data}

### Teaser:
{teaser_text}

## YOUR TASK

Perform a complete compliance assessment:
1. Use the search_guidelines tool to look up EVERY applicable limit
2. Check the deal against each limit you find
3. Include ALL relevant criteria — financial ratios, security requirements, sponsor criteria, concentration limits, anything else the Guidelines require
4. You MUST search before making determinations — do not rely on general knowledge

Follow the OUTPUT_STRUCTURE from your instructions.
"""

    result = call_llm_with_tools(
        prompt=prompt,
        tools=tools,
        tool_executor=executor,
        model=AGENT_MODELS.get("compliance_advisor", MODEL_PRO),
        temperature=0.0,
        max_tokens=12000,
        agent_name="ComplianceAdvisor",
        max_tool_rounds=5,
        tracer=tracer,
    )

    return result.text


def _run_compliance_text_based(
    filled_data: str,
    teaser_text: str,
    extracted_data: str,
    search_guidelines_fn: Callable,
    tracer: TraceStore,
) -> str:
    """Compliance using text-based tool calls (fallback). Returns raw analysis text."""

    planning_prompt = f"""{COMPLIANCE_ADVISOR_INSTRUCTION}

## YOUR TASK NOW

Plan your compliance assessment for this deal.

## DEAL DATA
{filled_data}

## EXTRACTED ANALYSIS
{extracted_data[:3000]}

## STEP 1: PLANNING

1. What type of deal is this (secured/unsecured PRE)? What asset class?
2. Which Guidelines sections apply to THIS specific deal?
3. What specific limits and criteria do you need to verify?
4. Are there any unusual features that trigger additional checks?

You MUST plan your searches. List each search query:
<TOOL>search_guidelines: "your specific query"</TOOL>
"""

    planning = call_llm(planning_prompt, MODEL_PRO, 0.0, 2500, "ComplianceAdvisor", tracer)

    tool_calls = parse_tool_calls(planning.text, "search_guidelines")

    agent_planned_queries = len(tool_calls)
    if agent_planned_queries == 0:
        tracer.record(
            "ComplianceAdvisor", "WARNING",
            "Agent planned 0 RAG queries — retrying"
        )
        retry_prompt = f"""You MUST search the Guidelines document before assessing compliance.

This deal involves: {extracted_data[:500]}

Generate 3-5 search queries to find the applicable Guidelines limits and requirements.
Each query should target a specific section, limit, or requirement.

<TOOL>search_guidelines: "your specific query"</TOOL>
"""
        retry = call_llm(retry_prompt, MODEL_FLASH, 0.0, 1000, "ComplianceAdvisor", tracer)
        tool_calls = parse_tool_calls(retry.text, "search_guidelines")
        tracer.record(
            "ComplianceAdvisor", "RETRY_RESULT",
            f"Retry produced {len(tool_calls)} queries (original: {agent_planned_queries})"
        )

    guideline_results: dict[str, Any] = {}
    for query in tool_calls[:7]:
        tracer.record("ComplianceAdvisor", "RAG_SEARCH", f"Agent-planned: {query[:60]}...")
        result = search_guidelines_fn(query, num_results=4)
        guideline_results[query] = result

    rag_context = format_rag_results(guideline_results)

    assessment_prompt = f"""{COMPLIANCE_ADVISOR_INSTRUCTION}

## GUIDELINES FROM RAG SEARCH
{rag_context}

## DEAL DATA

### Filled Requirements:
{filled_data}

### Extracted Analysis:
{extracted_data}

### Teaser:
{teaser_text}

## NOW: COMPLETE YOUR COMPLIANCE ASSESSMENT

Using the Guidelines search results above:
1. Check the deal against EVERY applicable criterion you found in the Guidelines
2. For each criterion, cite the SPECIFIC Guidelines section and limit
3. Only use limits from the search results — do NOT guess or use general knowledge
4. If a relevant limit was not found in the search, flag it as "UNABLE TO VERIFY — not found in search results"

Include ALL applicable criteria, not just financial ratios.
"""

    result = call_llm(assessment_prompt, MODEL_PRO, 0.0, 12000, "ComplianceAdvisor", tracer)
    return result.text


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
- suggested_additional_steps can include: "additional_compliance_check", "escalation_review", "data_verification", "re_analysis"

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
) -> OrchestratorInsights:
    """
    Orchestrator analyzes findings and provides ACTIONABLE routing decisions.
    """
    if tracer is None:
        tracer = get_tracer()

    tracer.record("Orchestrator", "DECISION_POINT", f"Phase: {phase}")

    analysis_prompt = f"""{ORCHESTRATOR_INSTRUCTION}

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

    analysis_result = call_llm(analysis_prompt, MODEL_PRO, 0.1, 3000, "Orchestrator", tracer)

    routing_prompt = ORCHESTRATOR_ROUTING_PROMPT.format(
        analysis_text=analysis_result.text,
        phase=phase,
    )
    routing_result = call_llm(routing_prompt, MODEL_FLASH, 0.0, 3000, "Orchestrator", tracer)
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
        insights.can_proceed = True
        insights.requires_human_review = True
        insights.message_to_human = "Could not parse orchestrator routing — please review manually."
        tracer.record("Orchestrator", "PARSE_FAIL", "Could not extract routing decisions")

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
) -> list[dict]:
    """
    Generate credit pack section structure adapted to process path and deal type.
    """
    if tracer is None:
        tracer = get_tracer()

    tracer.record("StructureGen", "START", f"Generating structure for {origination_method}")

    prompt = f"""Determine the section structure for this credit pack.

## PROCESS PATH
Assessment Approach: {assessment_approach}
Origination Method: {origination_method}

## DEAL ANALYSIS (excerpt)
{analysis_text[:3000]}

## EXAMPLE CREDIT PACK (for reference)
{example_text[:5000] if example_text else "(No example provided)"}

## INSTRUCTIONS

Design the section structure for THIS specific credit pack. Consider:

1. **Origination Method determines scope:**
   - A more comprehensive origination method (e.g., full credit rationale) → More sections, more detail (7-10 sections)
   - A condensed origination method (e.g., short form, abbreviated) → Fewer sections (4-6 sections)
   - A minimal/automated origination method → Fewest sections (3-4 sections)
   - Use the origination method name above to judge the appropriate scope

2. **Deal type determines content:**
   - If construction deal → add "Construction Plan & Budget" section
   - If acquisition → add "Acquisition Rationale" section
   - If multi-asset → add "Portfolio Overview" section
   - If hotel/hospitality → add "Operating Performance" section
   - Adapt to what the deal actually needs

3. **Use the example for style reference, not as a rigid template**

## OUTPUT FORMAT

Return a JSON array:
```json
[{{"name": "Section Name", "description": "What this section covers for THIS deal", "detail_level": "Detailed|Standard|Brief"}}]
```

Return ONLY the JSON array.
"""

    result = call_llm(prompt, MODEL_PRO, 0.0, 4000, "StructureGen", tracer)
    sections = safe_extract_json(result.text, "array")

    if sections and len(sections) >= 2:
        tracer.record("StructureGen", "COMPLETE", f"Generated {len(sections)} sections")
        return sections

    tracer.record("StructureGen", "PARSE_FAIL", "Could not generate section structure")
    return []


# =============================================================================
# Section Drafting with Agent Communication
# =============================================================================

def draft_section(
    section: dict[str, str],
    context: dict[str, Any],
    agent_bus: Any = None,
    tracer: TraceStore | None = None,
) -> SectionDraft:
    """Draft a credit pack section with full context."""
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

    prompt = f"""{WRITER_INSTRUCTION}

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

### Example Credit Pack (STYLE REFERENCE ONLY — never copy facts):
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
        prompt, MODEL_PRO, 0.3, 8000, "Writer", tracer=tracer
    )

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

    draft_content = result.text
    if "### 📝 DRAFTED SECTION" in draft_content:
        parts = draft_content.split("### 📝 DRAFTED SECTION")
        if len(parts) > 1:
            section_part = parts[1]
            if "### 📋 SECTION METADATA" in section_part:
                section_part = section_part.split("### 📋 SECTION METADATA")[0]
            draft_content = section_part.strip()

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
        r"(?:EUR|€|USD|\$)\s*[\d,\.]+\s*(?:million|M|billion|B)?",
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
        assessment_approach=process_path,
        origination_method=origination_method,
        evidence=ProcessDecisionEvidence(
            deal_size=deal_size,
            reasoning=reasoning,
            rag_sources=list(procedure_sources.keys())[:5],
        ),
    )
