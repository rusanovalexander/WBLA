"""
Compliance Advisor Agent - CLASS-BASED VERSION

Consolidates compliance assessment logic into a single ComplianceAdvisor class.
No mini-agents - all compliance logic is self-contained.

Key features:
- Governance-aware instruction building
- Native function calling + text-based fallback
- Autonomous RAG search for Guidelines
- Structured compliance check extraction
"""

from __future__ import annotations
from typing import Any, Callable
import logging

from config.settings import AGENT_MODELS, AGENT_TEMPERATURES, get_verbose_block, PRODUCT_NAME, MODEL_PRO, MODEL_FLASH, THINKING_BUDGET_NONE, THINKING_BUDGET_LIGHT
from core.llm_client import call_llm, call_llm_streaming, call_llm_with_tools
from core.tracing import TraceStore, get_tracer
from core.parsers import parse_tool_calls, format_rag_results, safe_extract_json
from models.schemas import ComplianceCheck

logger = logging.getLogger(__name__)


# =============================================================================
# Instruction Template Builders (same as before)
# =============================================================================

def _build_compliance_search_areas(governance_context: dict[str, Any] | None) -> str:
    """Build compliance search areas from governance context or defaults."""
    if governance_context and governance_context.get("compliance_framework"):
        areas = governance_context["compliance_framework"]
        return "\n".join(f"- {area}" for area in areas)
    return (
        "Search the Guidelines document broadly to discover all applicable compliance areas.\n"
        "Focus on areas relevant to the specific deal characteristics.\n"
        "Typical areas may include approval criteria, security requirements, financial limits,\n"
        "and exception processes — but adapt to what the Guidelines actually contain."
    )


def _build_search_examples(governance_context: dict[str, Any] | None) -> str:
    """Build search query examples from governance context or defaults."""
    if governance_context and governance_context.get("compliance_framework"):
        framework = governance_context["compliance_framework"]
        examples = []
        for cat in framework[:4]:
            examples.append(
                f'"Checking {cat} requirements..."\n'
                f'<TOOL>search_guidelines: "{cat} requirements limits"</TOOL>'
            )
        return "\n\n".join(examples)
    return (
        '"I need to verify specific limits for this deal type..."\n'
        '<TOOL>search_guidelines: "applicable requirements for this deal type"</TOOL>\n\n'
        '"Checking limit requirements..."\n'
        '<TOOL>search_guidelines: "limits and thresholds"</TOOL>\n\n'
        '"What structural requirements apply?"\n'
        '<TOOL>search_guidelines: "structural requirements"</TOOL>\n\n'
        '"Are there specific rules for this category?"\n'
        '<TOOL>search_guidelines: "specific rules for this category"</TOOL>'
    )


def _build_compliance_matrix_sections(governance_context: dict[str, Any] | None) -> str:
    """Build compliance matrix sections from governance context or defaults."""
    if governance_context and governance_context.get("compliance_framework"):
        categories = governance_context["compliance_framework"]
        sections = []
        for i, cat in enumerate(categories, start=2):
            sections.append(f"""
### {i}. 📊 COMPLIANCE MATRIX - {cat.upper()}

Search the Guidelines for ALL {cat.lower()} that apply to this deal type.
For EACH criterion you find, add a row:

| Criterion | Guideline Limit | Deal Value | Status | Evidence | Reference |
|-----------|-----------------|------------|--------|----------|-----------|
| [criterion name] | [MUST/SHOULD] [limit from RAG] | [value from deal data] | ✅/⚠️/❌ | "[source quote]" | [Doc title, page_reference from RAG] |

**IMPORTANT**: The Reference column MUST include the document title and page reference from your RAG search results.
Each RAG result includes a "page_reference" field (e.g., "p.5" or "pp.3-7") — use this in your citations.

Include ALL criteria found via RAG search — do not limit to a predefined list.
""")
        return "\n---\n".join(sections)
    # Default: open-ended matrix driven by Guidelines document
    return """
### 2. 📊 COMPLIANCE MATRIX

Organize your compliance assessment into sections based on the categories
you discover in the Guidelines document. For EACH category you find:

| Criterion | Guideline Limit | Deal Value | Status | Evidence | Reference |
|-----------|-----------------|------------|--------|----------|-----------|
| [criterion name] | [MUST/SHOULD] [limit from RAG] | [value from deal data] | ✅/⚠️/❌ | "[source quote]" | [Doc title, page_reference from RAG] |

**IMPORTANT**: The Reference column MUST include the document title and page reference from your RAG search results.
Each RAG result includes a "page_reference" field (e.g., "p.5" or "pp.3-7") — use this in your citations.

- State the guideline criterion and its source section
- State the deal's actual value or status
- Assess PASS / REVIEW / FAIL with evidence
- Note any conditions, exceptions, or required actions

Include ALL criteria found via RAG search — do not limit to a predefined list.
Group the criteria by whatever categories emerge from the Guidelines document.
"""


