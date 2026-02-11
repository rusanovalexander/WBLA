"""
Writer Agent - DOCUMENT-DRIVEN VERSION

Key changes:
- Instruction is now a function: get_writer_instruction(governance_context)
- Section-type content guidance is parameterized from governance context
- Falls back to sensible defaults when governance context is not available
"""

from __future__ import annotations
from typing import Any

from config.settings import AGENT_MODELS, AGENT_TEMPERATURES, get_verbose_block, PRODUCT_NAME, PRODUCT_ROLE, PRODUCT_AUDIENCE


def _build_section_type_guidance(governance_context: dict[str, Any] | None) -> str:
    """Build section-type content guidance from governance context or defaults."""
    if governance_context and governance_context.get("section_templates"):
        templates = governance_context["section_templates"]
        lines = []
        for method, sections in templates.items():
            if isinstance(sections, list) and sections:
                for sec in sections[:12]:
                    name = sec.get("name", "")
                    desc = sec.get("description", "")
                    if name and desc:
                        lines.append(f"- {name} sections → {desc}")
        if lines:
            return "\n".join(lines)

    # Default: generic guidance that works for any deal type
    return (
        "Adapt the writing style to each section's purpose:\n"
        "- Introductory/summary sections → lead with key conclusions, then supporting detail\n"
        "- Analytical sections → present data, then interpretation and implications\n"
        "- Assessment sections → state findings, evidence, and recommendations\n"
        "- Descriptive sections → relevant characteristics, context, and significance\n"
        "Match the structure to what the section title implies about its content."
    )


def _build_writing_conventions(governance_context: dict[str, Any] | None) -> str:
    """Build writing conventions from governance context or generic defaults."""
    if governance_context and governance_context.get("writing_conventions"):
        conventions = governance_context["writing_conventions"]
        if isinstance(conventions, list):
            return "\n".join(f"- {c}" for c in conventions)
        return str(conventions)

    # Generic professional writing conventions (no domain-specific language rules)
    return (
        "- Use formal third-person references (entity names, not pronouns)\n"
        "- Use professional, proposal-style language\n"
        "- Active voice where appropriate\n"
        "- Clear, concise sentences"
    )


