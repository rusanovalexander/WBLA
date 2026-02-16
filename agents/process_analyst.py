"""
Process Analyst Agent - DOCUMENT-DRIVEN VERSION

Key changes:
- Instruction is now a function: get_process_analyst_instruction(governance_context)
- Search vocabulary, extraction sections, and risk taxonomy are parameterized
- Falls back to sensible defaults when governance context is not available
"""

from __future__ import annotations
from typing import Any

from config.settings import AGENT_MODELS, AGENT_TEMPERATURES, get_verbose_block, PRODUCT_NAME


def _build_search_vocabulary(governance_context: dict[str, Any] | None) -> str:
    """Build search vocabulary hints from governance context or defaults."""
    if governance_context and governance_context.get("search_vocabulary"):
        vocab = governance_context["search_vocabulary"]
        return "\n".join(f"- {term}" for term in vocab[:8])
    return (
        "- Assessment approach decision criteria and thresholds\n"
        "- Available assessment approaches and when each applies\n"
        "- Origination methods and their requirements\n"
        "- Decision trees and threshold criteria\n"
        "- Special rules for specific deal types"
    )


def _build_extraction_sections(governance_context: dict[str, Any] | None) -> str:
    """Build extraction section suggestions from governance context or defaults."""
    if governance_context and governance_context.get("requirement_categories"):
        cats = governance_context["requirement_categories"]
        return "\n".join(f"- {cat}" for cat in cats)
    return (
        "Organize your extraction by whatever logical categories emerge from the teaser.\n"
        "Typical structures include deal details, entity information, financial data, and security,\n"
        "but you MUST adapt the sections to the specific deal type and content.\n"
        "Always include an 'Identified Gaps' section at the end."
    )


def _build_risk_taxonomy(governance_context: dict[str, Any] | None) -> str:
    """Build risk assessment template from governance context or defaults."""
    if governance_context and governance_context.get("risk_taxonomy"):
        cats = governance_context["risk_taxonomy"]
        lines = []
        for cat in cats:
            lines.append(f"**{cat}:**")
            lines.append(f"- [Key {cat.lower()} factors]")
            lines.append(f"- [Initial assessment]\n")
        return "\n".join(lines)
    return (
        "Identify the risk categories that emerge from the deal characteristics and any "
        "governance documents. For each risk category you identify:\n"
        "**[Risk Category]:**\n"
        "- [Key factors]\n"
        "- [Initial assessment]\n"
    )


def _build_asset_class_hints(governance_context: dict[str, Any] | None) -> str:
    """Build asset class extraction hints from governance context or defaults."""
    if governance_context and governance_context.get("deal_taxonomy"):
        taxonomy = governance_context["deal_taxonomy"]
        subtypes = taxonomy.get("asset_subtype") or taxonomy.get("asset_class", [])
        if subtypes:
            return (
                "   Adapt your extraction focus to the deal's asset class as identified.\n"
                "   Search the Procedure for data requirements specific to the identified asset type.\n"
                "   Known asset types from Procedure: " + ", ".join(str(s) for s in subtypes)
            )
    return (
        "   Adapt your extraction focus to the deal's asset class.\n"
        "   Search the Procedure for data requirements specific to the identified asset type."
    )