def _build_deal_classification(governance_context: dict[str, Any] | None) -> str:
    """Build deal classification dimensions from governance context or defaults."""
    if governance_context and governance_context.get("deal_taxonomy"):
        taxonomy = governance_context["deal_taxonomy"]
        lines = []
        for dim, values in taxonomy.items():
            dim_label = dim.replace("_", " ").title()
            lines.append(f"- {dim_label}: [as identified]")
        return "\n".join(lines)
    return (
        "Classify the deal along the dimensions used in the Guidelines document.\n"
        "For each dimension, state the value as identified from the teaser."
    )


_COMPLIANCE_ADVISOR_TEMPLATE = """
You are the **Compliance Advisor Agent** for a {product_name} drafting system.

<ROLE>
You are an expert in institutional guidelines and regulatory compliance. Your job is to:
1. Identify which guidelines apply to a specific deal
2. Check data against SPECIFIC limits and thresholds
3. Produce detailed compliance matrix with status for each criterion
4. Flag any gaps or exceptions required
5. Assess overall compliance status with clear reasoning
</ROLE>

<GUIDELINES_KNOWLEDGE>
You have access to a Guidelines document via RAG search. You do NOT know the exact structure
of this document in advance — you MUST search it to find relevant sections.

**Discovery approach:**
1. Start with broad queries to understand what the Guidelines cover
2. Then narrow down to specific limits, thresholds, and requirements
3. For each criterion you check, search for the SPECIFIC rule

**Typical areas to search for (adapt to the deal type):**
{compliance_search_areas}

DO NOT assume you know the section numbers or structure. SEARCH to find them.
</GUIDELINES_KNOWLEDGE>

<LEVEL3_AUTONOMOUS_SEARCH>
You can autonomously search the Guidelines document to find specific limits.

**Tool Syntax:**
<TOOL>search_guidelines: "your search query"</TOOL>

**When to Search:**
- To find exact limits for specific criteria
- To verify minimum requirements and thresholds
- To check security/collateral requirements
- To find specific rules for the deal's asset class
- To understand exception/deviation processes

**Search Strategy:**
1. Start broad: search for the topic area
2. Then narrow: search for specific limits and thresholds
3. Always cite the section you found

**Examples:**
{search_examples}
</LEVEL3_AUTONOMOUS_SEARCH>

<CRITICAL_RAG_REQUIREMENT>
You MUST use your RAG search tools to find the actual limits and thresholds from the Guidelines document.

DO NOT rely on general knowledge or pre-existing assumptions about what the limits are.
DO NOT assume standard values for any financial metric or ratio.

For EVERY criterion you check:
1. FIRST search the Guidelines for the specific limit
2. THEN compare the deal value against what you found
3. If you cannot find the limit in the Guidelines, mark it as "UNABLE TO VERIFY — limit not found in Guidelines search"

This ensures your compliance assessment is grounded in the actual Guidelines document,
not in general industry knowledge.
</CRITICAL_RAG_REQUIREMENT>

<COMPLIANCE_CHECK_TASK>
For each applicable criterion, determine:

**Status Options:**
- ✅ **PASS**: Meets or exceeds requirement with clear evidence
- ⚠️ **REVIEW**: Close to limit, needs attention, or partially compliant
- ❌ **FAIL**: Does not meet requirement, exception needed
- ℹ️ **N/A**: Not applicable to this deal type

**Severity Levels:**
- **MUST**: Mandatory requirement - breach requires exception
- **SHOULD**: Recommended - deviation requires justification

**For each criterion, document:**
1. Guideline requirement (with section reference)
2. Deal value (with source)
3. Pass/Fail determination
4. Evidence/reasoning
</COMPLIANCE_CHECK_TASK>

{verbose_block}

<OUTPUT_STRUCTURE>
Structure your response with these sections:

---

### 1. 🧠 COMPLIANCE THINKING

**Deal Classification:**
{deal_classification}
- Based on my RAG searches, the following sections of the Guidelines apply: [list what you found]

**Applicable Guidelines:**
- [Section reference] applies because: [reason]
- [Section reference] applies because: [reason]
- [Section reference] does NOT apply because: [reason]

**Data Available vs Required:**
For each criterion I will check, what data do I have and what does the guideline require?

**Initial Assessment:**
- Overall compliance appears: [COMPLIANT/CONDITIONAL/NON-COMPLIANT]
- Key issues are: [list]

---

{compliance_matrix_sections}

---

### EXCEPTIONS REQUIRED

| Exception | Guideline Breached | Deal Position | Justification Required |
|-----------|-------------------|---------------|----------------------|
| [if any] | [Section ref] | [detail] | [what's needed] |

If no exceptions required, state: "No exceptions required."

---

### SUMMARY

| Category | ✅ Pass | ⚠️ Review | ❌ Fail | Total |
|----------|---------|-----------|--------|-------|
| [category] | X | X | X | X |
| **TOTAL** | **X** | **X** | **X** | **X** |

**Overall Compliance Status:** [COMPLIANT / COMPLIANT WITH CONDITIONS / NON-COMPLIANT]

**Key Findings:**
1. [Most important finding]
2. [Second most important]
3. [Third most important]

---

### CONDITIONS & RECOMMENDATIONS

**Conditions Precedent (if any):**
- [Condition]

**Ongoing Monitoring:**
- [Covenant] to be tested [frequency]

**Recommendations:**
- [Recommendation]

---

### GUIDELINE SOURCES USED

| Query | Section Found | Key Finding |
|-------|---------------|-------------|
| "[search query]" | [Section ref] | [what was found] |

---

</OUTPUT_STRUCTURE>

<IMPORTANT_RULES>
- NEVER invent guideline requirements — search via RAG if unsure
- Always cite the specific section references that RAG returned
- Distinguish MUST (mandatory) from SHOULD (recommended)
- If a limit is unknown, search for it or state "LIMIT_TO_BE_VERIFIED"
- Be conservative - when in doubt, mark as REVIEW
- Include source quotes for all data used
</IMPORTANT_RULES>

<TOOLS>
You have access to:
- <TOOL>search_guidelines: "query"</TOOL> - Search Guidelines document for specific rules
- <TOOL>search_procedure: "query"</TOOL> - Search Procedure if needed
- tool_load_document: Load documents if needed
</TOOLS>
"""


