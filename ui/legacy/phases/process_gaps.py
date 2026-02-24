"""
PROCESS_GAPS Phase - Requirements discovery and data collection

Extracted from app.py lines 515-1427
"""

import streamlit as st
from pathlib import Path
from datetime import datetime
import json
import logging
import os

from config.settings import *
from tools.document_loader import *
from tools.rag_search import *
from core.orchestration import *
from core.llm_client import *
from core.parsers import *
from core.governance_discovery import get_terminology_synonyms
from agents import *
from ui.utils.session_state import get_tracer, advance_phase

logger = logging.getLogger(__name__)

def render_phase_process_gaps():
    st.header("📝 Phase 2: Requirements & Gap Filling")

    if not st.session_state.process_requirements:
        with st.spinner("Discovering deal-specific requirements..."):
            tracer = get_tracer()

            # Dynamic discovery based on deal analysis and process path
            reqs = discover_requirements(
                analysis_text=st.session_state.extracted_data,
                assessment_approach=st.session_state.process_path,
                origination_method=st.session_state.origination_method,
                tracer=tracer,
                search_procedure_fn=tool_search_procedure,
                governance_context=st.session_state.get("governance_context"),
            )

            if reqs:
                st.session_state.process_requirements = reqs
            else:
                # Discovery failed — tell the user, don't silently fallback
                st.error(
                    "⚠️ **Requirements discovery failed.** "
                    "The system could not determine what information is needed for this deal. "
                    "You can add requirements manually below."
                )
                st.session_state.process_requirements = []

            # Auto-fill from analysis
            if st.session_state.process_requirements:
                _auto_fill_requirements()
                # Aggressive: auto-suggest remaining CRITICAL requirements individually
                _auto_suggest_critical_requirements()

            st.rerun()

    reqs = st.session_state.process_requirements
    filled = sum(1 for r in reqs if r.get("status") == "filled")
    pending = sum(1 for r in reqs if r.get("status") != "filled")

    if reqs:
        st.progress(filled / max(len(reqs), 1))
        st.caption(f"**{filled}** filled / **{pending}** remaining / **{len(reqs)}** total")

        # Show auto-fill summary if just completed
        if st.session_state.get("_autofill_count") is not None:
            count = st.session_state["_autofill_count"]
            if count > 0:
                st.success(f"✅ Auto-filled **{count}** requirements from the teaser")
            else:
                st.info("ℹ️ Auto-fill could not find values in the teaser. Use AI Suggest or Upload for individual requirements.")
            del st.session_state["_autofill_count"]

        # Re-run auto-fill button
        if pending > 0:
            with st.expander("🔄 Re-run auto-fill from teaser", expanded=False):
                st.caption("Try again to extract values from the teaser for all unfilled requirements.")
                if st.button("🔍 Re-run Auto-Fill", use_container_width=True):
                    _auto_fill_requirements()
                    st.rerun()

        # === Bulk file upload ===
        with st.expander("📁 Upload Supporting Documents", expanded=False):
            st.caption(
                "Upload files (valuations, financial models, term sheets, etc.) — "
                "the agent will analyze each file and auto-fill matching requirements."
            )
            bulk_files = st.file_uploader(
                "Upload documents:",
                type=["pdf", "docx", "xlsx", "xls", "txt", "csv", "png", "jpg", "html", "htm", "json", "pptx"],
                accept_multiple_files=True,
                key="bulk_upload_phase2",
            )
            if bulk_files:
                already_uploaded = st.session_state.get("_bulk_uploaded_files", set())
                new_files = [f for f in bulk_files if f.name not in already_uploaded]

                if new_files:
                    st.write(f"**{len(new_files)} new file(s)** ready to analyze")
                    if st.button("🔍 Analyze All Files", type="primary", use_container_width=True):
                        _bulk_analyze_files(new_files, reqs, get_tracer())
                        already = st.session_state.get("_bulk_uploaded_files", set())
                        for f in new_files:
                            already.add(f.name)
                        st.session_state["_bulk_uploaded_files"] = already
                        st.rerun()

                if st.session_state.supplement_texts:
                    st.caption(f"📎 {len(st.session_state.supplement_texts)} supplementary document(s) loaded — available for compliance & drafting")

        # Group by category
        categories = {}
        for r in reqs:
            cat = r.get("category", "GENERAL")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(r)

        for cat, cat_reqs in categories.items():
            cat_filled = sum(1 for r in cat_reqs if r.get("status") == "filled")
            st.subheader(f"{cat} ({cat_filled}/{len(cat_reqs)})")

            for i, req in enumerate(cat_reqs):
                global_idx = reqs.index(req)
                status_icon = "✅" if req.get("status") == "filled" else "⬜"
                priority_badge = "🔴" if req.get("priority") == "CRITICAL" else ("🟡" if req.get("priority") == "IMPORTANT" else "⚪")

                with st.expander(
                    f"{status_icon} {priority_badge} {req['name']}",
                    expanded=(req.get("status") != "filled")
                ):
                    if req.get("why_required"):
                        st.caption(f"_Why needed: {req['why_required']}_")

                    if req.get("status") == "filled":
                        value_preview = req["value"][:300] + "..." if len(req.get("value", "")) > 300 else req.get("value", "")
                        st.write(f"**Value:** {value_preview}")
                        st.caption(f"Source: {req.get('source', 'unknown')}")

                        new_val = st.text_area("Edit:", value=req.get("value", ""), key=f"edit_{global_idx}")
                        if new_val != req.get("value", "") and st.button("💾 Save", key=f"save_{global_idx}"):
                            old = req["value"]
                            req["value"] = new_val
                            st.session_state.change_log.record_change(
                                "requirement_edit", req["name"], old[:100], new_val[:100], "PROCESS_GAPS"
                            )
                            st.rerun()
                    else:
                        st.caption(req.get("description", ""))

                        # Check for pending results (suggestion or file extraction)
                        sug_key = f"_suggestion_{global_idx}"
                        pending_sug = st.session_state.get(sug_key)

                        if pending_sug:
                            # Show result from AI Suggest or File Upload
                            conf = pending_sug.get("confidence", "?")
                            conf_icon = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(conf, "⚪")
                            source_type = pending_sug.get("source_type", "analysis")
                            source_label = f"📄 From uploaded file: {pending_sug.get('file_name', '')}" if source_type == "file" else "🔍 From teaser/analysis"

                            st.success(f"{conf_icon} Found (confidence: {conf}) — {source_label}")
                            if pending_sug.get("source_quote"):
                                st.caption(f"Source: _{pending_sug['source_quote'][:300]}_")

                            confirmed = st.text_area(
                                "Confirm/edit value:",
                                value=pending_sug["value"],
                                key=f"confirm_{global_idx}",
                            )
                            col_a, col_b = st.columns(2)
                            with col_a:
                                if st.button("✅ Accept", key=f"acc_sug_{global_idx}"):
                                    req["value"] = confirmed
                                    req["status"] = "filled"
                                    req["source"] = f"{source_type}: {pending_sug.get('file_name', 'ai')}"
                                    req["suggestion_detail"] = f"[{conf}] {pending_sug.get('source_quote', '')[:200]}"
                                    del st.session_state[sug_key]
                                    st.rerun()
                            with col_b:
                                if st.button("❌ Dismiss", key=f"dismiss_sug_{global_idx}"):
                                    del st.session_state[sug_key]
                                    st.rerun()

                        else:
                            # === Three input methods ===
                            input_mode = st.radio(
                                "Input method:",
                                ["✏️ Manual", "🤖 AI Suggest", "📁 Upload File"],
                                horizontal=True,
                                key=f"mode_{global_idx}",
                                label_visibility="collapsed",
                            )

                            if input_mode == "✏️ Manual":
                                manual = st.text_area("Enter value:", key=f"manual_{global_idx}", height=80)
                                if manual and st.button("✅ Accept", key=f"accept_{global_idx}"):
                                    req["value"] = manual
                                    req["status"] = "filled"
                                    req["source"] = "manual"
                                    st.rerun()

                            elif input_mode == "🤖 AI Suggest":
                                st.caption("Search teaser and analysis for this value")
                                if st.button("🔍 Search", key=f"ai_{global_idx}", use_container_width=True):
                                    with st.spinner("Searching teaser for this value..."):
                                        parsed = _ai_suggest_requirement_with_retry(req, get_tracer())
                                        if parsed and parsed.get("value"):
                                            parsed["source_type"] = "analysis"
                                            st.session_state[sug_key] = parsed
                                            st.rerun()
                                        else:
                                            st.warning("Could not find this value in the teaser or analysis.")

                            elif input_mode == "📁 Upload File":
                                st.caption("Upload a document (PDF, DOCX, XLSX, TXT, CSV, HTML, JSON, PPTX) — the agent will extract the relevant value")
                                uploaded = st.file_uploader(
                                    "Upload file:",
                                    type=["pdf", "docx", "xlsx", "xls", "txt", "csv", "png", "jpg", "html", "htm", "json", "pptx"],
                                    key=f"upload_{global_idx}",
                                    label_visibility="collapsed",
                                )
                                if uploaded:
                                    if st.button("📄 Analyze File", key=f"analyze_{global_idx}", type="primary", use_container_width=True):
                                        with st.spinner(f"Analyzing {uploaded.name}..."):
                                            parsed = _extract_from_uploaded_file(
                                                uploaded, req, get_tracer()
                                            )
                                            if parsed and parsed.get("value"):
                                                parsed["source_type"] = "file"
                                                parsed["file_name"] = uploaded.name
                                                st.session_state[sug_key] = parsed
                                                st.rerun()
                                            else:
                                                st.warning(
                                                    f"Could not extract **{req['name']}** from {uploaded.name}. "
                                                    "The file may not contain this information, or try a different file."
                                                )

    # Add manual requirement
    st.divider()
    with st.expander("➕ Add Custom Requirement"):
        new_name = st.text_input("Requirement name:", key="new_req_name")
        new_desc = st.text_input("Description:", key="new_req_desc")
        new_why = st.text_input("Why needed for this deal:", key="new_req_why")
        new_priority = st.selectbox("Priority:", ["CRITICAL", "IMPORTANT", "SUPPORTING"], key="new_req_pri")
        if new_name and st.button("Add Requirement"):
            reqs.append({
                "id": len(reqs) + 1,
                "name": new_name,
                "description": new_desc,
                "why_required": new_why,
                "priority": new_priority,
                "category": "CUSTOM",
                "status": "pending",
                "value": "", "source": "", "evidence": "", "suggestion_detail": "",
            })
            st.rerun()

    # Continue gate — based on critical requirements
    st.divider()
    critical_reqs = [r for r in reqs if r.get("priority") == "CRITICAL"]
    critical_filled = sum(1 for r in critical_reqs if r.get("status") == "filled")

    if critical_reqs and critical_filled < len(critical_reqs):
        unfilled_critical = [r["name"] for r in critical_reqs if r.get("status") != "filled"]
        st.warning(f"⚠️ {len(unfilled_critical)} CRITICAL requirements unfilled: {', '.join(unfilled_critical[:5])}")
        if st.checkbox("Proceed anyway (not recommended)"):
            if st.button("➡️ Continue to Compliance", use_container_width=True):
                advance_phase("COMPLIANCE")
                st.rerun()
    elif not reqs:
        st.info("No requirements defined. Add requirements above or continue.")
        if st.button("➡️ Continue to Compliance", use_container_width=True):
            advance_phase("COMPLIANCE")
            st.rerun()
    else:
        if st.button("➡️ Continue to Compliance", type="primary", use_container_width=True):
            advance_phase("COMPLIANCE")
            st.rerun()