def _build_example_extraction(governance_context: dict[str, Any] | None) -> str:
    """Build example extraction dynamically from governance context or generic structure.

    When governance_context has requirement_categories, generates a short
    category-adapted example. Otherwise, returns a domain-neutral structural
    example that demonstrates the expected format without any CRE-specific content.
    """
    if governance_context and governance_context.get("requirement_categories"):
        cats = governance_context["requirement_categories"]
        lines = ["**Example Extraction (adapted to governance categories):**\n"]
        for cat in cats[:5]:
            cat_upper = cat.upper() if cat == cat.lower() else cat
            lines.append(f"### {cat_upper}\n")
            lines.append(
                f"[Extract all information related to {cat.lower()} from the teaser. "
                f'Include exact figures with source quotes, e.g.: '
                f'"The [key metric] is [value with unit]" [HIGH CONFIDENCE] '
                f'[Source: "exact quote from teaser"]. '
                f"Mark missing information as NOT STATED.]\n"
            )
        return "\n".join(lines)

    # Domain-neutral structural example — demonstrates format without domain bias
    return """**Example Extraction (generic structure):**

### TRANSACTION OVERVIEW

The transaction is a [currency] [amount] [type/structure] with a [duration/term] [HIGH CONFIDENCE] [Source: "exact quote from teaser"]. The purpose is [purpose description] [HIGH CONFIDENCE] [Source: "exact quote"].

### PARTIES AND ENTITIES

The [primary entity] is [entity name], a [entity type] [HIGH CONFIDENCE] [Source: "exact quote"]. The [related party] is [details] [HIGH CONFIDENCE] [Source: "exact quote"].

### KEY METRICS

- [Metric 1]: [value] [HIGH CONFIDENCE] [Source: "exact quote"]
- [Metric 2]: [value] [HIGH CONFIDENCE] [Calculated: methodology]
- [Metric 3]: [value] [MEDIUM CONFIDENCE] [Estimated: reasoning]

### ADDITIONAL DETAILS

[Any other relevant information from the teaser, with source attribution]

### IDENTIFIED GAPS

**Information NOT stated in the teaser:**
- [Missing item 1] [NOT STATED]
- [Missing item 2] [NOT STATED]
"""


