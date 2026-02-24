"""
Conversational Chat UI for Credit Pack PoC v3.2.

Claude Code-style interface with:
- File upload sidebar
- Visible thinking process
- Agent-to-agent communication display
- Approval checkpoints
"""

import streamlit as st
from pathlib import Path
from datetime import datetime
import sys
import threading
import queue
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup Google Cloud environment (MUST be called before importing orchestrator)
from config.settings import setup_environment, VERSION, PRODUCT_NAME
setup_environment()

# Import v2 orchestrator with modern features
try:
    from core.conversational_orchestrator_v2 import ConversationalOrchestratorV2 as ConversationalOrchestrator
except ImportError:
    # Fallback to v1 if v2 not available
    from core.conversational_orchestrator import ConversationalOrchestrator


def init_session_state():
    """Initialize chat session state."""
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "uploaded_files" not in st.session_state:
        st.session_state.uploaded_files = {}

    if "orchestrator" not in st.session_state or not hasattr(st.session_state.get("orchestrator"), "process_message"):
        try:
            st.session_state.orchestrator = ConversationalOrchestrator()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Failed to initialize orchestrator: %s", e, exc_info=True)
            st.session_state.orchestrator = None

    if "pending_approval" not in st.session_state:
        st.session_state.pending_approval = None