def _auto_fill_requirements():
    """
    Auto-fill requirements from the teaser and analysis.

    Sends BOTH the raw teaser text AND the LLM analysis to maximize extraction.
    Uses descriptions so the LLM knows what to look for.
    """
    tracer = get_tracer()
    reqs = st.session_state.process_requirements
    unfilled = [r for r in reqs if r.get("status") != "filled"]

    if not unfilled:
        return

    tracer.record("AutoFill", "START", f"Auto-filling {len(unfilled)} requirements from teaser + analysis")

    # Include descriptions so LLM knows what to look for
    unfilled_for_prompt = [
        {
            "id": r["id"],
            "name": r["name"],
            "description": r.get("description", ""),
        }
        for r in unfilled
    ]
    unfilled_json = json.dumps(unfilled_for_prompt, indent=2)

    # KEY FIX: Include BOTH teaser text AND extracted analysis
    teaser = st.session_state.teaser_text or ""
    analysis = st.session_state.extracted_data or ""

    prompt = f"""You are extracting multiple values from a deal teaser and analysis.

## SOURCE DOCUMENTS:

### PRIMARY SOURCE - Teaser Document:
{teaser[:12000]}

### SECONDARY SOURCE - Analyst's Extraction:
{analysis[:5000]}

## REQUIREMENTS TO FILL:
{unfilled_json}

## EXTRACTION INSTRUCTIONS:

1. **SEMANTIC MATCHING:** Requirement names may differ from source terminology.
   Examples of equivalent terms:
{get_terminology_synonyms(st.session_state.get("governance_context"))}

   **Search for CONCEPTS, not exact words.** Be flexible in matching terminology.

2. **SEARCH THOROUGHLY:**
   - Read the ENTIRE teaser document, not just the beginning
   - Check the analysis if the teaser is unclear or incomplete
   - Look in multiple sections (financials, asset details, parties, narrative)
   - Information might be embedded in paragraphs, not explicit fields

3. **EXTRACT COMPLETELY:**
   - For tables and multi-part values, include ALL rows and components
   - For multi-paragraph descriptions, include everything relevant
   - Don't truncate or summarize complex values
   - Format tables as markdown if needed

4. **QUALITY RULES:**
   - Use EXACT values from teaser (don't round numbers)
   - Include source quote for verification
   - Skip requirements you truly cannot find (don't guess)
   - id must be a NUMBER matching requirement id

## OUTPUT FORMAT:

Return ONLY valid JSON between XML tags, with NO other text:

<json_output>
[
  {{"id": 1, "value": "[amount in deal currency]", "source_quote": "exact quote from teaser..."}},
  {{"id": 2, "value": "[entity name]", "source_quote": "exact quote from teaser..."}}
]
</json_output>

Examples:

Simple value:
<json_output>
[{{"id": 5, "value": "5 years", "source_quote": "facility tenor of 5 years"}}]
</json_output>

Multi-line value:
<json_output>
[{{"id": 8, "value": "Item A: detail one\\nItem B: detail two\\nTotal: combined detail", "source_quote": "the portfolio comprises Item A (detail one)..."}}]
</json_output>

Not found:
<json_output>
[]
</json_output>

CRITICAL RULES:
- Output ONLY the JSON array between <json_output></json_output> tags
- NO preambles like "Here is the JSON:" or "Based on the teaser:"
- NO explanations before or after the tags
- If you can't find any requirements, return empty array: <json_output>[]</json_output>
- Keep each "value" field CONCISE (max 200 chars). For complex data, include only the key figures.
  BAD: "Sponsor: ABC Corp, global real estate arm of XYZ... (500 chars)"
  GOOD: "ABC Corp (key metric: value, relevant experience/qualifications)"
- For tables with many rows, summarize rather than listing every row in the value

NOW: Extract ALL requirements you can find from the documents above.
Use semantic matching to find values even if terminology differs.
Output ONLY <json_output> tags with JSON array inside, NO other text.
"""

    result = call_llm_with_backoff(prompt, MODEL_PRO, 0.0, 8000, "AutoFill", tracer, max_retries=5, thinking_budget=THINKING_BUDGET_NONE)

    tracer.record("AutoFill", "RAW_RESPONSE", f"LLM returned {len(result.text)} chars")

    fills = safe_extract_json(result.text, "array")

    if not fills:
        tracer.record("AutoFill", "PARSE_FAIL", f"Could not parse JSON from response: {result.text[:200]}")
        return

    fill_count = 0
    for fill in fills:
        # Normalize ID to int for comparison (LLM may return string or int)
        try:
            fill_id = int(fill.get("id", -1))
        except (ValueError, TypeError):
            continue

        value = fill.get("value", "").strip()
        if not value or value.upper() in ("NOT STATED", "NOT STATED IN TEASER", "N/A", "NOT FOUND", "NOT AVAILABLE", ""):
            continue

        for req in reqs:
            if int(req.get("id", -1)) == fill_id and req.get("status") != "filled":
                req["value"] = value
                req["status"] = "filled"
                req["source"] = "auto_extracted"
                req["evidence"] = fill.get("source_quote", "")
                fill_count += 1
                break

    tracer.record("AutoFill", "COMPLETE", f"Auto-filled {fill_count}/{len(unfilled)} requirements")
    st.session_state["_autofill_count"] = fill_count


