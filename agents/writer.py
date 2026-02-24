"""
Writer Agent - DOCUMENT-DRIVEN VERSION

Key changes:
- Instruction is now a function: get_writer_instruction(governance_context)
- Section-type content guidance is parameterized from governance context
- Falls back to sensible defaults when governance context is not available
"""

from __future__ import annotations
import re
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

**Tables:** Use tables for numerical data, comparisons, key metrics.
ALWAYS format tables using markdown pipe syntax — NEVER use tab-separated columns:
| Header 1 | Header 2 | Header 3 |
|----------|----------|----------|
| Value 1  | Value 2  | Value 3  |

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
# Draft Content Extraction — strip internal scaffolding
# =============================================================================

def _extract_clean_draft(raw_text: str) -> tuple[str, str, str]:
    """
    Extract only the publishable content from the LLM's raw draft output.

    The Writer LLM outputs three clearly-delimited blocks:
        🧠 THINKING  ...
        📝 DRAFTED SECTION  ...
        📋 SECTION METADATA  ...

    We want ONLY the content between the DRAFTED SECTION and SECTION METADATA
    markers.  Everything else is internal audit data and must never appear in
    the exported DOCX.

    Returns:
        (clean_content, thinking_notes, section_metadata)
        If the markers are absent the whole text is treated as clean content
        (graceful degradation for older prompts / models that skip them).
    """
    # Patterns for the three delimiters (emoji + text variants)
    drafted_pattern = re.compile(
        r"(?:📝\s*DRAFTED\s*SECTION|DRAFTED\s*SECTION)",
        re.IGNORECASE,
    )
    metadata_pattern = re.compile(
        r"(?:📋\s*SECTION\s*METADATA|SECTION\s*METADATA)",
        re.IGNORECASE,
    )
    thinking_pattern = re.compile(
        r"(?:🧠\s*THINKING|THINKING)",
        re.IGNORECASE,
    )

    thinking_notes = ""
    section_metadata = ""
    clean_content = raw_text

    drafted_match = drafted_pattern.search(raw_text)
    metadata_match = metadata_pattern.search(raw_text)

    if drafted_match:
        # Extract content between DRAFTED SECTION and SECTION METADATA (or end)
        start = drafted_match.end()
        end = metadata_match.start() if metadata_match else len(raw_text)
        clean_content = raw_text[start:end].strip()

        # Extract thinking notes (everything before DRAFTED SECTION)
        thinking_section = raw_text[:drafted_match.start()]
        # Strip the leading THINKING header if present
        thinking_match = thinking_pattern.search(thinking_section)
        if thinking_match:
            thinking_notes = thinking_section[thinking_match.end():].strip()
        else:
            thinking_notes = thinking_section.strip()

        # Extract metadata (everything after SECTION METADATA)
        if metadata_match:
            section_metadata = raw_text[metadata_match.end():].strip()

    return clean_content, thinking_notes, section_metadata


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
        on_stream: Callable[[str], None] | None = None,
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

        if on_stream:
            result = call_llm_streaming(
                prompt, MODEL_PRO, 0.0, 4000,
                "Writer",
                on_chunk=on_stream,
                tracer=self.tracer,
                thinking_budget=THINKING_BUDGET_LIGHT,
            )
        else:
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
        on_stream: Callable[[str], None] | None = None,
        on_thinking: Callable[[str], None] | None = None,
    ) -> SectionDraft:
        """Draft a document section.

        This method can optionally trigger a lightweight review sub-task with
        ComplianceAdvisor for sections where compliance reinforcement is
        valuable (e.g., compliance/risk sections). The review does not block
        drafting but augments the draft content when successful.
        """
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
        user_additions_summary = context.get("user_additions_summary", "")  # User-requested additions
        identified_gaps = context.get("identified_gaps", [])  # Confirmed gaps from analysis step

        # Separate requirements into filled vs empty
        req_list = requirements if isinstance(requirements, list) else []
        filled_reqs = [r for r in req_list if r.get("value") or r.get("status") == "filled"]
        empty_reqs = [r for r in req_list if r.get("required") and not r.get("value")]

        # Format filled requirements
        filled_context = format_requirements_for_context(filled_reqs)

        # Build empty requirements block — Writer uses this to place precise [INFORMATION REQUIRED] markers
        empty_context = ""
        if empty_reqs:
            lines = []
            for r in empty_reqs:
                hint = r.get("source_hint", "not in documents")
                ref = f" [{r['procedure_ref']}]" if r.get("procedure_ref") else ""
                lines.append(f"- **{r['name']}**: {hint}{ref}")
            # Also add any analysis-time identified gaps not already in empty_reqs
            empty_names = {r.get("name", "") for r in empty_reqs}
            for g in identified_gaps:
                gname = g.get("name", "")
                if gname and gname not in empty_names:
                    rec = f" — {g['recommendation']}" if g.get("recommendation") else ""
                    lines.append(f"- **{gname}** (confirmed gap from analysis{rec})")
            empty_context = "\n".join(lines)

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

        # 🆕 C1 FIX: Query other agents for additional context if needed
        agent_insights = ""
        if self.agent_bus:
            agent_insights = self._query_agents_for_section(section_name, context)

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

{f"### Unfilled Requirements (use [INFORMATION REQUIRED: name] for each):{chr(10)}{empty_context}" if empty_context else ""}

### Compliance Assessment:
{compliance_result}

{f"### Supplementary Documents:{supplement_context}" if supplement_context else ""}

{previously_context}

{f"### Agent Insights (from ProcessAnalyst and ComplianceAdvisor):{agent_insights}" if agent_insights else ""}