_WRITER_TEMPLATE = """
You are the **Writer Agent** ({product_role}) for a {product_name} drafting system.

<ROLE>
You are an expert in writing professional documentation. Your job is to:
1. Draft {product_name} sections in professional language appropriate for {product_audience}
2. Use the EXAMPLE for style and structure ONLY
3. Use TEASER and PROVIDED DATA for ALL facts
4. Mark missing information clearly with [INFORMATION REQUIRED: ...]
5. Incorporate compliance notes where relevant
</ROLE>

<CRITICAL_RULES>
⚠️ THESE RULES ARE ABSOLUTE - NEVER VIOLATE:

**Rule 1: EXAMPLE = STYLE ONLY**
- Use example document ONLY for style, tone, and structure
- NEVER copy facts, figures, names, or content from example
- The example shows HOW to write, not WHAT to write

**Rule 2: DATA = FROM CONTEXT ONLY**
- ALL facts must come from: teaser, extracted data, filled requirements, compliance result
- You have COMPLETE context - no truncation
- If something is not in your context, it's genuinely missing

**Rule 3: NO INVENTION**
- NEVER invent or assume facts
- If information is missing, mark it: **[INFORMATION REQUIRED: description]**
- Do not guess values, dates, or names

**Rule 4: CITE SOURCES**
- Every fact should be traceable to source
- Use: "per teaser", "as extracted", "per compliance assessment"

**Rule 5: PRECISION**
- Use exact values, not approximations
- Exact names, exact figures, exact dates
</CRITICAL_RULES>

<LEVEL3_AGENT_QUERIES>
You receive COMPLETE context from all previous phases:
- Full teaser text
- Full extracted data analysis
- All filled requirements
- Full compliance assessment
- All supplementary documents

You should have everything you need. However, if something is GENUINELY unclear or ambiguous, you can query other agents:

**Query Syntax:**
<AGENT_QUERY to="ProcessAnalyst">Your specific question about teaser data</AGENT_QUERY>
<AGENT_QUERY to="ComplianceAdvisor">Your specific question about guidelines</AGENT_QUERY>

**When to Query:**
- You need specific section/paragraph citations from Guidelines or Procedure
- Compliance flagged something as "REVIEW" and you need specifics on thresholds
- Process reasoning would strengthen your methodology narrative
- Teaser mentions something ambiguous that needs clarification
- A compliance limit is mentioned but not the specific value
- You want to validate an unusual deal characteristic

**Example Queries:**

SCENARIO: Compliance shows "Leverage: ⚠️ REVIEW"
<AGENT_QUERY to="ComplianceAdvisor">What is the specific leverage threshold from the Guidelines that triggered the REVIEW flag for this deal?</AGENT_QUERY>

SCENARIO: Drafting Risk Analysis section
<AGENT_QUERY to="ComplianceAdvisor">What are the key compliance risks identified in your assessment that I should highlight?</AGENT_QUERY>

SCENARIO: Drafting Process Methodology section
<AGENT_QUERY to="ProcessAnalyst">Can you explain why Standard Assessment was chosen over Fast Track for this deal?</AGENT_QUERY>

**When NOT to Query:**
- You just want confirmation of data you already have
- The information is clearly stated in your context
</LEVEL3_AGENT_QUERIES>

<WRITING_PRINCIPLES>
**Tone:** Professional, objective, analytical - appropriate for {product_audience}

**Structure:** Follow the example's section organization and flow

**Content:** Based ONLY on teaser facts and provided data

**Length:** Match the detail level specified (Brief/Standard/Detailed)

**Language Conventions:**
{writing_conventions}

**Tables:** Use tables for numerical data, comparisons, key metrics

**Compliance Integration:** Reference compliance findings where relevant
</WRITING_PRINCIPLES>

<SECTION_WRITING_APPROACH>
You will receive a specific section to draft, with:
- **name**: The section title
- **description**: What THIS section should cover for THIS deal
- **detail_level**: "Brief" (0.5-1 page), "Standard" (1-2 pages), or "Detailed" (2-4 pages)

**How to write ANY section:**

1. Read the section description — it tells you what this section needs
2. Look at the example document for how similar sections are structured and toned
3. Pull ALL relevant facts from your context (teaser, requirements, compliance)
4. Structure with clear sub-headings (##, ###)
5. Use tables for numerical comparisons, key metrics, covenant packages
6. End with a clear takeaway or assessment where appropriate
7. Mark gaps: **[INFORMATION REQUIRED: what's missing]**

**For common section types, typical content includes:**
{section_type_guidance}

**For deal-specific sections:**
- Use the section description as your primary guide
- Draw on relevant data from teaser and requirements
- Structure logically for the topic
- Apply the same professional tone
</SECTION_WRITING_APPROACH>

{verbose_block}

<OUTPUT_STRUCTURE>
Structure your response as:

---

### 🧠 THINKING

**Section Understanding:**
- This section should cover: [what the section is about]
- From the example, the structure is: [structure notes]
- Expected length/detail level: [assessment]

**Available Data (from my context):**
- For this section, I have: [list key data points]
- From teaser: [relevant teaser facts]
- From extracted data: [relevant extracted data]
- From compliance: [relevant compliance findings]
- From requirements: [relevant filled requirements]

**Missing Information:**
- Not in my context: [list what's genuinely missing]
- Will mark as [INFORMATION REQUIRED: ...]

**Compliance Considerations:**
- Relevant compliance notes to incorporate: [if any]

---

### 📝 DRAFTED SECTION

## [SECTION NAME]

[Professional content here]

[Use facts from teaser/data - never from example]

[Tables for numerical data]

[Mark any gaps as: **[INFORMATION REQUIRED: specific info needed]**]

---

### 📋 SECTION METADATA

**Facts Used:**
| Fact | Source | Quote |
|------|--------|-------|
| [fact 1] | teaser/extracted/compliance | "[quote]" |
| [fact 2] | teaser/extracted/compliance | "[quote]" |

**Marked as Missing:**
- [Item 1] - needed for [reason]
- [Item 2] - needed for [reason]

**Compliance Notes Incorporated:**
- [Note if any]

**Agent Queries Made (if any):**
- [Query and response summary]

---

</OUTPUT_STRUCTURE>

<TOOLS>
You have access to:
- <AGENT_QUERY to="ProcessAnalyst">question</AGENT_QUERY> - Query Process Analyst for teaser clarification
- <AGENT_QUERY to="ComplianceAdvisor">question</AGENT_QUERY> - Query Compliance Advisor for guideline context
- tool_load_document: Load documents if needed

Remember: Agent queries should be RARE - you have full context.
</TOOLS>
"""


def get_writer_instruction(governance_context: dict[str, Any] | None = None) -> str:
    """Build Writer instruction with governance-derived parameters."""
    return _WRITER_TEMPLATE.format(
        section_type_guidance=_build_section_type_guidance(governance_context),
        writing_conventions=_build_writing_conventions(governance_context),
        verbose_block=get_verbose_block(),
        product_name=PRODUCT_NAME,
        product_role=PRODUCT_ROLE,
        product_audience=PRODUCT_AUDIENCE,
    )


# Backward-compatible constant (uses defaults when no governance context)
WRITER_INSTRUCTION = get_writer_instruction(None)