def _auto_suggest_critical_requirements():
    """
    Aggressive auto-fill: after bulk auto-fill, individually search for
    remaining unfilled CRITICAL requirements using AI Suggest.

    This ensures maximum data capture without user intervention.
    Caps at 10 requirements to avoid rate limiting.
    """
    reqs = st.session_state.process_requirements
    tracer = get_tracer()

    critical_unfilled = [
        r for r in reqs
        if r.get("priority") == "CRITICAL" and r.get("status") != "filled"
    ]

    if not critical_unfilled:
        return

    tracer.record("AutoSuggest", "BATCH_START",
                  f"Auto-suggesting {len(critical_unfilled)} unfilled CRITICAL requirements")

    suggested_count = 0
    for req in critical_unfilled[:10]:  # Cap at 10 to avoid rate limits
        try:
            parsed = _ai_suggest_requirement(req, tracer)
            if parsed and parsed.get("value"):
                confidence = parsed.get("confidence", "MEDIUM")
                req["value"] = parsed["value"]
                req["status"] = "filled"
                req["source"] = f"auto_suggest ({confidence})"
                req["evidence"] = parsed.get("source_quote", "")
                req["suggestion_detail"] = f"[{confidence}] {parsed.get('source_quote', '')[:200]}"
                suggested_count += 1
        except Exception as e:
            tracer.record("AutoSuggest", "ERROR", f"{req['name']}: {str(e)[:100]}")
            continue

    tracer.record("AutoSuggest", "BATCH_COMPLETE",
                  f"Auto-suggested {suggested_count}/{len(critical_unfilled)} critical requirements")

    if suggested_count > 0:
        autofill_count = st.session_state.get("_autofill_count", 0)
        st.session_state["_autofill_count"] = autofill_count + suggested_count