def render_sidebar():
    """Render file upload sidebar."""
    with st.sidebar:
        st.header("📁 Files")

        # File upload button ('+' equivalent)
        uploaded = st.file_uploader(
            "Upload Documents",
            type=["pdf", "docx", "txt"],
            accept_multiple_files=True,
            key="file_uploader",
            help="Upload teaser, example packs, or other documents"
        )

        # Process uploaded files
        if uploaded:
            for file in uploaded:
                if file.name not in st.session_state.uploaded_files:
                    # Save file content
                    content = file.read()
                    st.session_state.uploaded_files[file.name] = {
                        "content": content,
                        "type": file.type,
                        "size": file.size
                    }
                    # Reset file pointer
                    file.seek(0)

        # Show current files
        if st.session_state.uploaded_files:
            st.subheader("Uploaded")
            for filename in list(st.session_state.uploaded_files.keys()):
                col1, col2 = st.columns([4, 1])
                with col1:
                    # Show file type icon
                    if "teaser" in filename.lower():
                        icon = "📄"
                    elif any(kw in filename.lower() for kw in ["example", "template"]):
                        icon = "📋"
                    else:
                        icon = "📎"

                    size_kb = st.session_state.uploaded_files[filename]["size"] / 1024
                    st.text(f"{icon} {filename[:30]}")
                    st.caption(f"{size_kb:.1f} KB")

                with col2:
                    if st.button("🗑️", key=f"del_{filename}", help="Remove file"):
                        del st.session_state.uploaded_files[filename]
                        st.rerun()

        else:
            st.info("No files uploaded yet")

        st.divider()

        # Governance status
        st.header("🔍 Governance")
        if st.session_state.get("orchestrator") is None:
            st.error("⚠️ Orchestrator failed to initialize. Check GCP credentials and restart.")
            return
        gov_context = st.session_state.orchestrator.get_governance_context()

        if gov_context and gov_context.get("frameworks"):
            for fw in gov_context["frameworks"]:
                st.success(f"✓ {fw['name']}")
        else:
            st.info("No frameworks loaded")

        st.divider()

        # 🆕 High-level workflow status (TaskState)
        st.header("📈 Workflow Status")
        try:
            task_state = st.session_state.orchestrator.get_task_state()
            phase_label = {
                "SETUP": "Setup",
                "ANALYSIS": "Analysis",
                "PROCESS_GAPS": "Requirements",
                "COMPLIANCE": "Compliance",
                "DRAFTING": "Drafting",
                "COMPLETE": "Complete",
            }.get(task_state.phase.value, task_state.phase.value)
            st.metric("Phase", phase_label)
            st.caption(f"Conversation turns: {task_state.conversation_turns}")

            for step in task_state.steps:
                icon = "✅" if step.done else "○"
                st.text(f"{icon} {step.name}")
        except Exception:
            st.info("Workflow status not available")

        st.divider()

        # 🆕 Process timeline (Cursor-like: see steps, thought, re-run from here)
        st.header("🕐 Process Timeline")
        if hasattr(st.session_state.orchestrator, "get_step_history"):
            steps = st.session_state.orchestrator.get_step_history()
            if not steps:
                st.caption("No steps yet. Run analysis, compliance, or drafting to see the timeline.")
            else:
                for i, step in enumerate(steps):
                    with st.expander(f"**{i}. {step.label}**", expanded=(i == len(steps) - 1)):
                        if step.thinking:
                            st.markdown("**Thinking**")
                            for t in step.thinking:
                                st.caption(t)
                            st.markdown("---")
                        st.markdown("**Response**")
                        st.markdown(step.response[:3000] + ("…" if len(step.response) > 3000 else ""))
                        st.markdown("---")
                        extra = st.text_input("Additional instruction (optional)", key=f"replay_extra_{i}", placeholder="e.g. focus on environmental risk")
                        if st.button("Re-run from here", key=f"replay_btn_{i}"):
                            st.session_state["_replay_step_index"] = i
                            st.session_state["_replay_instruction"] = extra or ""
                            st.rerun()
        else:
            st.caption("Step history available with v2 orchestrator.")

        st.divider()

        # 🆕 SOURCES USED TRACKING
        st.header("📚 Sources")
        if hasattr(st.session_state.orchestrator, 'persistent_context'):
            context = st.session_state.orchestrator.persistent_context

            # RAG searches
            rag_count = len(context.get("rag_searches_done", []))
            if rag_count > 0:
                st.metric("RAG Searches", rag_count)
                with st.expander("View RAG searches", expanded=False):
                    for search in context.get("rag_searches_done", [])[-5:]:  # Last 5
                        st.caption(f"🔍 {search['type']}: \"{search['query']}\" ({search['num_results']} results)")

            # Examples used
            examples_count = len(context.get("examples_used", []))
            if examples_count > 0:
                st.metric("Examples Used", examples_count)

            # Files analyzed
            files_analyzed = sum(1 for f in context.get("uploaded_files", {}).values() if f.get("analyzed"))
            if files_analyzed > 0:
                st.metric("Files Analyzed", files_analyzed)

            if rag_count == 0 and examples_count == 0 and files_analyzed == 0:
                st.info("No sources used yet")

        st.divider()

        # Agent communication log
        st.header("💬 Agent Comms")
        comm_count = st.session_state.orchestrator.agent_bus.message_count

        if comm_count > 0:
            st.metric("Queries", comm_count)
            if st.button("View Log"):
                # Add to chat
                log = st.session_state.orchestrator.get_agent_communication_log()
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"## Agent Communication Log\n\n{log}",
                    "thinking": None
                })
                st.rerun()

            if st.button("Clear Log"):
                st.session_state.orchestrator.clear_agent_communication_log()
                st.rerun()
        else:
            st.info("No agent communications yet")

        st.divider()

        # Export drafted credit pack to DOCX (saved to outputs folder)
        st.header("📥 Export")
        if hasattr(st.session_state.orchestrator, "persistent_context"):
            ctx = st.session_state.orchestrator.persistent_context
            structure = ctx.get("structure") or []
            drafts = ctx.get("drafts") or {}
            if structure and drafts:
                num_drafted = sum(1 for s in structure if drafts.get(s.get("name")))
                st.caption(f"{num_drafted}/{len(structure)} sections drafted")
                if st.session_state.get("_chat_docx_path"):
                    docx_path = st.session_state["_chat_docx_path"]
                    st.success(f"Saved: {Path(docx_path).name}")
                    try:
                        with open(docx_path, "rb") as f:
                            st.download_button(
                                "⬇️ Download DOCX",
                                f,
                                Path(docx_path).name,
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                use_container_width=True,
                            )
                    except Exception:
                        pass
                    if st.button("🔄 Regenerate DOCX", key="regen_docx"):
                        st.session_state["_chat_docx_path"] = None
                        st.rerun()
                else:
                    if st.button("📥 Save DOCX to outputs folder", type="primary", use_container_width=True):
                        from core.export import generate_docx
                        # Assemble final document from structure order (same as legacy complete phase)
                        parts = []
                        for sec in structure:
                            name = sec.get("name", "")
                            d = drafts.get(name)
                            if d is None:
                                continue
                            content = getattr(d, "content", d) if not isinstance(d, str) else d
                            if content:
                                parts.append(f"# {name}\n\n{content}")
                        final_document = "\n\n---\n\n".join(parts) if parts else ""
                        if not final_document:
                            st.error("No draft content to export")
                        else:
                            metadata = {}
                            if ctx.get("teaser_filename"):
                                metadata["deal_name"] = ctx["teaser_filename"]
                            analysis = ctx.get("analysis") or {}
                            if analysis.get("process_path"):
                                metadata["process_path"] = analysis["process_path"]
                            if analysis.get("origination_method"):
                                metadata["origination_method"] = analysis["origination_method"]
                            filename = f"{PRODUCT_NAME.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"
                            path = generate_docx(final_document, filename, metadata)
                            if path:
                                st.session_state["_chat_docx_path"] = path
                                st.success(f"Saved to: {path}")
                                st.rerun()
                            else:
                                st.error("DOCX generation failed — check python-docx installation")
            else:
                st.info("Draft sections first, then export here")
        else:
            st.info("Draft sections first, then export here")