_PROCESS_ANALYST_TEMPLATE = """
You are the **Process Analyst Agent** for a {product_name} drafting system.

<ROLE>
You are an expert in processes and procedures. Your job is to:
1. Extract ALL data points from deal teasers (comprehensive extraction)
2. Analyze deal characteristics (type, amount, asset class, etc.)
3. Determine the correct process path based on the Procedure document
4. Identify all required steps for this specific deal
5. Flag any uncertainties or missing information
6. Provide preliminary risk assessment
</ROLE>

<PROCEDURE_KNOWLEDGE>
You have access to a Procedure document via RAG search. You do NOT know the exact structure
of this document in advance — you MUST search it to find relevant sections.

**Discovery approach:**
1. Start with broad queries to understand the document structure
2. Search for assessment approaches (how to determine which assessment is needed)
3. Search for proportionality criteria (thresholds that determine the approach)
4. Search for origination methods (what type of document to produce)

**Typical areas to search for (adapt based on what you find):**
{search_vocabulary}

DO NOT assume you know the section numbers or decision thresholds. SEARCH to find them.
</PROCEDURE_KNOWLEDGE>

<LEVEL3_AUTONOMOUS_SEARCH>
You can autonomously search the Procedure document to find specific rules.

**Tool Syntax:**
<TOOL>search_procedure: "your search query"</TOOL>

**When to Search:**
- To verify threshold amounts for assessment approaches
- To confirm required steps for a specific process path
- To check specific section requirements
- When uncertain about which path applies

**Example search queries:**
"What determines which assessment approach to use?"
<TOOL>search_procedure: "proportionality approach thresholds assessment"</TOOL>

"What are the origination methods available?"
<TOOL>search_procedure: "origination methods"</TOOL>

"What size threshold triggers a full assessment?"
<TOOL>search_procedure: "deal size threshold full assessment"</TOOL>
</LEVEL3_AUTONOMOUS_SEARCH>

<DATA_EXTRACTION_TASK>
Extract ALL available information from the teaser in NATURAL LANGUAGE, organized by logical categories.

**CRITICAL: DO NOT use a fixed template or rigid table format.**

Instead, write a comprehensive extraction in prose that captures EVERYTHING in the teaser.
Organize information naturally based on what the teaser actually contains.

**Extraction Principles:**

1. **Adapt to the Deal Type:**
{asset_class_hints}

2. **Natural Language Format:**
   Write each category as a paragraph or section of natural text, not a rigid table.
   Include ALL context, not just extracted values in isolation.

3. **Source Attribution:**
   After each piece of information, include [Source: "exact quote from teaser"] in parentheses.

4. **Confidence Indicators:**
   Mark your confidence for each major piece of information:
   - [HIGH CONFIDENCE]: Explicitly stated with clear source
   - [MEDIUM CONFIDENCE]: Reasonably inferred from available info
   - [LOW CONFIDENCE]: Uncertain or requires assumptions

{example_extraction}

---

**INSTRUCTIONS:**

Follow this NATURAL LANGUAGE approach instead of using a rigid table. 

Write comprehensive sections that capture ALL information naturally. This allows downstream requirement discovery to find ANY information using semantic search, regardless of exact field names.

The goal is a thorough analysis that reads like a professional analyst's memo, not a database dump.

</DATA_EXTRACTION_TASK>

<PROCESS_PATH_TASK>
After extraction, determine the correct process path by searching the Procedure document.

**1. Assessment Approach:**
Search the Procedure for:
- What assessment approaches are available
- The decision criteria / proportionality thresholds that determine which approach to use
- How deal size, complexity, client type affect the choice

Then apply what you found to THIS deal.

**2. Origination Method:**
Search the Procedure for:
- What origination methods / document types are available
- Which origination method matches which assessment approach
- Any special rules for the deal type

Then determine which method applies to THIS deal.

**3. Required Steps:**
Search the Procedure for the specific steps required for the assessment approach and origination method you determined. List ALL steps in order.

IMPORTANT: Do not use a pre-assumed list of options. SEARCH the Procedure to find what the options actually are, then pick the one that matches.
</PROCESS_PATH_TASK>

{verbose_block}

<OUTPUT_STRUCTURE>
Structure your response with these sections:

---

### 1. 🧠 THINKING PROCESS

Document your complete analytical thinking:

**Deal Assessment:**
- What type of deal is this? What are the key characteristics?
- Who are the parties involved (borrower, sponsor, guarantor)?

**Asset Assessment:**
- What is the asset/collateral and how would you assess it?
- Location quality and market position?

**Financial Assessment:**
- What are the key financial metrics?
- How do they compare to typical thresholds?

**Risk Indicators:**
- What risks do you identify?
- What additional information would strengthen the analysis?

**Procedure Application:**
- According to the Procedure [cite specific section you found via RAG]... [cite specific rules]
- The decision criteria indicate... [logic]

**Confidence Level:** [HIGH/MEDIUM/LOW] because...

---

### 2. 📋 COMPREHENSIVE EXTRACTION

[Write your natural language extraction here following the examples above]

Organize by logical sections based on what the teaser contains.
Suggested categories (from governance documents):
{extraction_sections}

Include confidence levels and source quotes throughout.

---

### 3. 📋 PROCESS PATH DETERMINATION

**A. Assessment Approach:**

Based on my RAG search of the Procedure document, the available assessment approaches are:
[List the approaches you found in the Procedure]

Evaluation against the decision criteria from the Procedure:
- Deal size: [amount] vs threshold: [from Procedure search]
- Client type: [type]
- Risk indicators: [list]
- Complexity: [assessment]

**Recommended Assessment Approach:** [Use the EXACT name from the Procedure document]

**Reasoning:** [Detailed explanation citing Procedure sections you searched]

**B. Origination Method:**

Based on my RAG search, the available origination methods are:
[List the methods you found in the Procedure]

Evaluation:
- Deal characteristics: [summary]
- Client profile: [summary]
- Requirements from Procedure: [what you found]

**Recommended Origination Method:** [Use the EXACT name from the Procedure document]

**Reasoning:** [Detailed explanation citing Procedure sections you searched]

---

### 4. 📋 REQUIRED PROCESS STEPS

Based on the determined process path, ALL required steps:

| Step | Description | What's Needed | Procedure Reference |
|------|-------------|---------------|---------------------|
| 1 | [step name] | [requirements] | Section X.X |
| 2 | [step name] | [requirements] | Section X.X |
| 3 | [step name] | [requirements] | Section X.X |
| ... | ... | ... | ... |

---

### 5. ❌ IDENTIFIED GAPS AND UNCERTAINTIES

| Gap/Uncertainty | Impact | Recommendation |
|-----------------|--------|----------------|
| [Missing item] | HIGH/MEDIUM/LOW | [Action to take] |
| [Unclear item] | HIGH/MEDIUM/LOW | [Action to take] |
| [Needs verification] | HIGH/MEDIUM/LOW | [Action to take] |

---

### 6. ⚠️ PRELIMINARY RISK ASSESSMENT

{risk_taxonomy}
*Note: This is preliminary - detailed assessment follows in compliance check.*

---

### 7. 📦 RESULT JSON

At the very END of your response, include this machine-readable block:

<RESULT_JSON>
{{
  "assessment_approach": "[The assessment approach you determined from the Procedure — use the EXACT term from the document]",
  "origination_method": "[The origination method you determined from the Procedure — use the EXACT term from the document]",
  "assessment_reasoning": "[1-2 sentence summary of WHY this assessment approach was chosen, citing Procedure]",
  "origination_reasoning": "[1-2 sentence summary of WHY this origination method was chosen, citing Procedure]",
  "procedure_sections_cited": ["[Section refs from your searches]"],
  "confidence": "HIGH | MEDIUM | LOW"
}}
</RESULT_JSON>

This JSON block is CRITICAL for downstream processing. Always include it as the very last item.
Use the EXACT terms from the Procedure document — do not paraphrase or generalize.

---

</OUTPUT_STRUCTURE>

<TOOLS>
You have access to:
- <TOOL>search_procedure: "query"</TOOL> - Search Procedure document for specific rules
- tool_load_document: Load any document if needed
</TOOLS>
"""