def _ai_suggest_requirement(req: dict, tracer) -> dict | None:
    """
    Search teaser + analysis for a requirement value with ROBUST semantic extraction.
    
    Improvements:
    1. Semantic matching - searches for concepts, not just exact words
    2. XML output tags - constrains LLM response format
    3. Increased token budget - 3000 instead of 800 tokens
    4. Better examples - shows how to handle complex values
    5. Enhanced instructions - tells LLM to search thoroughly
    """
    teaser = st.session_state.teaser_text or ""
    analysis = st.session_state.extracted_data or ""
    
    tracer.record("AISuggest", "START", f"Searching for: {req['name']}")
    
    prompt = f"""You are extracting a specific value from a deal teaser and analysis.

## TARGET REQUIREMENT:
**Name:** {req['name']}
**Description:** {req.get('description', 'N/A')}
**Why Needed:** {req.get('why_required', 'N/A')}
**Expected Source:** {req.get('typical_source', 'teaser')}

## SOURCE DOCUMENTS:

### PRIMARY SOURCE - Teaser Document:
{teaser[:12000]}

### SECONDARY SOURCE - Analyst's Extraction (for reference):
{analysis[:5000]}

## EXTRACTION INSTRUCTIONS:

1. **SEMANTIC MATCHING:** The requirement name may use different terminology than the source documents.
   Examples of equivalent terms:
{get_terminology_synonyms(st.session_state.get("governance_context"))}

   **Search for the CONCEPT, not just the exact words.** Be flexible in matching.

2. **SEARCH THOROUGHLY:** 
   - Read the ENTIRE teaser, not just the beginning
   - Check the analysis if the teaser is unclear
   - Look in multiple sections (the info might be in financial summary, asset details, or narrative)
   - For multi-part requirements, search for each component

3. **EXTRACT COMPLETELY:**
   - If the value is a table or multi-part data, include ALL rows and components
   - If the value is a multi-paragraph description, include it all
   - If the value is a calculation, show the math
   - If the value spans multiple sentences or paragraphs, include the full context
   - Do NOT truncate or summarize unless the value is extremely long (>1000 words)

4. **CONFIDENCE ASSESSMENT:**
   - HIGH: Value is explicitly stated with clear source quote
   - MEDIUM: Value is reasonably inferred from available information  
   - LOW: Value is uncertain or requires assumptions
   - If truly not found anywhere, set value to empty string and confidence to LOW

5. **EXTRACTION FROM NATURAL LANGUAGE:**
   Since the analyst's extraction may be in prose format (not a rigid table), search for concepts
   expressed in natural language. The information might be embedded in paragraphs.

## OUTPUT FORMAT:

You MUST output ONLY valid JSON between the XML tags below, with NO other text before or after:

<json_output>
{{
  "value": "<the extracted value - can be multi-line or long, include everything relevant>",
  "source_quote": "<exact quote from source that contains this value - max 500 chars>",
  "confidence": "HIGH|MEDIUM|LOW",
  "found_in": "teaser|analysis|both"
}}
</json_output>

Examples:

Example 1 (Simple value):
<json_output>
{{
  "value": "50,000,000",
  "source_quote": "The total amount of 50 million...",
  "confidence": "HIGH",
  "found_in": "teaser"
}}
</json_output>

Example 2 (Complex multi-line value):
<json_output>
{{
  "value": "Item A: detail one, detail two\\nItem B: detail three, detail four\\nTotal: combined summary",
  "source_quote": "The portfolio comprises Item A (detail one)...",
  "confidence": "HIGH",
  "found_in": "teaser"
}}
</json_output>

Example 3 (Semantic match):
<json_output>
{{
  "value": "15 years of relevant experience",
  "source_quote": "The company has a 15-year track record in the sector",
  "confidence": "HIGH",
  "found_in": "analysis"
}}
</json_output>

Example 4 (Not found):
<json_output>
{{
  "value": "",
  "source_quote": "",
  "confidence": "LOW",
  "found_in": ""
}}
</json_output>

IMPORTANT: Keep the "value" field concise (max 300 chars). Summarize key figures rather than copying entire paragraphs.

NOW: Extract the requirement "{req['name']}" from the documents above.
Remember: Use SEMANTIC MATCHING - look for the concept, not just exact word matches.
Output ONLY the JSON between <json_output></json_output> tags with NO other text before or after.
"""

    # Increased token budget to handle complex multi-line values (sponsor profiles, rent rolls, etc.)
    # Use backoff retry to handle rate limits gracefully
    result = call_llm_with_backoff(prompt, MODEL_PRO, 0.0, 6000, "AISuggest", tracer, thinking_budget=THINKING_BUDGET_NONE)
    
    # Use improved parser with XML tag support
    parsed = safe_extract_json(result.text, "object")
    
    if parsed and parsed.get("value"):
        tracer.record(
            "AISuggest", "FOUND",
            f"{req['name']}: {str(parsed['value'])[:80]}... (confidence: {parsed.get('confidence', '?')})"
        )
    else:
        tracer.record("AISuggest", "NOT_FOUND", f"{req['name']}: no value found")
    
    return parsed