# Create agent config dict
writer_config = {
    "name": "WriterAgent",
    "model": AGENT_MODELS["writer"],
    "instruction": WRITER_INSTRUCTION,
    "temperature": AGENT_TEMPERATURES["writer"],
    "tools": ["tool_load_document"],
}
# This will be appended to agents/writer.py

# =============================================================================
# Writer Class (NEW - Phase 1.3 Consolidation)
# =============================================================================

"""
Writer consolidates document drafting logic:
- StructureGen (section structure generation)
- Section drafting

Single entry point: generate_structure() + draft_section()
"""

import logging
from typing import Any, Callable
from config.settings import MODEL_PRO, MODEL_FLASH, AGENT_MODELS, THINKING_BUDGET_NONE, THINKING_BUDGET_LIGHT, THINKING_BUDGET_STANDARD
from core.llm_client import call_llm, call_llm_streaming
from core.tracing import TraceStore, get_tracer
from core.parsers import format_rag_results, format_requirements_for_context, safe_extract_json
from models.schemas import SectionDraft
import json

logger = logging.getLogger(__name__)


# =============================================================================
# Structure Generation Prompt
# =============================================================================

STRUCTURE_GENERATION_PROMPT = """Determine the section structure for this {product_name}.

## PROCESS PATH
Assessment Approach: {assessment_approach}
Origination Method: {origination_method}

## PROCEDURE CONTEXT
{procedure_sections_context}

{gov_sections_str}

## DEAL ANALYSIS
{analysis_text}

## EXAMPLE STRUCTURE (adapt as needed)
{example_sections}

## TASK
Output ONLY valid JSON with section structure:

<json_output>
{{
  "sections": [
    {{
      "name": "Section Name",
      "description": "What this section covers",
      "detail_level": "Standard"
    }}
  ]
}}
</json_output>

Rules:
- Adapt sections to this specific deal and process path
- Use Procedure context for required sections
- Include 4-8 sections minimum
- Output ONLY JSON between tags
"""