def get_process_analyst_instruction(governance_context: dict[str, Any] | None = None) -> str:
    """Build Process Analyst instruction with governance-derived parameters."""
    return _PROCESS_ANALYST_TEMPLATE.format(
        search_vocabulary=_build_search_vocabulary(governance_context),
        asset_class_hints=_build_asset_class_hints(governance_context),
        extraction_sections=_build_extraction_sections(governance_context),
        risk_taxonomy=_build_risk_taxonomy(governance_context),
        example_extraction=_build_example_extraction(governance_context),
        verbose_block=get_verbose_block(),
        product_name=PRODUCT_NAME,
    )


# Backward-compatible constant (uses defaults when no governance context)
PROCESS_ANALYST_INSTRUCTION = get_process_analyst_instruction(None)


# Create agent config dict
process_analyst_config = {
    "name": "ProcessAnalystAgent",
    "model": AGENT_MODELS["process_analyst"],
    "instruction": PROCESS_ANALYST_INSTRUCTION,
    "temperature": AGENT_TEMPERATURES["process_analyst"],
    "tools": ["tool_search_procedure", "tool_load_document"],
}
# This will be appended to agents/process_analyst.py

# =============================================================================
# ProcessAnalyst Class (NEW - Phase 1.2 Consolidation)
# =============================================================================

"""
ProcessAnalyst consolidates all analysis mini-agents:
- Extraction (deal data extraction from teaser)
- RequirementsDiscovery (dynamic requirements based on process path)

Single entry point: analyze_deal() + discover_requirements()
"""

import logging
from typing import Any, Callable
from config.settings import MODEL_PRO, MODEL_FLASH, AGENT_MODELS, THINKING_BUDGET_NONE, THINKING_BUDGET_LIGHT, THINKING_BUDGET_STANDARD
from core.llm_client import call_llm, call_llm_with_tools
from core.tracing import TraceStore, get_tracer
from core.parsers import parse_tool_calls, format_rag_results, safe_extract_json

logger = logging.getLogger(__name__)


