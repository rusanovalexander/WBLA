"""
Process Analyst Agent - DOCUMENT-DRIVEN VERSION

Key changes:
- Instruction is now a function: get_process_analyst_instruction(governance_context)
- Search vocabulary, extraction sections, and risk taxonomy are parameterized
- Falls back to sensible defaults when governance context is not available
"""

from __future__ import annotations
from typing import Any

from config.settings import AGENT_MODELS, AGENT_TEMPERATURES, get_verbose_block


def _build_search_vocabulary(governance_context: dict[str, Any] | None) -> str:
    """Build search vocabulary hints from governance context or defaults."""
    if governance_context and governance_context.get("search_vocabulary"):
        vocab = governance_context["search_vocabulary"]
        return "\n".join(f"- {term}" for term in vocab[:8])
    return (
        "- Assessment approach decision criteria and thresholds\n"
        "- Available assessment approaches and when each applies\n"
        "- Credit origination methods and their requirements\n"
        "- Decision trees and threshold criteria\n"
        "- Special rules for specific deal types"
    )


def _build_extraction_sections(governance_context: dict[str, Any] | None) -> str:
    """Build extraction section suggestions from governance context or defaults."""
    if governance_context and governance_context.get("requirement_categories"):
        cats = governance_context["requirement_categories"]
        return "\n".join(f"- {cat}" for cat in cats)
    return (
        "- Deal Structure\n"
        "- Borrower and Structure\n"
        "- Sponsor Information (if applicable)\n"
        "- Asset Characteristics\n"
        "- Financial Metrics\n"
        "- Security Package\n"
        "- Transaction Context\n"
        "- Identified Gaps"
    )


def _build_risk_taxonomy(governance_context: dict[str, Any] | None) -> str:
    """Build risk assessment template from governance context or defaults."""
    if governance_context and governance_context.get("risk_taxonomy"):
        cats = governance_context["risk_taxonomy"]
    else:
        cats = ["Credit Risk", "Market Risk", "Operational Risk", "Structural Risk"]
    lines = []
    for cat in cats:
        lines.append(f"**{cat}:**")
        lines.append(f"- [Key {cat.lower()} factors]")
        lines.append(f"- [Initial assessment]\n")
    return "\n".join(lines)


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
                f'"The facility amount is EUR 50 million" [HIGH CONFIDENCE] '
                f'[Source: "senior facility of EUR 50 million"]. '
                f"Mark missing information as NOT STATED.]\n"
            )
        return "\n".join(lines)

    # Domain-neutral structural example — demonstrates format without CRE bias
    return """**Example Extraction (generic structure):**

### DEAL STRUCTURE

The transaction is a [currency] [amount] [facility type] with a [tenor] [HIGH CONFIDENCE] [Source: "exact quote from teaser"]. The purpose is [purpose description] [HIGH CONFIDENCE] [Source: "exact quote"]. Pricing is [benchmark] plus [margin] basis points [HIGH CONFIDENCE] [Source: "exact quote"].

### BORROWER AND STRUCTURE

The borrower is [entity name], a [entity type] [HIGH CONFIDENCE] [Source: "exact quote"]. The ultimate beneficial owner is [owner details] [HIGH CONFIDENCE] [Source: "exact quote"]. This is a [new/existing] client relationship [MEDIUM CONFIDENCE] [Inferred: reasoning].

### FINANCIAL METRICS

**Key Ratios:**
- [Metric 1]: [value] [HIGH CONFIDENCE] [Source: "exact quote"]
- [Metric 2]: [value] [HIGH CONFIDENCE] [Calculated: methodology]
- [Metric 3]: [value] [MEDIUM CONFIDENCE] [Estimated: reasoning]

### SECURITY PACKAGE

The facility is secured by [collateral description] [HIGH CONFIDENCE] [Source: "exact quote"].
[Additional security items with source attribution]

### IDENTIFIED GAPS

**Information NOT stated in the teaser:**
- [Missing item 1] [NOT STATED]
- [Missing item 2] [NOT STATED]
"""


_PROCESS_ANALYST_TEMPLATE = """
You are the **Process Analyst Agent** for a credit pack drafting system.

<ROLE>
You are an expert in credit processes and procedures. Your job is to:
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
2. Search for credit assessment approaches (how to determine which assessment is needed)
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
<TOOL>search_procedure: "credit origination methods"</TOOL>

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

The goal is a thorough analysis that reads like a credit analyst's memo, not a database dump.

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