class Writer:
    """
    Writer Agent - handles document structure generation and section drafting.
    """

    def __init__(
        self,
        search_procedure_fn: Callable | None = None,
        governance_context: dict[str, Any] | None = None,
        agent_bus: Any = None,
        tracer: TraceStore | None = None,
    ):
        self.search_procedure_fn = search_procedure_fn
        self.governance_context = governance_context
        self.agent_bus = agent_bus
        self.tracer = tracer or get_tracer()
        self.instruction = get_writer_instruction(governance_context)

    def generate_structure(
        self,
        example_text: str,
        assessment_approach: str,
        origination_method: str,
        analysis_text: str,
    ) -> list[dict]:
        """Generate document section structure."""
        self.tracer.record("Writer", "START_STRUCTURE", f"Generating structure for {origination_method}")

        # RAG search for section requirements
        procedure_sections_context = self._search_procedure_for_sections(
            origination_method, assessment_approach
        )

        # Governance templates
        gov_sections_str = self._build_governance_sections_hint(origination_method)

        # Extract example sections
        example_sections = self._extract_example_sections(example_text)

        # Generate structure
        from config.settings import PRODUCT_NAME
        prompt = STRUCTURE_GENERATION_PROMPT.format(
            product_name=PRODUCT_NAME,
            assessment_approach=assessment_approach or "assessment",
            origination_method=origination_method or "document",
            procedure_sections_context=procedure_sections_context,
            gov_sections_str=gov_sections_str,
            analysis_text=analysis_text[:2000],
            example_sections=example_sections,
        )

        result = call_llm(
            prompt, MODEL_PRO, 0.0, 4000,
            "Writer", self.tracer,
            thinking_budget=THINKING_BUDGET_LIGHT
        )

        if not result.success:
            self.tracer.record("Writer", "STRUCTURE_FAIL", result.error or "Unknown")
            return []

        parsed = safe_extract_json(result.text, "object")
        if parsed and "sections" in parsed:
            sections = parsed["sections"]
            if isinstance(sections, list):
                self.tracer.record("Writer", "STRUCTURE_COMPLETE", f"Generated {len(sections)} sections")
                return sections

        # Retry with simplified prompt
        self.tracer.record("Writer", "STRUCTURE_RETRY", "First attempt failed")
        retry_result = call_llm(
            "Generate section structure as JSON array with name, description fields",
            MODEL_FLASH, 0.0, 3000,
            "Writer", self.tracer,
            thinking_budget=THINKING_BUDGET_NONE
        )

        if retry_result.success:
            retry_parsed = safe_extract_json(retry_result.text, "array")
            if retry_parsed:
                return retry_parsed

        return []

    def draft_section(
        self,
        section: dict[str, str],
        context: dict[str, Any],
    ) -> SectionDraft:
        """Draft a document section."""
        section_name = section.get("name", "Section")
        self.tracer.record("Writer", "START_DRAFT", f"Drafting: {section_name}")

        # Extract context
        teaser_text = context.get("teaser_text", "")
        example_text = context.get("example_text", "")
        extracted_data = context.get("extracted_data", "")
        compliance_result = context.get("compliance_result", "")
        requirements = context.get("requirements", [])
        supplement_texts = context.get("supplement_texts", {})
        previously_drafted = context.get("previously_drafted", "")

        # Format requirements
        filled_context = format_requirements_for_context(
            requirements if isinstance(requirements, list) else []
        )

        # Format supplements
        supplement_context = ""
        if supplement_texts:
            for fname, ftext in supplement_texts.items():
                supplement_context += f"\n### Supplementary: {fname}\n{ftext[:3000]}\n"

        # Previously drafted
        previously_context = ""
        if previously_drafted:
            previously_context = f"""
### Previously Drafted Sections:
{previously_drafted[:6000]}
"""

        # Build prompt
        prompt = f"""{self.instruction}

## SECTION TO DRAFT: {section_name}

Description: {section.get('description', '')}
Detail Level: {section.get('detail_level', 'Standard')}

## COMPLETE CONTEXT

### Teaser Document:
{teaser_text}

### Extracted Data Analysis:
{extracted_data}

### Filled Requirements:
{filled_context}

### Compliance Assessment:
{compliance_result}

{f"### Supplementary Documents:{supplement_context}" if supplement_context else ""}

{previously_context}

### Example Document (STYLE REFERENCE ONLY):
{example_text}

## DRAFT THIS SECTION

Remember:
- Use example for STYLE only
- ALL facts from teaser/data/compliance
- Mark missing info as **[INFORMATION REQUIRED: description]**
- Be precise with figures and dates
- Use ## and ### for sub-headings
- Do NOT repeat previously drafted content
"""

        result = call_llm_streaming(
            prompt=prompt,
            model=AGENT_MODELS.get("writer", MODEL_PRO),
            temperature=0.3,
            max_tokens=8000,
            agent_name="Writer",
            tracer=self.tracer,
            thinking_budget=THINKING_BUDGET_STANDARD,
        )

        if not result.success:
            content = f"[Section drafting failed: {result.error}]"
            self.tracer.record("Writer", "DRAFT_FAIL", result.error or "Unknown")
        else:
            content = result.text
            self.tracer.record("Writer", "DRAFT_COMPLETE", f"Drafted {len(content)} chars")

        return SectionDraft(
            section_name=section_name,
            content=content,
            word_count=len(content.split()),
            requires_review=("[INFORMATION REQUIRED" in content or "[TO BE VERIFIED" in content),
        )

    def _search_procedure_for_sections(
        self, origination_method: str, assessment_approach: str
    ) -> str:
        """Search Procedure for section requirements."""
        if not self.search_procedure_fn:
            return "(No Procedure context)"

        om = origination_method or "document"
        aa = assessment_approach or "assessment"

        rag_queries = [
            f"required sections for {om} document",
            f"content structure {om} origination method",
            f"section requirements {aa} assessment approach",
        ]

        rag_results: dict[str, Any] = {}
        for query in rag_queries:
            self.tracer.record("Writer", "RAG_SEARCH", f"Proc: {query[:60]}")
            try:
                rag_results[query] = self.search_procedure_fn(query, 3)
            except Exception as e:
                logger.warning("Structure RAG query failed: %s", e)

        return format_rag_results(rag_results) if rag_results else "(No results)"

    def _build_governance_sections_hint(self, origination_method: str) -> str:
        """Build governance section templates hint."""
        if not self.governance_context:
            return ""

        if self.governance_context.get("discovery_status") not in ("complete", "partial"):
            return ""

        templates = self.governance_context.get("section_templates", {})
        om_key = origination_method or ""

        # Try exact match first
        matched_template = templates.get(om_key)
        if not matched_template:
            # Try partial match
            for key, val in templates.items():
                if key.lower() in om_key.lower() or om_key.lower() in key.lower():
                    matched_template = val
                    break

        if matched_template:
            return f"Procedure-defined sections for '{om_key}': " + json.dumps(matched_template, indent=2)

        return ""

    def _extract_example_sections(self, example_text: str) -> str:
        """Extract section names from example document."""
        if not example_text:
            return "(No example)"

        # Simple extraction: look for markdown headers
        lines = example_text.split('\n')
        sections = []
        for line in lines[:100]:  # First 100 lines
            if line.startswith('# ') or line.startswith('## '):
                sections.append(line.strip('# ').strip())

        if sections:
            return "Example sections: " + ", ".join(sections[:10])

        return "(No clear section structure in example)"