# =============================================================================
# Decision Extraction Prompt
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
  "assessment_approach": "<exact approach name>",
  "origination_method": "<exact method name>",
  "assessment_reasoning": "<why this approach>",
  "origination_reasoning": "<why this method>",
  "confidence": "HIGH",
  "decision_found": true
}}
</json_output>

Output ONLY the JSON between <json_output></json_output> tags.
"""


# =============================================================================
# Decision JSON Normalization
# =============================================================================

def _normalize_decision_dict(parsed: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Validate and normalize decision JSON from LLM/RESULT_JSON.

    Ensures required keys exist and types are sane. Returns a cleaned dict or
    None if the content is unusable (no meaningful decision information).
    """
    if not isinstance(parsed, dict):
        return None

    decision: dict[str, Any] = {}

    # Normalize core string fields
    for key in (
        "assessment_approach",
        "origination_method",
        "assessment_reasoning",
        "origination_reasoning",
    ):
        value = parsed.get(key)
        if isinstance(value, str):
            value = value.strip()
        else:
            value = ""
        decision[key] = value

    # Normalize confidence
    raw_conf = parsed.get("confidence") or "MEDIUM"
    if isinstance(raw_conf, str):
        conf = raw_conf.strip().upper()
    else:
        conf = "MEDIUM"
    if conf not in {"HIGH", "MEDIUM", "LOW"}:
        conf = "MEDIUM"
    decision["confidence"] = conf

    # Preserve optional fields when present
    for key in ("procedure_sections_cited", "decision_found"):
        if key in parsed:
            decision[key] = parsed[key]

    # If both core identifiers are empty, treat as unusable
    if not decision["assessment_approach"] and not decision["origination_method"]:
        return None

    # Derive decision_found flag when missing
    if "decision_found" not in decision:
        decision["decision_found"] = bool(
            decision["assessment_approach"] or decision["origination_method"]
        )

    return decision


# =============================================================================
# Requirements Discovery Prompt
# =============================================================================

REQUIREMENTS_DISCOVERY_PROMPT = """You are an analyst. Based on this deal analysis and process path, identify ALL information requirements needed for a {origination_method}.

## DEAL ANALYSIS (contains extracted data from the teaser)
{analysis_text}

## PROCESS PATH
- Assessment Approach: {assessment_approach}
- Origination Method: {origination_method}

## PROCEDURE CONTEXT (from RAG search of the Procedure document)
{procedure_rag_context}

{governance_categories}

## TASK
1. Discover ALL information requirements specifically needed for a **{origination_method}** under the **{assessment_approach}** approach, as defined in the Procedure.
2. For EACH requirement, check if the deal analysis above already contains data that addresses it.
3. If data IS available in the analysis, set "value" to a summary of that data and "status" to "filled".
4. If data is NOT available, set "value" to "" and "status" to "empty".

IMPORTANT:
- Requirements should be SPECIFIC to the {origination_method} process, not generic documentation checklists.
- Focus on the information CONTENT required (financial metrics, risk assessments, compliance checks), not just document names.
- Include Procedure section references where possible.

OUTPUT FORMAT (JSON only):

<json_output>
{{
  "requirements": [
    {{
      "name": "Loan Purpose & Transaction Summary",
      "category": "Purpose of Application",
      "description": "Clear statement of the financing purpose, deal type, loan amount, LTV, term",
      "required": true,
      "value": "Acquisition financing for Polderzicht Retailpark, ca. €39MM senior loan, 50% LTV, 5yr term",
      "status": "filled",
      "source_hint": "Teaser summary",
      "procedure_ref": "Section 4.1.a"
    }},
    {{
      "name": "Obligor Credit Rating",
      "category": "Creditworthiness Assessment",
      "description": "Internal or external credit rating of the borrower",
      "required": true,
      "value": "",
      "status": "empty",
      "source_hint": "Not in teaser - request from client",
      "procedure_ref": "Section 4.2"
    }}
  ]
}}
</json_output>
"""


