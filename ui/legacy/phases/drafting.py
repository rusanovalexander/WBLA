"""
DRAFTING Phase - Extracted from app.py

Lines 1646-1822
"""

import streamlit as st
import logging
from pathlib import Path
from datetime import datetime
import json

# Import all necessary items (add as needed based on actual usage)
from config.settings import *
from tools.document_loader import *
from tools.rag_search import *
from core.orchestration import *
from core.llm_client import *
from agents import *
from ui.utils.session_state import get_tracer, advance_phase
from ui.components.agent_dashboard import render_agent_dashboard


def _build_drafting_context(structure: list, drafts: dict) -> dict:
    """Build the full context for section drafting, including previously drafted sections."""
    # Collect already-drafted sections so the Writer sees what came before
    previously_drafted = ""
    for section in structure:
        name = section["name"]
        if name in drafts:
            previously_drafted += f"\n\n# {name}\n\n{drafts[name][:2000]}"

    context = {
        "teaser_text": st.session_state.teaser_text,
        "example_text": st.session_state.example_text,
        "extracted_data": st.session_state.extracted_data,
        "compliance_result": st.session_state.compliance_result,
        "requirements": st.session_state.process_requirements,
        "supplement_texts": st.session_state.supplement_texts,
        "previously_drafted": previously_drafted,
    }
    return context