def _ai_suggest_requirement_with_retry(req: dict, tracer) -> dict | None:
    """
    Search for requirement value with intelligent retry.
    
    If first attempt fails, retry with:
    1. More specific search terms
    2. Alternative field names
    3. Direct teaser search without analysis clutter
    """
    
    # Attempt 1: Standard search with semantic matching
    result = _ai_suggest_requirement(req, tracer)
    if result and result.get("value"):
        return result
    
    tracer.record("AISuggest", "RETRY", f"First attempt failed for {req['name']}, trying refined search")
    
    # Attempt 2: Refined search with explicit alternative terms
    teaser = st.session_state.teaser_text or ""
    
    # Generate alternative search terms
    alternative_terms = _generate_alternative_terms(req['name'])
    
    prompt = f"""Find information in this teaser using FLEXIBLE term matching.

## TARGET:
**Primary requirement:** {req['name']}
**Alternative terms to search for:** {', '.join(alternative_terms[:6])}
**Description:** {req.get('description', 'N/A')}
**Context:** {req.get('why_required', 'N/A')}

## INSTRUCTIONS:
1. Search for the primary term AND all alternative terms
2. Look for the underlying CONCEPT even if exact words don't match
3. Be generous in interpretation - if something seems related, include it
4. The information might be phrased differently than the requirement name

## TEASER DOCUMENT:
{teaser[:12000]}

## OUTPUT:
Return ONLY valid JSON between the XML tags with NO other text:

<json_output>
{{
  "value": "<found value or empty string>",
  "source_quote": "<quote from teaser>",
  "confidence": "HIGH|MEDIUM|LOW",
  "found_with_term": "<which term/concept matched>"
}}
</json_output>

Be flexible and generous in matching. If you find something that seems related to the requirement,
include it even if the wording is different.
"""
    
    result = call_llm_with_backoff(prompt, MODEL_PRO, 0.1, 4000, "AISuggestRetry", tracer, thinking_budget=THINKING_BUDGET_NONE)
    parsed = safe_extract_json(result.text, "object")
    
    if parsed and parsed.get("value"):
        tracer.record(
            "AISuggest", "RETRY_SUCCESS",
            f"Found {req['name']} using term: {parsed.get('found_with_term', 'alternative matching')}"
        )
    else:
        tracer.record("AISuggest", "RETRY_FAILED", f"Could not find {req['name']} after retry")
    
    return parsed


