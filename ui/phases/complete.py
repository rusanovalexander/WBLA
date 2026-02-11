"""
COMPLETE Phase - Final document assembly, export, audit trail

Extracted from app.py lines 1822-1898
"""

import streamlit as st
from pathlib import Path
from datetime import datetime

from config.settings import PRODUCT_NAME
from ui.components.agent_dashboard import render_agent_dashboard
from ui.utils.session_state import get_tracer
from tools.export_utils import generate_docx, generate_audit_trail


def render_phase_complete():
    """Render COMPLETE phase UI."""
    st.header("🎉 Phase 5: Complete")

    st.subheader("📊 Session Summary")
    render_agent_dashboard(get_tracer())
    st.divider()

    # Reassemble document from current drafts
    all_content = []
    for section in st.session_state.proposed_structure:
        name = section["name"]
        content = st.session_state.section_drafts.get(name, "")
        if content:
            all_content.append(f"# {name}\n\n{content}")
    st.session_state.final_document = "\n\n---\n\n".join(all_content)

    # Document preview
    with st.expander(f"📄 Full {PRODUCT_NAME.title()} Preview", expanded=True):
        st.markdown(st.session_state.final_document[:5000])
        if len(st.session_state.final_document) > 5000:
            st.caption(f"... ({len(st.session_state.final_document):,} total chars)")

    # DOCX generation
    if st.session_state.get("_docx_path"):
        docx_path = st.session_state["_docx_path"]
        docx_name = Path(docx_path).name
        st.success(f"✅ DOCX ready: {docx_name}")
        with open(docx_path, "rb") as f:
            st.download_button(
                "⬇️ Download DOCX", f, docx_name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        if st.button("🔄 Regenerate DOCX"):
            st.session_state["_docx_path"] = ""
            st.rerun()
    else:
        if st.button("📥 Generate DOCX", type="primary", use_container_width=True):
            with st.spinner("Generating professional DOCX..."):
                metadata = {
                    "deal_name": st.session_state.teaser_file,
                    "process_path": st.session_state.process_path,
                    "origination_method": st.session_state.origination_method,
                }
                filename = f"{PRODUCT_NAME.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
                path = generate_docx(st.session_state.final_document, filename, metadata)
                if path:
                    st.session_state["_docx_path"] = path
                    st.rerun()
                else:
                    st.error("DOCX generation failed — check python-docx installation")

    st.divider()
    col1, col2 = st.columns(2)
    
    # Audit trail
    with col1:
        if st.session_state.get("_audit_path"):
            audit_path = st.session_state["_audit_path"]
            with open(audit_path, "r") as f:
                st.download_button(
                    "⬇️ Download Audit Trail", f, Path(audit_path).name,
                    use_container_width=True,
                )
        else:
            if st.button("📋 Generate Audit Trail", use_container_width=True):
                with st.spinner("Generating audit trail..."):
                    path = generate_audit_trail(dict(st.session_state), get_tracer())
                    if path:
                        st.session_state["_audit_path"] = path
                        st.rerun()

    # Change log
    with col2:
        change_log = st.session_state.change_log
        if change_log and change_log.has_changes():
            with st.expander(f"📝 Change Log ({change_log.get_change_count()})"):
                st.markdown(change_log.generate_audit_trail())