def render_phase_drafting():
    st.header(f"✍️ Phase 4: {PRODUCT_NAME.title()} Drafting")

    structure = st.session_state.proposed_structure
    drafts = st.session_state.section_drafts

    # Deduplicate section names (LLM may generate duplicates, which breaks dict-keyed drafts)
    if structure:
        seen_names: set[str] = set()
        for sec in structure:
            name = sec.get("name", "")
            if name in seen_names:
                sec["name"] = f"{name} ({structure.index(sec) + 1})"
            seen_names.add(sec.get("name", ""))

    if not structure:
        # Show error from previous failed attempt
        if st.session_state.get("_structure_gen_failed"):
            st.error(
                "⚠️ **Section structure generation failed.** "
                "The LLM response could not be parsed. "
                "You can try again or add sections manually below."
            )

        if st.button("📋 Generate Section Structure", type="primary", use_container_width=True):
            with st.spinner("Generating deal-specific section structure..."):
                sections = generate_section_structure(
                    example_text=st.session_state.example_text,
                    assessment_approach=st.session_state.process_path,
                    origination_method=st.session_state.origination_method,
                    analysis_text=st.session_state.extracted_data,
                    tracer=get_tracer(),
                    search_procedure_fn=tool_search_procedure,
                    governance_context=st.session_state.get("governance_context"),
                )

                if sections:
                    st.session_state.proposed_structure = sections
                    st.session_state["_structure_gen_failed"] = False
                    st.rerun()
                else:
                    st.session_state["_structure_gen_failed"] = True
                    st.rerun()

        # Manual section builder (always available when no structure)
        st.divider()
        st.subheader("Or define sections manually:")
        sec_name = st.text_input("Section name:", key="new_sec_name_init")
        sec_desc = st.text_input("Description:", key="new_sec_desc_init")
        sec_detail = st.selectbox("Detail level:", ["Standard", "Detailed", "Brief"], key="new_sec_detail_init")
        if sec_name and st.button("➕ Add Section", key="add_sec_init"):
            st.session_state.proposed_structure.append(
                {"name": sec_name, "description": sec_desc, "detail_level": sec_detail}
            )
            st.rerun()

        return  # Don't render the drafting UI until we have sections

    if structure:
        st.caption(
            f"Structure: {len(structure)} sections "
            f"(adapted for {st.session_state.origination_method or 'this deal'})"
        )
        st.progress(len(drafts) / max(len(structure), 1))

        # Draft All button
        undrafted = [s for i, s in enumerate(structure) if s.get("name", f"Section_{i + 1}") not in drafts]
        if undrafted:
            if st.button(
                f"✍️ Draft All Remaining ({len(undrafted)} sections)",
                type="primary", use_container_width=True
            ):
                for idx, section in enumerate(structure):
                    name = section.get("name", f"Section_{idx + 1}")
                    if name in drafts:
                        continue
                    with st.spinner(f"Drafting {idx+1}/{len(structure)}: {name}..."):
                        try:
                            context = _build_drafting_context(structure, drafts)
                            draft_result = draft_section(
                                section, context,
                                agent_bus=st.session_state.agent_bus,
                                tracer=get_tracer(),
                                governance_context=st.session_state.get("governance_context"),
                            )
                            drafts[name] = draft_result.content
                        except Exception as e:
                            logger.error("Failed to draft section '%s': %s", name, e)
                            drafts[name] = f"[DRAFTING FAILED: {e}]\n\nPlease re-draft this section manually."
                st.rerun()

            st.divider()

        for i, section in enumerate(structure):
            name = section.get("name", f"Section_{i + 1}")
            is_drafted = name in drafts

            with st.expander(f"{'✅' if is_drafted else '⬜'} {name}", expanded=not is_drafted):
                st.caption(section.get("description", ""))
                st.caption(f"Detail level: {section.get('detail_level', 'Standard')}")

                if is_drafted:
                    st.markdown(drafts[name])
                    edited = st.text_area("Edit:", value=drafts[name], key=f"edit_section_{i}", height=300)
                    if edited != drafts[name] and st.button("💾 Save", key=f"save_section_{i}"):
                        old = drafts[name]
                        drafts[name] = edited
                        st.session_state.change_log.record_change(
                            "section_edit", name, old[:100], edited[:100], "DRAFTING"
                        )
                        st.rerun()
                else:
                    if st.button(f"✍️ Draft {name}", key=f"draft_{i}", use_container_width=True):
                        with st.spinner(f"Writer drafting {name}..."):
                            context = _build_drafting_context(structure, drafts)
                            draft_result = draft_section(
                                section, context,
                                agent_bus=st.session_state.agent_bus,
                                tracer=get_tracer(),
                                governance_context=st.session_state.get("governance_context"),
                            )
                            drafts[name] = draft_result.content
                            st.rerun()

    # Add custom section
    with st.expander("➕ Add Custom Section"):
        sec_name = st.text_input("Section name:", key="new_sec_name")
        sec_desc = st.text_input("Description:", key="new_sec_desc")
        if sec_name and st.button("Add Section"):
            structure.append({"name": sec_name, "description": sec_desc, "detail_level": "Standard"})
            st.rerun()

    st.divider()
    if structure and len(drafts) >= len(structure):
        # AG-M8: Run Orchestrator routing check before allowing completion
        if not st.session_state.get("drafting_routing_done"):
            if st.button("Run Final Review", type="secondary", use_container_width=True):
                with st.spinner("Running orchestrator final review..."):
                    tracer = get_tracer()
                    insights = run_orchestrator_decision(
                        "DRAFTING",
                        {"Analysis": (st.session_state.extracted_data or "")[:3000]},
                        {"Compliance": (st.session_state.compliance_result or "")[:3000],
                         "Process Path": st.session_state.process_path or ""},
                        tracer,
                        governance_context=st.session_state.get("governance_context"),
                    )
                    # Store as plain dict (not Pydantic object) for Streamlit serialization safety
                    st.session_state["drafting_routing"] = {
                        "can_proceed": insights.can_proceed,
                        "requires_human_review": insights.requires_human_review,
                        "message_to_human": insights.message_to_human,
                        "flags": [{"text": f.text, "severity": f.severity.value} for f in insights.flags],
                    }
                    st.session_state["drafting_routing_done"] = True
                    st.rerun()
        else:
            routing = st.session_state.get("drafting_routing") or {}
            if routing.get("message_to_human"):
                st.info(f"Orchestrator: {routing['message_to_human']}")
            for flag in routing.get("flags", []):
                st.warning(f"{flag.get('severity', 'MEDIUM')}: {flag.get('text', '')}")
            can_export = True
            if routing and not routing.get("can_proceed", True):
                st.warning("Orchestrator recommends review before export.")
                can_export = st.checkbox("I have reviewed the drafts and wish to proceed", key="drafting_override")
            if can_export:
                if st.button("➡️ Continue to Export", type="primary", use_container_width=True):
                    advance_phase("COMPLETE")
                    st.rerun()


# =============================================================================
# Phase: COMPLETE
# =============================================================================