def render_thinking_process(thinking_steps: list[str], status_label: str = "Processing..."):
    """Render thinking process with status widget."""
    with st.status(status_label, expanded=True) as status:
        for step in thinking_steps:
            # Color-code steps
            if step.startswith("✓"):
                st.success(step)
            elif step.startswith("⏳"):
                st.info(step)
            elif step.startswith("❌") or step.startswith("⚠️"):
                st.warning(step)
            elif step.startswith("💬"):
                st.info(step)
            else:
                st.write(step)

        # Update status to complete
        if any(step.startswith("❌") for step in thinking_steps):
            status.update(label="❌ Error", state="error")
        else:
            status.update(label="✅ Complete", state="complete")


def render_reasoning(reasoning: str):
    """🆕 Render extended reasoning/thinking from LLM."""
    if reasoning:
        with st.expander("🤔 Agent Reasoning (Extended Thinking)", expanded=False):
            st.markdown(reasoning)
            st.caption("_This is the agent's internal reasoning process using Gemini 2.5 extended thinking._")


def render_agent_communication(comm_log: str):
    """Render agent-to-agent communication log."""
    if comm_log and comm_log != "(No agent communications)":
        with st.expander("💬 Agent-to-Agent Communications", expanded=False):
            st.markdown(comm_log)


def render_approval_checkpoint(next_suggestion: str, message_idx: int):
    """Render approval checkpoint with suggested next action."""
    st.divider()

    col1, col2 = st.columns([3, 1])

    with col1:
        st.info(f"💡 **Next:** {next_suggestion}")

    with col2:
        if st.button("✅ Proceed", key=f"approve_button_{message_idx}", use_container_width=True):
            st.session_state.pending_approval = next_suggestion
            st.rerun()