def get_compliance_advisor_instruction(governance_context: dict[str, Any] | None = None) -> str:
    """Build Compliance Advisor instruction with governance-derived parameters."""
    return _COMPLIANCE_ADVISOR_TEMPLATE.format(
        compliance_search_areas=_build_compliance_search_areas(governance_context),
        search_examples=_build_search_examples(governance_context),
        compliance_matrix_sections=_build_compliance_matrix_sections(governance_context),
        deal_classification=_build_deal_classification(governance_context),
        verbose_block=get_verbose_block(),
        product_name=PRODUCT_NAME,
    )


# Backward-compatible constant (uses defaults when no governance context)
COMPLIANCE_ADVISOR_INSTRUCTION = get_compliance_advisor_instruction(None)


# =============================================================================
# Compliance Extraction Prompt
# =============================================================================

COMPLIANCE_EXTRACTION_PROMPT = """Extract ALL compliance checks from the text below into a JSON array. Do NOT think or explain — go straight to the JSON output.

## COMPLIANCE ANALYSIS TEXT
{compliance_text}

## TASK — DIRECT EXTRACTION, NO REASONING

Output ONLY a valid JSON array with NO text before or after. Do NOT include markdown fences.

For each criterion the agent assessed, extract:

<json_output>
[
  {{
    "criterion": "exact criterion name",
    "guideline_limit": "MUST/SHOULD [limit text]",
    "deal_value": "value from deal data",
    "status": "PASS|REVIEW|FAIL|N/A",
    "evidence": "brief evidence/reasoning",
    "reference": "Section X.X or Page Y",
    "severity": "MUST|SHOULD"
  }}
]
</json_output>

EXTRACTION RULES:
- Extract ALL criteria found in the analysis text
- If the agent checked 0 criteria, return an empty array: []
- Status must be exactly one of: PASS, REVIEW, FAIL, N/A
- Severity must be exactly one of: MUST, SHOULD
- If any field is missing, use empty string "" or "MUST" for severity

Output ONLY the JSON array between <json_output></json_output> tags.
"""