class ProcessAnalyst:
    """
    ProcessAnalyst Agent - handles all deal analysis and requirements discovery.
    """

    def __init__(
        self,
        search_procedure_fn: Callable,
        governance_context: dict[str, Any] | None = None,
        tracer: TraceStore | None = None,
    ):
        self.search_procedure_fn = search_procedure_fn
        self.governance_context = governance_context
        self.tracer = tracer or get_tracer()
        self.instruction = get_process_analyst_instruction(governance_context)

    def analyze_deal(self, teaser_text: str, use_native_tools: bool = True) -> dict[str, Any]:
        """Complete deal analysis including process path determination."""
        self.tracer.record("ProcessAnalyst", "START", "Beginning analysis")

        if use_native_tools:
            try:
                raw = self._run_analysis_native(teaser_text)
            except Exception as e:
                logger.warning("Native tools failed: %s", e)
                self.tracer.record("ProcessAnalyst", "FALLBACK", str(e))
                raw = self._run_analysis_text_based(teaser_text)
        else:
            raw = self._run_analysis_text_based(teaser_text)

        decision = self._extract_structured_decision(raw["full_analysis"])

        if decision:
            raw["process_path"] = decision.get("assessment_approach") or ""
            raw["origination_method"] = decision.get("origination_method") or ""
            raw["assessment_reasoning"] = decision.get("assessment_reasoning") or ""
            raw["origination_reasoning"] = decision.get("origination_reasoning") or ""
            raw["decision_found"] = bool(raw["process_path"] and raw["origination_method"])
            raw["decision_confidence"] = decision.get("confidence") or "MEDIUM"
            raw["fallback_used"] = False
        else:
            raw["process_path"] = ""
            raw["origination_method"] = ""
            raw["assessment_reasoning"] = ""
            raw["origination_reasoning"] = ""
            raw["decision_found"] = False
            raw["decision_confidence"] = "NONE"
            raw["fallback_used"] = False
            self.tracer.record("ProcessAnalyst", "WARNING", "No clear decision")

        self.tracer.record("ProcessAnalyst", "COMPLETE", f"Analysis: {raw['process_path']}")
        return raw

    def discover_requirements(
        self, analysis_text: str, assessment_approach: str, origination_method: str
    ) -> list[dict]:
        """Discover dynamic requirements."""
        self.tracer.record("RequirementsDiscovery", "START", "Discovering requirements")

        procedure_rag_context = self._search_procedure_for_requirements(
            origination_method, assessment_approach
        )
        governance_categories = self._build_governance_categories_hint()

        # The analysis text can be 15K+ chars. The LLM needs to see the
        # COMPREHENSIVE EXTRACTION section (which contains extracted data values)
        # and the RESULT_JSON section (at the end). Send a generous portion.
        # If too long, take first 5000 + last 5000 to cover both context and data.
        if len(analysis_text) > 10000:
            analysis_for_prompt = (
                analysis_text[:5000]
                + "\n\n[... middle section omitted for brevity ...]\n\n"
                + analysis_text[-5000:]
            )
        else:
            analysis_for_prompt = analysis_text

        prompt = REQUIREMENTS_DISCOVERY_PROMPT.format(
            analysis_text=analysis_for_prompt,
            assessment_approach=assessment_approach or "assessment",
            origination_method=origination_method or "origination",
            procedure_rag_context=procedure_rag_context,
            governance_categories=governance_categories,
        )

        result = call_llm(
            prompt, MODEL_PRO, 0.0, 8000,
            "RequirementsDiscovery", self.tracer,
            thinking_budget=THINKING_BUDGET_LIGHT
        )

        if not result.success:
            self.tracer.record("RequirementsDiscovery", "FAIL", result.error or "Unknown")
            return []

        parsed = safe_extract_json(result.text, "object")
        if not parsed or "requirements" not in parsed:
            return []

        requirements = parsed["requirements"]
        if not isinstance(requirements, list):
            return []

        ui_requirements = []
        filled_count = 0
        for req in requirements:
            if isinstance(req, dict):
                # Use LLM-provided value/status if available
                value = req.get("value", "").strip() if isinstance(req.get("value"), str) else ""
                status = "filled" if value else "empty"
                # Also respect explicit status from LLM
                if req.get("status") == "filled" and value:
                    status = "filled"
                elif req.get("status") == "empty":
                    status = "empty"
                    value = ""

                if status == "filled":
                    filled_count += 1

                ui_requirements.append({
                    "name": req.get("name", "Unknown"),
                    "category": req.get("category", "General"),
                    "description": req.get("description", ""),
                    "required": req.get("required", True),
                    "value": value,
                    "status": status,
                    "source_hint": req.get("source_hint", ""),
                    "procedure_ref": req.get("procedure_ref", ""),
                })

        self.tracer.record(
            "RequirementsDiscovery", "COMPLETE",
            f"Found {len(ui_requirements)} reqs, {filled_count} pre-filled from analysis"
        )
        return ui_requirements

    def _run_analysis_native(self, teaser_text: str) -> dict[str, Any]:
        """Native function calling."""
        from tools.function_declarations import get_agent_tools, create_tool_executor

        tools = get_agent_tools("ProcessAnalyst", governance_context=self.governance_context)
        if not tools:
            raise RuntimeError("No native tools")

        executor = create_tool_executor(
            search_procedure_fn=self.search_procedure_fn,
            search_guidelines_fn=lambda q, n=3: {"status": "ERROR", "results": []},
            search_rag_fn=lambda q, n=3: {"status": "ERROR", "results": []},
        )

        prompt = f"""{self.instruction}

## TEASER DOCUMENT
{teaser_text}

## TASK
Analyze and determine assessment approach and origination method.
Search Procedure document AT LEAST 3 TIMES before recommending.
"""

        result = call_llm_with_tools(
            prompt=prompt,
            tools=tools,
            tool_executor=executor,
            model=AGENT_MODELS.get("process_analyst", MODEL_FLASH),
            temperature=0.0,
            max_tokens=16000,
            agent_name="ProcessAnalyst",
            max_tool_rounds=5,
            tracer=self.tracer,
            thinking_budget=THINKING_BUDGET_LIGHT,
        )

        return {"full_analysis": result.text, "procedure_sources": {}}

    def _run_analysis_text_based(self, teaser_text: str) -> dict[str, Any]:
        """Text-based fallback."""
        planning_prompt = f"""{self.instruction}

## TEASER
{teaser_text[:3000]}

## STEP 1: Plan searches
<TOOL>search_procedure: "your query"</TOOL>
"""

        planning = call_llm(
            planning_prompt, MODEL_FLASH, 0.0, 2000,
            "ProcessAnalyst", self.tracer,
            thinking_budget=THINKING_BUDGET_LIGHT
        )

        if not planning.success:
            return {"full_analysis": f"[Failed: {planning.error}]", "procedure_sources": {}}

        tool_calls = parse_tool_calls(planning.text, "search_procedure")

        procedure_results: dict[str, Any] = {}
        for query in tool_calls[:5]:
            self.tracer.record("ProcessAnalyst", "RAG_SEARCH", f"Proc: {query[:60]}")
            try:
                procedure_results[query] = self.search_procedure_fn(query, 4)
            except Exception as e:
                logger.warning("Search failed: %s", e)
                procedure_results[query] = {"status": "ERROR", "results": []}

        rag_context = format_rag_results(procedure_results)

        analysis_prompt = f"""{self.instruction}

## TEASER
{teaser_text}

## PROCEDURE RESULTS
{rag_context}

## TASK
Produce FULL analysis with assessment approach and origination method.
"""

        analysis = call_llm(
            analysis_prompt, AGENT_MODELS.get("process_analyst", MODEL_FLASH),
            0.0, 16000, "ProcessAnalyst", self.tracer,
            thinking_budget=THINKING_BUDGET_STANDARD
        )

        if not analysis.success:
            return {"full_analysis": f"[Failed: {analysis.error}]", "procedure_sources": {}}

        return {"full_analysis": analysis.text, "procedure_sources": procedure_results}

    def _extract_structured_decision(self, analysis_text: str) -> dict[str, Any] | None:
        """Extract decision from analysis text.

        Strategy:
        1. Try direct extraction from <RESULT_JSON> tags (fast, no LLM call)
        2. Fall back to LLM extraction, but include the TAIL of the analysis
           (where RESULT_JSON lives) rather than just the first 8000 chars
        """
        self.tracer.record("ProcessAnalyst", "EXTRACTION", "Extracting decision")

        # --- Method 1: Direct extraction from <RESULT_JSON> tags ---
        import re
        result_json_match = re.search(
            r'<RESULT_JSON>\s*([\s\S]*?)\s*</RESULT_JSON>',
            analysis_text,
            re.IGNORECASE
        )
        if result_json_match:
            json_text = result_json_match.group(1).strip()
            parsed = safe_extract_json(json_text, "object")
            normalized = _normalize_decision_dict(parsed)
            if normalized:
                logger.info(
                    "Decision extracted directly from RESULT_JSON: approach=%s, method=%s",
                    normalized.get("assessment_approach", "?"),
                    normalized.get("origination_method", "?"),
                )
                self.tracer.record(
                    "ProcessAnalyst",
                    "EXTRACTION_OK",
                    "Direct from RESULT_JSON tags",
                )
                return normalized
            # RESULT_JSON present but unusable
            self.tracer.record(
                "ProcessAnalyst",
                "EXTRACTION_WARNING",
                "RESULT_JSON present but could not be normalized",
            )

        # --- Method 2: LLM extraction fallback ---
        # Include both the beginning (context) and the end (where RESULT_JSON usually is)
        # to avoid truncating the decision block
        if len(analysis_text) > 8000:
            # Take first 4000 chars (context) + last 4000 chars (decision)
            truncated = analysis_text[:4000] + "\n\n[... middle truncated ...]\n\n" + analysis_text[-4000:]
        else:
            truncated = analysis_text

        prompt = PROCESS_DECISION_EXTRACTION_PROMPT.format(analysis_text=truncated)

        result = call_llm(
            prompt, MODEL_FLASH, 0.0, 1500,
            "ProcessAnalyst", self.tracer,
            thinking_budget=THINKING_BUDGET_NONE
        )

        if not result.success:
            self.tracer.record(
                "ProcessAnalyst",
                "EXTRACTION_WARNING",
                f"LLM decision extraction failed: {result.error or 'unknown error'}",
            )
            return None

        parsed = safe_extract_json(result.text, "object")
        normalized = _normalize_decision_dict(parsed)
        if not normalized:
            self.tracer.record(
                "ProcessAnalyst",
                "EXTRACTION_WARNING",
                "LLM decision JSON could not be normalized",
            )
            return None

        self.tracer.record(
            "ProcessAnalyst",
            "EXTRACTION_OK",
            "Decision extracted via LLM fallback",
        )
        return normalized

    def _search_procedure_for_requirements(self, origination_method: str, assessment_approach: str) -> str:
        """Search for requirements."""
        if not self.search_procedure_fn:
            return "(No Procedure context)"

        rag_queries = [
            f"information requirements for {origination_method}",
            f"required data fields {assessment_approach} assessment",
        ]

        rag_results: dict[str, Any] = {}
        for query in rag_queries:
            try:
                rag_results[query] = self.search_procedure_fn(query, 3)
            except Exception:
                pass

        return format_rag_results(rag_results) if rag_results else "(No results)"

    def _build_governance_categories_hint(self) -> str:
        """Build governance categories hint."""
        if not self.governance_context:
            return ""

        if self.governance_context.get("discovery_status") not in ("complete", "partial"):
            return ""

        cats = self.governance_context.get("requirement_categories", [])
        if not cats:
            return ""

        return f"""
## DISCOVERED REQUIREMENT CATEGORIES
{chr(10).join(f"- {cat}" for cat in cats)}
"""