def render_chat():
    """Render chat interface with thinking process."""

    if st.session_state.get("orchestrator") is None:
        st.error("⚠️ Orchestrator is not available. Check your GCP credentials and restart the app.")
        return

    # Display chat history
    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

            # 🆕 Show extended reasoning if exists
            if message.get("reasoning"):
                render_reasoning(message["reasoning"])

            # Show thinking process if exists
            if message.get("thinking"):
                render_thinking_process(
                    message["thinking"],
                    message.get("status_label", "Processing...")
                )

            # Show agent communication if exists
            if message.get("agent_communication"):
                render_agent_communication(message["agent_communication"])

            # 🆕 Show sources used if exists
            if message.get("sources_used"):
                sources = message["sources_used"]
                if any(sources.values()):  # If any source was used
                    with st.expander("📚 Sources Consulted", expanded=False):
                        if sources.get("rag_searches", 0) > 0:
                            st.caption(f"🔍 RAG Database: {sources['rag_searches']} searches")
                        if sources.get("examples", 0) > 0:
                            st.caption(f"📋 Example Credit Packs: {sources['examples']} used")
                        if sources.get("uploaded_files", 0) > 0:
                            st.caption(f"📄 Uploaded Files: {sources['uploaded_files']} analyzed")

            # Show approval checkpoint if needed
            if message.get("requires_approval") and idx == len(st.session_state.messages) - 1:
                if message.get("next_suggestion"):
                    render_approval_checkpoint(message["next_suggestion"], idx)

    # Chat input
    user_input = st.chat_input("Type your message...")

    # Handle pending approval (button click)
    if st.session_state.pending_approval:
        user_input = st.session_state.pending_approval
        st.session_state.pending_approval = None

    # 🆕 Handle Re-run from step (Cursor-like: from Process Timeline)
    replay_step = st.session_state.pop("_replay_step_index", None)
    replay_instruction = st.session_state.pop("_replay_instruction", "")

    if replay_step is not None and hasattr(st.session_state.orchestrator, "process_replay_from_step"):
        orchestrator = st.session_state.orchestrator
        thinking_queue = queue.Queue()
        shared_replay = {"result": None, "done": False, "error": None}

        def run_replay():
            try:
                out = orchestrator.process_replay_from_step(
                    step_index=replay_step,
                    additional_instruction=replay_instruction,
                    on_thinking_step=thinking_queue.put,
                )
                shared_replay["result"] = out
            except Exception as e:
                shared_replay["error"] = e
                shared_replay["result"] = {
                    "response": f"❌ Re-run failed: {str(e)}",
                    "thinking": [str(e)],
                    "requires_approval": False,
                    "next_suggestion": None,
                    "agent_communication": None,
                    "sources_used": {},
                }
            finally:
                shared_replay["done"] = True
                thinking_queue.put(None)

        thread = threading.Thread(target=run_replay, daemon=True)
        thread.start()

        with st.chat_message("assistant"):
            st.markdown("**Thinking**")
            steps_shown = []
            stream_buffer = []

            # Create status box once — stable, never torn down mid-stream
            with st.status("🤖 Re-running...", expanded=True) as replay_status:
                replay_steps_container = st.empty()
                replay_stream_placeholder = st.empty()

            while not shared_replay["done"] or not thinking_queue.empty():
                updated = False
                while True:
                    try:
                        item = thinking_queue.get_nowait()
                    except queue.Empty:
                        break
                    if item is None:
                        break
                    if isinstance(item, tuple) and len(item) == 2:
                        kind, text = item
                        if kind == "step":
                            steps_shown.append(text)
                            updated = True
                        elif kind == "chunk" and text:
                            stream_buffer.append(text)
                            updated = True
                    else:
                        # Legacy: plain string step items
                        steps_shown.append(str(item))
                        updated = True

                if updated:
                    with replay_steps_container.container():
                        for s in steps_shown:
                            if s.startswith("✓"):
                                st.success(s)
                            elif s.startswith("⏳"):
                                st.info(s)
                            elif s.startswith("❌") or s.startswith("⚠️"):
                                st.warning(s)
                            else:
                                st.caption(s)
                    if stream_buffer:
                        replay_stream_placeholder.markdown("".join(stream_buffer))

                if shared_replay["done"]:
                    if shared_replay.get("error"):
                        replay_status.update(label="❌ Error", state="error")
                    else:
                        replay_status.update(label="✅ Complete", state="complete")
                    break

                time.sleep(0.1)

            result = shared_replay["result"] or {
                "response": "Re-run produced no result.",
                "thinking": [],
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
                "sources_used": {},
            }
            if shared_replay.get("error"):
                st.error(f"Error: {str(shared_replay['error'])}")
            st.markdown("---")
            st.markdown("**Response**")
            st.markdown(result["response"])
        st.session_state.messages.append({
            "role": "user",
            "content": f"[Re-run from step {replay_step}] {replay_instruction or '(re-run)'}",
        })
        st.session_state.messages.append({
            "role": "assistant",
            "content": result["response"],
            "thinking": result.get("thinking"),
            "reasoning": result.get("reasoning"),
            "requires_approval": result.get("requires_approval", False),
            "next_suggestion": result.get("next_suggestion"),
            "agent_communication": result.get("agent_communication"),
            "sources_used": result.get("sources_used"),
        })
        if result.get("requires_approval") and result.get("next_suggestion"):
            st.session_state.pending_approval = result["next_suggestion"]
        st.rerun()

    if user_input:
        # Add user message
        st.session_state.messages.append({
            "role": "user",
            "content": user_input
        })

        # Display user message
        with st.chat_message("user"):
            st.markdown(user_input)

        # Process with orchestrator (stream thinking steps live)
        # Capture refs in main thread — worker thread must not access st.session_state (no ScriptRunContext).
        orchestrator = st.session_state.orchestrator
        uploaded_files = st.session_state.uploaded_files

        with st.chat_message("assistant"):
            st.markdown("**Thinking**")
            thinking_queue = queue.Queue()
            shared = {"result": None, "done": False, "error": None}

            def run_orchestrator():
                try:
                    # Queue items: ("step", str) = status line, ("chunk", str) = live agent output, None = done
                    on_step = lambda s: thinking_queue.put(("step", s))
                    on_stream = lambda s: thinking_queue.put(("chunk", s))
                    out = orchestrator.process_message(
                        message=user_input,
                        uploaded_files=uploaded_files,
                        on_thinking_step=on_step,
                        on_agent_stream=on_stream,
                    )
                    shared["result"] = out
                except Exception as e:
                    shared["error"] = e
                    shared["result"] = {
                        "response": f"❌ Error: {str(e)}",
                        "thinking": [f"❌ {str(e)}"],
                        "action": None,
                        "requires_approval": False,
                        "next_suggestion": None,
                        "agent_communication": None,
                    }
                finally:
                    shared["done"] = True
                    thinking_queue.put(None)

            thread = threading.Thread(target=run_orchestrator, daemon=True)
            thread.start()

            steps_shown = []
            stream_buffer = []

            # Create status box once — stable, never torn down mid-stream
            with st.status("🤖 Processing...", expanded=True) as status:
                steps_container = st.empty()   # thinking steps rendered here
                stream_placeholder = st.empty()  # live token stream rendered here

            while not shared["done"] or not thinking_queue.empty():
                updated = False
                while True:
                    try:
                        item = thinking_queue.get_nowait()
                    except queue.Empty:
                        break
                    if item is None:
                        break
                    if isinstance(item, tuple) and len(item) == 2:
                        kind, text = item
                        if kind == "step":
                            steps_shown.append(text)
                            updated = True
                        elif kind == "chunk" and text:
                            stream_buffer.append(text)
                            updated = True
                    else:
                        steps_shown.append(str(item))
                        updated = True

                if updated:
                    # Redraw thinking steps in-place
                    with steps_container.container():
                        for step in steps_shown:
                            if step.startswith("✓"):
                                st.success(step)
                            elif step.startswith("⏳"):
                                st.info(step)
                            elif step.startswith("❌") or step.startswith("⚠️"):
                                st.warning(step)
                            elif step.startswith("💬"):
                                st.info(step)
                            else:
                                st.write(step)
                    # Update live stream text in-place (no flicker)
                    if stream_buffer:
                        stream_placeholder.markdown("".join(stream_buffer))

                if shared["done"]:
                    result = shared["result"]
                    if shared.get("error"):
                        status.update(label="❌ Error", state="error")
                    elif result and "❌" in result.get("response", ""):
                        status.update(label="❌ Error", state="error")
                    else:
                        status.update(label="✅ Complete", state="complete")
                    break

                time.sleep(0.1)

            result = shared["result"]

            # Display response
            st.markdown(result["response"])

            # 🆕 Show extended reasoning
            if result.get("reasoning"):
                render_reasoning(result["reasoning"])

            # Show thinking in expander (for history)
            if result["thinking"]:
                render_thinking_process(
                    result["thinking"],
                    "✅ Complete"
                )

            # Show agent communication
            if result.get("agent_communication"):
                render_agent_communication(result["agent_communication"])

            # 🆕 Show sources used
            if result.get("sources_used"):
                sources = result["sources_used"]
                if any(sources.values()):
                    with st.expander("📚 Sources Consulted", expanded=False):
                        if sources.get("rag_searches", 0) > 0:
                            st.caption(f"🔍 RAG Database: {sources['rag_searches']} searches")
                        if sources.get("examples", 0) > 0:
                            st.caption(f"📋 Example Credit Packs: {sources['examples']} used")
                        if sources.get("uploaded_files", 0) > 0:
                            st.caption(f"📄 Uploaded Files: {sources['uploaded_files']} analyzed")

            # Save assistant message
            st.session_state.messages.append({
                "role": "assistant",
                "content": result["response"],
                "reasoning": result.get("reasoning"),  # 🆕 Save reasoning
                "thinking": result["thinking"],
                "status_label": "✅ Complete",
                "agent_communication": result.get("agent_communication"),
                "sources_used": result.get("sources_used"),  # 🆕 Save sources
                "requires_approval": result.get("requires_approval", False),
                "next_suggestion": result.get("next_suggestion"),
            })

            # Show approval checkpoint if needed
            if result.get("requires_approval") and result.get("next_suggestion"):
                render_approval_checkpoint(result["next_suggestion"], len(st.session_state.messages) - 1)

            # Force rerun to show approval button
            if result.get("requires_approval"):
                st.rerun()


def main():
    """Main app entry point."""
    st.set_page_config(
        page_title="Credit Pack Assistant",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Custom CSS for better styling
    st.markdown("""
    <style>
    .stChatMessage {
        padding: 1rem;
        border-radius: 0.5rem;
    }
    .stStatus {
        font-size: 0.9rem;
    }
    div[data-testid="stExpander"] {
        border: 1px solid #e0e0e0;
        border-radius: 0.5rem;
    }
    </style>
    """, unsafe_allow_html=True)

    # Initialize session state
    init_session_state()

    # Header
    st.title("🤖 Credit Pack Assistant")
    st.caption("Multi-agent conversational system for credit pack drafting")

    # Sidebar with files and status
    render_sidebar()

    # Main chat area
    render_chat()

    # Footer
    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.caption(f"💬 {len(st.session_state.messages)} messages")
    with col2:
        st.caption(f"📁 {len(st.session_state.uploaded_files)} files")
    with col3:
        try:
            agent_comms = st.session_state.orchestrator.agent_bus.message_count
        except Exception:
            agent_comms = 0
        st.caption(f"🔗 {agent_comms} agent queries")


if __name__ == "__main__":
    main()
