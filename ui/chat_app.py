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
import sys
import threading
import queue
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup Google Cloud environment (MUST be called before importing orchestrator)
from config.settings import setup_environment, VERSION
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

    if "orchestrator" not in st.session_state:
        # Initialize orchestrator with agents
        st.session_state.orchestrator = ConversationalOrchestrator()
    else:
        # Basic guard against stale/invalid orchestrator objects across reloads
        if not hasattr(st.session_state.orchestrator, "process_message"):
            st.session_state.orchestrator = ConversationalOrchestrator()

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
        with st.chat_message("assistant"):
            status_placeholder = st.empty()
            thinking_queue = queue.Queue()
            shared = {"result": None, "done": False, "error": None}

            def run_orchestrator():
                try:
                    out = st.session_state.orchestrator.process_message(
                        message=user_input,
                        uploaded_files=st.session_state.uploaded_files,
                        on_thinking_step=thinking_queue.put,
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
            while not shared["done"] or not thinking_queue.empty():
                while True:
                    try:
                        step = thinking_queue.get_nowait()
                    except queue.Empty:
                        break
                    if step is None:
                        break
                    steps_shown.append(step)
                status_placeholder.empty()
                with status_placeholder.container():
                    with st.status("🤖 Processing...", expanded=True) as status:
                        if steps_shown:
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
                        else:
                            st.write("⏳ Analyzing message...")
                        if shared["done"]:
                            result = shared["result"]
                            if shared.get("error"):
                                st.error(f"Error: {str(shared['error'])}")
                                status.update(label="❌ Error", state="error")
                            elif result and "❌" in result.get("response", ""):
                                status.update(label="❌ Error", state="error")
                            else:
                                status.update(label="✅ Complete", state="complete")
                if shared["done"]:
                    break
                time.sleep(0.25)

            result = shared["result"]

            status_placeholder.empty()

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
        agent_comms = st.session_state.orchestrator.agent_bus.message_count
        st.caption(f"🔗 {agent_comms} agent queries")


if __name__ == "__main__":
    main()