def _generate_alternative_terms(requirement_name: str) -> list[str]:
    """
    Generate alternative search terms for a requirement.

    Uses governance-discovered terminology when available.
    No hardcoded domain-specific synonyms — all terminology comes from
    governance discovery or basic string variations.
    """

    # Build term map entirely from governance-discovered terminology
    term_map: dict[str, list[str]] = {}
    gov_ctx = st.session_state.get("governance_context")
    if gov_ctx and gov_ctx.get("terminology_map"):
        for term, synonyms in gov_ctx["terminology_map"].items():
            if isinstance(synonyms, list):
                term_map[term.lower()] = synonyms
    
    alternatives = []
    name_lower = requirement_name.lower()
    
    # Check if any mapped terms appear in the requirement name
    for key, synonyms in term_map.items():
        if key in name_lower:
            alternatives.extend(synonyms)
    
    # Add requirement name itself with variations
    alternatives.insert(0, requirement_name)
    
    # Add name with different separators
    alternatives.append(requirement_name.replace("_", " "))
    alternatives.append(requirement_name.replace("-", " "))
    alternatives.append(requirement_name.replace(" ", "_"))
    
    # Remove duplicates while preserving order
    seen = set()
    unique_alternatives = []
    for term in alternatives:
        term_lower = term.lower()
        if term_lower not in seen:
            seen.add(term_lower)
            unique_alternatives.append(term)
    
    # Return max 10 alternatives
    return unique_alternatives[:10]