{f"### USER REQUESTED ADDITIONS (MANDATORY — incorporate these into this section):\n{user_additions_summary}" if user_additions_summary else ""}

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
            on_chunk=on_stream,
        )

        if result.thinking and on_thinking:
            on_thinking(result.thinking)

        thinking_notes = ""
        section_metadata = ""
        compliance_review_notes = ""

        if not result.success:
            content = f"[SECTION PENDING — Drafting could not be completed ({result.error}). Please re-draft this section.]"
            self.tracer.record("Writer", "DRAFT_FAIL", result.error or "Unknown")
        else:
            # Strip internal scaffolding — keep only the publishable content
            content, thinking_notes, section_metadata = _extract_clean_draft(result.text)
            self.tracer.record("Writer", "DRAFT_COMPLETE", f"Drafted {len(content)} chars")

        # Optional post-draft compliance review loop — store notes separately,
        # never appended to the publishable content
        if self.agent_bus and self._section_needs_compliance_input(section_name.lower()):
            try:
                review_summary = self._run_compliance_review_subtask(section_name, content, context)
                if review_summary:
                    compliance_review_notes = review_summary
            except Exception as e:
                # Do not fail the draft if the review loop has issues
                logger.debug("Compliance review sub-task failed: %s", e)

        return SectionDraft(
            name=section_name,
            content=content,
            thinking_notes=thinking_notes,
            section_metadata=section_metadata,
            compliance_review_notes=compliance_review_notes,
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

    # =========================================================================
    # C1 FIX: Agent-to-Agent Communication
    # =========================================================================

    def _query_agents_for_section(self, section_name: str, context: dict) -> str:
        """
        Query other agents for additional context when drafting sections.

        This implements the agent communication feature (C1 fix).
        """
        if not self.agent_bus:
            return ""

        insights = []
        section_lower = section_name.lower()

        # Query ProcessAnalyst for risk/deal-specific insights
        if self._section_needs_analyst_input(section_lower):
            try:
                query = self._build_analyst_query(section_lower)
                response = self.agent_bus.query(
                    from_agent="Writer",
                    to_agent="ProcessAnalyst",
                    query=query,
                    context=context
                )
                if response and not response.startswith("[Agent"):
                    insights.append(f"\n**ProcessAnalyst Input:**\n{response}")
            except Exception as e:
                # Silent failure - don't block drafting if query fails
                pass

        # Query ComplianceAdvisor for compliance/guideline insights
        if self._section_needs_compliance_input(section_lower):
            try:
                query = self._build_compliance_query(section_lower)
                response = self.agent_bus.query(
                    from_agent="Writer",
                    to_agent="ComplianceAdvisor",
                    query=query,
                    context=context
                )
                if response and not response.startswith("[Agent"):
                    insights.append(f"\n**ComplianceAdvisor Input:**\n{response}")
            except Exception as e:
                # Silent failure
                pass

        return "\n".join(insights) if insights else ""

    def _section_needs_analyst_input(self, section_name: str) -> bool:
        """Check if section should query ProcessAnalyst."""
        # Sections that benefit from ProcessAnalyst input
        analyst_keywords = [
            "executive", "summary", "risk", "assessment",
            "analysis", "deal", "structure", "background",
            "overview", "key features"
        ]
        return any(kw in section_name for kw in analyst_keywords)

    def _section_needs_compliance_input(self, section_name: str) -> bool:
        """Check if section should query ComplianceAdvisor."""
        # Sections that benefit from ComplianceAdvisor input
        compliance_keywords = [
            "compliance", "regulatory", "guidelines",
            "policy", "requirements", "framework",
            "legal", "governance"
        ]
        return any(kw in section_name for kw in compliance_keywords)

    def _build_analyst_query(self, section_name: str) -> str:
        """Build query for ProcessAnalyst based on section type."""
        if "risk" in section_name:
            return "What are the 2-3 most critical risks for this deal that should be highlighted?"
        elif "executive" in section_name or "summary" in section_name:
            return "What are the key highlights and critical considerations for this deal?"
        elif "structure" in section_name:
            return "Describe the deal structure and key financial terms."
        else:
            return f"What key information should be included in the '{section_name}' section?"

    def _build_compliance_query(self, section_name: str) -> str:
        """Build query for ComplianceAdvisor based on section type."""
        if "compliance" in section_name:
            return "What are the key compliance considerations and any policy exceptions for this deal?"
        elif "guideline" in section_name or "framework" in section_name:
            return "What guidelines and frameworks apply to this deal?"
        else:
            return f"Are there any compliance notes relevant to the '{section_name}' section?"

    def _run_compliance_review_subtask(
        self,
        section_name: str,
        draft_content: str,
        context: dict[str, Any],
    ) -> str:
        """
        Run a focused compliance review sub-task on the drafted section.

        This uses the agent bus to ask ComplianceAdvisor to highlight
        potential issues or confirm alignment with guidelines for the
        specific section content.
        """
        if not self.agent_bus:
            return ""

        query = (
            f"Please review the drafted '{section_name}' section for compliance. "
            f"Identify any potential guideline breaches, missing mandatory "
            f"statements, or places where the language should be strengthened "
            f"from a policy perspective. If everything is aligned, state that "
            f"explicitly.\n\nDraft content:\n{draft_content[:6000]}"
        )

        response = self.agent_bus.query(
            from_agent="Writer",
            to_agent="ComplianceAdvisor",
            query=query,
            context=context,
        )
        # Avoid echoing technical error messages into the draft
        if response.startswith("[Agent"):
            return ""
        return response.strip()