# =============================================================================
# ComplianceAdvisor Class (NEW)
# =============================================================================

class ComplianceAdvisor:
    """
    Compliance Advisor Agent - handles all compliance assessment logic.

    Consolidates:
    - Governance-aware instruction building
    - Native function calling + text-based fallback
    - Autonomous RAG search
    - Structured extraction of compliance checks
    """

    def __init__(
        self,
        search_guidelines_fn: Callable,
        governance_context: dict[str, Any] | None = None,
        tracer: TraceStore | None = None,
        search_procedure_fn: Callable | None = None,
    ):
        """
        Initialize ComplianceAdvisor.

        Args:
            search_guidelines_fn: Callable(query, num_results) -> RAG results dict
            governance_context: Discovered governance framework (from governance_discovery)
            tracer: TraceStore for observability
            search_procedure_fn: Optional Callable(query, num_results) -> RAG results dict
                                 for cross-referencing Procedure rules during compliance
        """
        self.search_guidelines_fn = search_guidelines_fn
        self.search_procedure_fn = search_procedure_fn
        self.governance_context = governance_context
        self.tracer = tracer or get_tracer()

        # Build instruction once
        self.instruction = get_compliance_advisor_instruction(governance_context)

        # Compliance criteria hint for prompts
        if governance_context and governance_context.get("compliance_framework"):
            self.criteria_hint = ", ".join(governance_context["compliance_framework"])
        else:
            self.criteria_hint = "all applicable compliance criteria from the Guidelines"

    def assess_compliance(
        self,
        requirements: list[dict],
        teaser_text: str,
        extracted_data: str,
        use_native_tools: bool = True,
        on_stream: Callable[[str], None] | None = None,
        on_thinking: Callable[[str], None] | None = None,
        supplement_texts: dict[str, str] | None = None,
    ) -> tuple[str, list[dict]]:
        """
        Complete compliance assessment including RAG search and extraction.

        Args:
            requirements: List of filled requirements
            teaser_text: Original teaser document text
            extracted_data: Extracted analysis from ProcessAnalyst
            use_native_tools: Whether to use native function calling (vs text-based fallback)
            supplement_texts: Optional dict of {filename: content} for supplementary docs

        Returns:
            Tuple of (compliance_analysis_text, list_of_compliance_checks)
        """
        self.tracer.record("ComplianceAdvisor", "START", "Beginning compliance assessment")

        # Prepare filled data
        filled_data = "\n".join([
            f"**{r['name']}:** {r['value']}"
            for r in requirements if r.get("status") == "filled"
        ])

        # Run compliance analysis (native or text-based)
        if use_native_tools:
            try:
                result_text = self._run_compliance_native(
                    filled_data, teaser_text, extracted_data
                )
            except Exception as e:
                logger.warning("Native compliance tools failed: %s", e)
                self.tracer.record("ComplianceAdvisor", "FALLBACK", str(e))
                result_text = self._run_compliance_text_based(
                    filled_data, teaser_text, extracted_data,
                    on_stream=on_stream, on_thinking=on_thinking,
                    supplement_texts=supplement_texts,
                )
        else:
            result_text = self._run_compliance_text_based(
                filled_data, teaser_text, extracted_data,
                on_stream=on_stream, on_thinking=on_thinking,
                supplement_texts=supplement_texts,
            )

        # Extract structured compliance checks
        checks = self._extract_compliance_checks(result_text)

        self.tracer.record("ComplianceAdvisor", "COMPLETE", f"Checks extracted: {len(checks)}")
        return result_text, checks

    def _run_compliance_native(
        self,
        filled_data: str,
        teaser_text: str,
        extracted_data: str,
    ) -> str:
        """Run compliance using native function calling."""
        from tools.function_declarations import get_agent_tools, create_tool_executor

        tools = get_agent_tools("ComplianceAdvisor", governance_context=self.governance_context)
        if not tools:
            raise RuntimeError("No native tool declarations available")

        executor = create_tool_executor(
            search_procedure_fn=self.search_procedure_fn or (lambda q, n=3: {"status": "ERROR", "results": []}),
            search_guidelines_fn=self.search_guidelines_fn,
            search_rag_fn=lambda q, n=3: {"status": "ERROR", "results": []},
        )

        prompt = f"""{self.instruction}

## DEAL DATA

### Filled Requirements:
{filled_data}

### Extracted Analysis:
{extracted_data}

### Teaser:
{teaser_text}

## CRITICAL INSTRUCTIONS — READ BEFORE RESPONDING

**YOU MUST SEARCH THE GUIDELINES DOCUMENT BEFORE PRODUCING YOUR ASSESSMENT.**

Do NOT write your assessment first. Instead:
1. FIRST, call the search_guidelines tool AT LEAST 3 TIMES to find applicable limits and criteria
2. Read the search results carefully
3. THEN AND ONLY THEN produce your full compliance assessment

If you produce an assessment without calling search_guidelines first, it will be REJECTED.

Criteria to check: {self.criteria_hint}

Follow the OUTPUT_STRUCTURE from your instructions.
"""

        result = call_llm_with_tools(
            prompt=prompt,
            tools=tools,
            tool_executor=executor,
            model=AGENT_MODELS.get("compliance_advisor", MODEL_PRO),
            temperature=0.0,
            max_tokens=32000,
            agent_name="ComplianceAdvisor",
            max_tool_rounds=8,
            tracer=self.tracer,
            thinking_budget=THINKING_BUDGET_LIGHT,
        )

        return result.text

    def _run_compliance_text_based(
        self,
        filled_data: str,
        teaser_text: str,
        extracted_data: str,
        on_stream: Callable[[str], None] | None = None,
        on_thinking: Callable[[str], None] | None = None,
        supplement_texts: dict[str, str] | None = None,
    ) -> str:
        """Run compliance using text-based tool calls (fallback)."""

        planning_prompt = f"""{self.instruction}

## YOUR TASK NOW

Plan your compliance assessment for this deal.

## DEAL DATA
{filled_data}

## EXTRACTED ANALYSIS
{extracted_data[:3000]}

## STEP 1: PLANNING

1. What type of deal is this? What structure? What asset class?
2. Which Guidelines sections apply to THIS specific deal?
3. What specific limits and criteria do you need to verify?
4. Are there any unusual features that trigger additional checks?

You MUST plan your searches. List each search query:
<TOOL>search_guidelines: "your specific query"</TOOL>
"""

        planning = call_llm(
            planning_prompt, MODEL_PRO, 0.0, 2500,
            "ComplianceAdvisor", self.tracer,
            thinking_budget=THINKING_BUDGET_LIGHT
        )

        if not planning.success:
            self.tracer.record("ComplianceAdvisor", "LLM_FAIL", f"Planning failed: {planning.error}")
            return f"[Compliance analysis failed: {planning.error}]"

        tool_calls = parse_tool_calls(planning.text, "search_guidelines")

        # Retry if no queries planned
        if len(tool_calls) == 0:
            self.tracer.record("ComplianceAdvisor", "WARNING", "Agent planned 0 RAG queries — retrying")
            retry_prompt = f"""You MUST search the Guidelines document before assessing compliance.

This deal involves: {extracted_data[:500]}

Generate 3-5 search queries to find the applicable Guidelines limits and requirements.
Each query should target a specific section, limit, or requirement.

<TOOL>search_guidelines: "your specific query"</TOOL>
"""
            retry = call_llm(
                retry_prompt, MODEL_FLASH, 0.0, 1000,
                "ComplianceAdvisor", self.tracer,
                thinking_budget=THINKING_BUDGET_NONE
            )
            tool_calls = parse_tool_calls(retry.text, "search_guidelines")
            self.tracer.record("ComplianceAdvisor", "RETRY_RESULT", f"Retry produced {len(tool_calls)} queries")

        # Execute RAG searches
        guideline_results: dict[str, Any] = {}
        for query in tool_calls[:7]:
            self.tracer.record("ComplianceAdvisor", "RAG_SEARCH", f"Agent-planned: {query[:60]}...")
            try:
                result = self.search_guidelines_fn(query, 4)
                guideline_results[query] = result
            except Exception as e:
                logger.warning("Guidelines search failed for '%s': %s", query, e)
                guideline_results[query] = {"status": "ERROR", "results": []}

        rag_context = format_rag_results(guideline_results)

        # Build supplementary documents block (financial statements, market reports, etc.)
        supplement_section = ""
        if supplement_texts:
            parts = []
            for fname, ftext in supplement_texts.items():
                parts.append(f"### {fname}\n{ftext[:3000]}")
            supplement_section = (
                "\n## ADDITIONAL SUPPORTING DOCUMENTS\n"
                "Use data from these documents when checking compliance criteria "
                "(e.g., LTV, DSCR, financial ratios from financial statements).\n\n"
                + "\n\n".join(parts)
            )

        # Final assessment with RAG context
        assessment_prompt = f"""{self.instruction}

## DEAL DATA

### Filled Requirements:
{filled_data}

### Extracted Analysis:
{extracted_data}

### Teaser:
{teaser_text[:3000]}
{supplement_section}
## GUIDELINES SEARCH RESULTS

{rag_context}

## YOUR TASK NOW

You've completed your RAG searches. Now produce your FULL compliance assessment following the OUTPUT_STRUCTURE.

Criteria to check: {self.criteria_hint}

Use ONLY the information from your RAG searches above when citing Guidelines limits.
"""

        if on_stream:
            assessment = call_llm_streaming(
                assessment_prompt, AGENT_MODELS.get("compliance_advisor", MODEL_PRO),
                0.0, 32000, "ComplianceAdvisor",
                on_chunk=on_stream,
                tracer=self.tracer,
                thinking_budget=THINKING_BUDGET_LIGHT,
            )
        else:
            assessment = call_llm(
                assessment_prompt, AGENT_MODELS.get("compliance_advisor", MODEL_PRO),
                0.0, 32000, "ComplianceAdvisor", self.tracer,
                thinking_budget=THINKING_BUDGET_LIGHT
            )

        if not assessment.success:
            self.tracer.record("ComplianceAdvisor", "LLM_FAIL", f"Assessment failed: {assessment.error}")
            return f"[Compliance assessment failed: {assessment.error}]"

        if assessment.thinking and on_thinking:
            on_thinking(assessment.thinking)

        return assessment.text

    def _extract_compliance_checks(self, compliance_text: str) -> list[dict]:
        """Extract structured compliance checks from free-text analysis."""
        self.tracer.record("ComplianceAdvisor", "EXTRACTION", "Extracting compliance checks")

        extraction_prompt = COMPLIANCE_EXTRACTION_PROMPT.format(compliance_text=compliance_text[:30000])

        result = call_llm(
            extraction_prompt, MODEL_FLASH, 0.0, 8000,
            "ComplianceAdvisor", self.tracer,
            thinking_budget=THINKING_BUDGET_NONE
        )

        if not result.success:
            logger.warning("Compliance extraction failed: %s", result.error)
            self.tracer.record("ComplianceAdvisor", "EXTRACTION_FAIL", str(result.error))
            return []

        parsed = safe_extract_json(result.text, "array")

        if not parsed or not isinstance(parsed, list):
            logger.warning("Compliance extraction returned non-array")
            self.tracer.record("ComplianceAdvisor", "PARSE_FAIL", "Expected array, got something else")
            return []

        # Validate and convert to dicts
        checks = []
        for item in parsed:
            if isinstance(item, dict):
                # Pre-process: convert null values to defaults (same as orchestration.py)
                if item.get("reference") is None:
                    item["reference"] = ""
                if item.get("severity") is None:
                    item["severity"] = "MUST"

                try:
                    validated = ComplianceCheck.model_validate(item)
                    checks.append(validated.model_dump())
                except Exception as e:
                    logger.warning("Pydantic validation failed for ComplianceCheck: %s", e)
                    # Add as dict anyway with defaults
                    checks.append({
                        "criterion": item.get("criterion", "Unknown"),
                        "guideline_limit": item.get("guideline_limit", ""),
                        "deal_value": item.get("deal_value", ""),
                        "status": item.get("status", "REVIEW"),
                        "evidence": item.get("evidence", ""),
                        "reference": item.get("reference", ""),
                        "severity": item.get("severity", "MUST"),
                    })

        self.tracer.record("ComplianceAdvisor", "CHECKS_EXTRACTED", f"Extracted {len(checks)} checks")
        return checks


# =============================================================================
# Backward-compatible agent config dict
# =============================================================================

compliance_advisor_config = {
    "name": "ComplianceAdvisorAgent",
    "model": AGENT_MODELS["compliance_advisor"],
    "instruction": COMPLIANCE_ADVISOR_INSTRUCTION,
    "temperature": AGENT_TEMPERATURES["compliance_advisor"],
    "tools": ["tool_search_guidelines", "tool_search_procedure", "tool_load_document"],
}
