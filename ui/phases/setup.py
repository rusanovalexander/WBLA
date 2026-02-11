"""
SETUP Phase - RAG connection, governance discovery, document upload

Extracted from app.py lines 221-328
"""

import streamlit as st
from pathlib import Path

from config.settings import VERSION, PRODUCT_NAME, TEASERS_FOLDER, EXAMPLES_FOLDER, MODEL_PRO
from tools.document_loader import tool_load_document, scan_data_folder
from tools.rag_search import test_rag_connection, tool_search_procedure, tool_search_guidelines
from core.governance_discovery import run_governance_discovery
from core.llm_client import call_llm
from agents import create_process_analyst_responder, create_compliance_advisor_responder
from ui.utils.session_state import get_tracer, advance_phase


def render_phase_setup():
    """Render SETUP phase UI."""
    st.header(f"📋 {PRODUCT_NAME.upper()} System")
    st.subheader(f"v{VERSION} — Autonomous Multi-Agent System")

    # Test RAG connection
    if st.session_state.rag_ok is None:
        with st.spinner("Testing RAG connection..."):
            rag_test = test_rag_connection()
            st.session_state.rag_ok = rag_test.get("connected", False)

    if st.session_state.rag_ok:
        st.success("✅ RAG connected to Vertex AI Search")
        
        # Run governance discovery once
        if not st.session_state.governance_discovery_done:
            with st.spinner("🔍 Analyzing governance documents (Procedure & Guidelines)..."):
                gov_ctx = run_governance_discovery(
                    search_procedure_fn=tool_search_procedure,
                    search_guidelines_fn=tool_search_guidelines,
                    tracer=get_tracer(),
                )
                st.session_state.governance_context = gov_ctx
                st.session_state.governance_discovery_done = True
                
                # Re-register agent responders with governance context
                bus = st.session_state.get("agent_bus")
                if bus and gov_ctx and gov_ctx.get("discovery_status") in ("complete", "partial"):
                    bus.register_responder(
                        "ProcessAnalyst",
                        create_process_analyst_responder(call_llm, MODEL_PRO, gov_ctx)
                    )
                    bus.register_responder(
                        "ComplianceAdvisor",
                        create_compliance_advisor_responder(call_llm, MODEL_PRO, tool_search_guidelines, gov_ctx)
                    )
        
        # Show discovery results
        gov_ctx = st.session_state.governance_context
        if gov_ctx and gov_ctx.get("discovery_status") == "complete":
            st.success(
                f"📚 Governance framework discovered: "
                f"{len(gov_ctx.get('requirement_categories', []))} categories, "
                f"{len(gov_ctx.get('compliance_framework', []))} compliance criteria, "
                f"{len(gov_ctx.get('risk_taxonomy', []))} risk categories"
            )
        elif gov_ctx and gov_ctx.get("discovery_status") == "partial":
            st.info("📚 Governance framework partially discovered — some prompts will use defaults")
        elif gov_ctx:
            st.warning("📚 Could not discover governance framework — using default prompts")
    else:
        st.warning("⚠️ RAG not connected — agents will not be able to search Procedure/Guidelines")

    st.subheader("📁 Documents")
    docs = scan_data_folder()

    # Teaser upload
    st.markdown("**Deal Teaser** (required)")
    if docs.get("teasers"):
        for f in docs["teasers"]:
            st.write(f"📄 {Path(f).name}")
    uploaded_teaser = st.file_uploader(
        "Upload deal teaser",
        type=["pdf", "docx", "txt", "xlsx", "xls", "csv", "png", "jpg", "html", "htm", "json", "pptx"],
        accept_multiple_files=False,
        key="setup_teaser_upload",
    )
    if uploaded_teaser:
        safe_name = Path(uploaded_teaser.name).name
        dest = TEASERS_FOLDER / safe_name
        with open(dest, "wb") as out:
            out.write(uploaded_teaser.getbuffer())
        st.success(f"Uploaded teaser: {uploaded_teaser.name}")

    # Example upload
    st.markdown(f"**Example {PRODUCT_NAME.title()}** (optional — used as style/structure reference for drafting)")
    if docs.get("examples"):
        for f in docs["examples"]:
            st.write(f"📄 {Path(f).name}")
    uploaded_example = st.file_uploader(
        f"Upload example {PRODUCT_NAME}",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=False,
        key="setup_example_upload",
    )
    if uploaded_example:
        safe_name = Path(uploaded_example.name).name
        dest = EXAMPLES_FOLDER / safe_name
        with open(dest, "wb") as out:
            out.write(uploaded_example.getbuffer())
        st.success(f"Uploaded example: {uploaded_example.name}")

    # Load documents button
    if st.button("📋 Load Documents & Start", type="primary", use_container_width=True):
        with st.spinner("Loading documents..."):
            docs = scan_data_folder()
            if docs["teasers"]:
                result = tool_load_document(docs["teasers"][0], force_ocr=True)
                if result["status"] == "OK":
                    st.session_state.teaser_text = result["text"]
                    st.session_state.teaser_file = result["file_name"]
            if docs["examples"]:
                result = tool_load_document(docs["examples"][0])
                if result["status"] == "OK":
                    st.session_state.example_text = result["text"]
                    st.session_state.example_file = result["file_name"]

            if st.session_state.teaser_text:
                advance_phase("ANALYSIS")
                st.rerun()
            else:
                st.error("No teaser document found. Upload a teaser file above.")