def _extract_from_uploaded_file(uploaded_file, req: dict, tracer) -> dict | None:
    """
    Extract a requirement value from an uploaded file.

    1. Save uploaded bytes to temp file
    2. Parse with universal_loader
    3. LLM extracts the specific requirement value
    4. Store full file text in supplement_texts for later phases
    """
    import tempfile

    tracer.record("FileAnalysis", "START", f"Analyzing {uploaded_file.name} for '{req['name']}'")

    # Save to temp file for the loader
    suffix = Path(uploaded_file.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    try:
        # Extract text
        file_text = universal_loader(tmp_path)

        if not file_text or file_text.startswith("[ERROR]") or len(file_text.strip()) < 20:
            tracer.record("FileAnalysis", "ERROR", f"Could not extract text from {uploaded_file.name}")
            return None

        tracer.record(
            "FileAnalysis", "EXTRACTED",
            f"{uploaded_file.name}: {len(file_text)} chars extracted"
        )

        # Store full text as supplementary document for later phases
        st.session_state.supplement_texts[uploaded_file.name] = file_text

        # LLM extraction — find the specific requirement in the file
        prompt = f"""Extract a specific value from this document.

## REQUIREMENT TO FIND
Name: {req['name']}
Description: {req.get('description', '')}
Why needed: {req.get('why_required', '')}

## DOCUMENT: {uploaded_file.name}
{file_text[:8000]}

## INSTRUCTIONS
Search the document above for information matching this requirement.
This could be a financial figure, a name, a date, a description, a ratio, a table, etc.

If the document contains tabular data relevant to this requirement, you may include
a formatted table as the value.

Respond with ONLY a JSON object:
```json
{{
  "value": "<the extracted value, or empty string if truly not found>",
  "source_quote": "<exact quote from the document that contains this value>",
  "confidence": "HIGH|MEDIUM|LOW"
}}
```

Return ONLY the JSON object.
"""
        result = call_llm(prompt, MODEL_PRO, 0.0, 1500, "FileAnalysis", tracer, thinking_budget=THINKING_BUDGET_NONE)
        parsed = safe_extract_json(result.text, "object")

        if parsed and parsed.get("value"):
            tracer.record(
                "FileAnalysis", "COMPLETE",
                f"Found '{req['name']}' in {uploaded_file.name} [{parsed.get('confidence', '?')}]"
            )
        else:
            tracer.record(
                "FileAnalysis", "NOT_FOUND",
                f"'{req['name']}' not found in {uploaded_file.name}"
            )

        return parsed

    except Exception as e:
        tracer.record("FileAnalysis", "ERROR", str(e))
        return None
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _bulk_analyze_files(files, reqs: list[dict], tracer):
    """
    Analyze multiple uploaded files against all unfilled requirements.

    For each file:
    1. Extract text
    2. Store as supplementary document
    3. Ask LLM to match file contents against all unfilled requirements
    4. Auto-fill any matches
    """
    import tempfile

    unfilled = [r for r in reqs if r.get("status") != "filled"]
    if not unfilled:
        return

    unfilled_desc = json.dumps(
        [{"id": r["id"], "name": r["name"], "description": r.get("description", "")} for r in unfilled],
        indent=2,
    )

    for uploaded in files:
        tracer.record("BulkAnalysis", "START", f"Analyzing {uploaded.name}")

        suffix = Path(uploaded.name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded.getbuffer())
            tmp_path = tmp.name

        try:
            file_text = universal_loader(tmp_path)
            if not file_text or file_text.startswith("[ERROR]") or len(file_text.strip()) < 20:
                tracer.record("BulkAnalysis", "SKIP", f"{uploaded.name}: could not extract text")
                continue

            # Store as supplementary document
            st.session_state.supplement_texts[uploaded.name] = file_text

            tracer.record("BulkAnalysis", "EXTRACTED", f"{uploaded.name}: {len(file_text)} chars")

            # LLM: match file contents against all unfilled requirements
            prompt = f"""Analyze this document and extract values for as many requirements as possible.

## DOCUMENT: {uploaded.name}
{file_text[:10000]}

## UNFILLED REQUIREMENTS
{unfilled_desc}

## INSTRUCTIONS
For each requirement where you can find a matching value in the document, include it in the output.
Only include requirements where you found a clear match — skip any you're uncertain about.

Respond with ONLY a JSON array:
```json
[
  {{
    "id": <requirement id>,
    "value": "<extracted value>",
    "source_quote": "<exact quote from document>",
    "confidence": "HIGH|MEDIUM|LOW"
  }}
]
```

Return ONLY the JSON array. If nothing matches, return an empty array [].
"""
            result = call_llm(prompt, MODEL_PRO, 0.0, 3000, "BulkAnalysis", tracer, thinking_budget=THINKING_BUDGET_NONE)
            fills = safe_extract_json(result.text, "array")

            fill_count = 0
            if fills:
                for fill in fills:
                    try:
                        fill_id = int(fill.get("id", -1))
                    except (ValueError, TypeError):
                        continue
                    value = fill.get("value", "").strip()
                    if not value or value.upper() in ("NOT FOUND", "N/A", "NOT AVAILABLE", ""):
                        continue
                    for req in reqs:
                        if int(req.get("id", -1)) == fill_id and req.get("status") != "filled":
                            req["value"] = value
                            req["status"] = "filled"
                            req["source"] = f"file: {uploaded.name}"
                            req["evidence"] = fill.get("source_quote", "")
                            fill_count += 1
                            break

            tracer.record(
                "BulkAnalysis", "COMPLETE",
                f"{uploaded.name}: filled {fill_count} requirements"
            )

        except Exception as e:
            tracer.record("BulkAnalysis", "ERROR", f"{uploaded.name}: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

# =============================================================================
# Phase: COMPLIANCE
# =============================================================================


