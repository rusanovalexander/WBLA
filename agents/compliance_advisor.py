"""
Compliance Advisor Agent - DOCUMENT-DRIVEN VERSION

Key changes:
- Instruction is now a function: get_compliance_advisor_instruction(governance_context)
- Compliance search areas, matrix categories, and search examples are parameterized
- Falls back to sensible defaults when governance context is not available
"""

from __future__ import annotations
from typing import Any

from config.settings import AGENT_MODELS, AGENT_TEMPERATURES, get_verbose_block


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
| [criterion name] | [MUST/SHOULD] [limit from RAG] | [value from deal data] | ✅/⚠️/❌ | "[source quote]" | [Section ref from RAG] |

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
| [criterion name] | [MUST/SHOULD] [limit from RAG] | [value from deal data] | ✅/⚠️/❌ | "[source quote]" | [Section ref from RAG] |

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
You are the **Compliance Advisor Agent** for a credit pack drafting system.

<ROLE>
You are an expert in lending guidelines and regulatory compliance. Your job is to:
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
    )


# Backward-compatible constant (uses defaults when no governance context)
COMPLIANCE_ADVISOR_INSTRUCTION = get_compliance_advisor_instruction(None)


# Create agent config dict
compliance_advisor_config = {
    "name": "ComplianceAdvisorAgent",
    "model": AGENT_MODELS["compliance_advisor"],
    "instruction": COMPLIANCE_ADVISOR_INSTRUCTION,
    "temperature": AGENT_TEMPERATURES["compliance_advisor"],
    "tools": ["tool_search_guidelines", "tool_search_procedure", "tool_load_document"],
}
