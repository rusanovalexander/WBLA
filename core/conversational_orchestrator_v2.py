"""
Conversational Orchestrator v2 - Modern Agentic AI Architecture

Key improvements:
- Full conversation memory (tracks entire chat history)
- LLM-based flexible intent detection (no rigid keywords)
- Extended thinking display (Gemini 2.5 thinking budget)
- Auto-file upload analysis
- Example search with user confirmation
- Multi-source integration (RAG + examples + uploads)
"""

from __future__ import annotations

from typing import Any, Callable
from pathlib import Path
import json

from core._streaming_thinking import StreamingThinkingList

from agents import (
    ProcessAnalyst,
    ComplianceAdvisor,
    Writer,
    AgentCommunicationBus,
    create_process_analyst_responder,
    create_compliance_advisor_responder,
)
from core.governance_discovery import run_governance_discovery
from core.llm_client import call_llm
from tools.rag_search import tool_search_procedure, tool_search_guidelines
from config.settings import MODEL_PRO, MODEL_FLASH
from core.tracing import get_tracer, TraceStore
from models.task_state import TaskState
from models.process_steps import (
    ProcessStepRecord,
    snapshot_context,
    restore_context,
)


def _format_one_check(c: dict) -> str:
    """Format a single compliance check for Key Findings. Uses ComplianceCheck keys: criterion, evidence, status, severity."""
    label = c.get("criterion") or c.get("requirement", "General")
    finding = c.get("evidence") or c.get("finding", "")
    if not finding:
        status = c.get("status", "")
        deal_val = c.get("deal_value", "")
        finding = f"{status}" + (f" — {deal_val}" if deal_val else "") if (status or deal_val) else "N/A"
    severity = c.get("severity", "info")
    return f"- **{label}**: {finding} [{severity}]"


_STATE_CHANGING_INTENTS = frozenset({
    "analyze_deal", "enhance_analysis", "discover_requirements",
    "check_compliance", "generate_structure", "draft_section",
})

_INTENT_LABELS = {
    "analyze_deal": "Deal analysis",
    "enhance_analysis": "Enhance analysis",
    "discover_requirements": "Discover requirements",
    "check_compliance": "Compliance check",
    "generate_structure": "Document structure",
    "draft_section": "Draft section",
}


def _record_step(orch: "ConversationalOrchestratorV2", intent: str, result: dict, thinking: list) -> None:
    """Append one process step to history for Cursor-like timeline and re-run."""
    if intent not in _STATE_CHANGING_INTENTS:
        return
    label = _INTENT_LABELS.get(intent, intent.replace("_", " ").title())
    if intent == "draft_section" and result.get("response"):
        # Try to get section name from response (e.g. "## Executive Summary")
        import re
        m = re.search(r"^##\s+(.+?)(?:\n|$)", result["response"], re.MULTILINE)
        if m:
            label = f"Draft: {m.group(1).strip()}"
    thinking_list = list(thinking) if hasattr(thinking, "__iter__") else []
    response_text = result.get("response", "")
    preview = (response_text[:200] + "…") if len(response_text) > 200 else response_text
    step = ProcessStepRecord(
        step_index=len(orch.step_history),
        phase=intent,
        label=label,
        thinking=thinking_list,
        response=response_text,
        response_preview=preview,
        context_after=snapshot_context(orch.persistent_context),
    )
    orch.step_history.append(step)


class ConversationalOrchestratorV2:
    """
    Modern conversational orchestrator with:
    - Conversation memory
    - Flexible LLM-based intent detection
    - Extended thinking display
    - Auto-file analysis
    - Example search control
    """

    def __init__(self, tracer: TraceStore | None = None):
        """Initialize orchestrator with agents and communication bus."""

        self.tracer = tracer or get_tracer()

        # Load governance context
        self.governance_context = self._load_governance()

        # Initialize agent communication bus
        self.agent_bus = AgentCommunicationBus()

        # Register responders for agent-to-agent communication
        self._register_agent_responders()

        # Initialize agents with bus access
        self.analyst = ProcessAnalyst(
            search_procedure_fn=self.search_procedure,
            governance_context=self.governance_context,
            tracer=self.tracer,
        )

        self.advisor = ComplianceAdvisor(
            search_guidelines_fn=self.search_guidelines,
            governance_context=self.governance_context,
            tracer=self.tracer,
            search_procedure_fn=self.search_procedure,
        )

        self.writer = Writer(
            search_procedure_fn=self.search_procedure,
            governance_context=self.governance_context,
            agent_bus=self.agent_bus,  # Writer can query other agents
            tracer=self.tracer,
        )

        # 🆕 CONVERSATION MEMORY - Full chat history
        self.conversation_history = []  # List of {"role": "user/assistant", "content": str}

        # 🆕 PERSISTENT CONTEXT - Remembers across messages
        # Initialize and validate shape to protect against corrupted/legacy
        # state when upgrading versions.
        self.persistent_context = self._init_persistent_context()

        # 🆕 PROCESS STEP HISTORY (Cursor-like: go back, re-run from step)
        self.step_history: list[ProcessStepRecord] = []

    def _load_governance(self) -> dict[str, Any]:
        """Load governance frameworks at startup.

        Returns the governance discovery result DIRECTLY — not wrapped in
        another dict. Agents expect keys like 'search_vocabulary',
        'requirement_categories', 'compliance_framework', 'risk_taxonomy',
        'deal_taxonomy', 'section_templates', 'terminology_map', and
        'discovery_status' at the top level of governance_context.
        """
        import logging
        _log = logging.getLogger(__name__)

        result = run_governance_discovery(
            search_procedure_fn=tool_search_procedure,
            search_guidelines_fn=tool_search_guidelines,
            tracer=self.tracer
        )

        status = result.get("discovery_status", "unknown")
        _log.info(
            "Governance discovery status: %s | categories=%d, compliance=%d, risk=%d, vocab=%d",
            status,
            len(result.get("requirement_categories", [])),
            len(result.get("compliance_framework", [])),
            len(result.get("risk_taxonomy", [])),
            len(result.get("search_vocabulary", [])),
        )

        if status == "failed":
            _log.warning(
                "⚠️ Governance discovery FAILED — agents will use generic defaults. "
                "Check RAG connectivity and data store configuration."
            )

        # Return discovery result DIRECTLY — agents look for keys like
        # governance_context["search_vocabulary"], NOT governance_context["full_context"]["search_vocabulary"]
        return result

    def _init_persistent_context(self) -> dict[str, Any]:
        """Initialize a fresh persistent_context with safe defaults."""
        return {
            # Files
            "uploaded_files": {},  # filename -> {"content": str, "type": str, "analyzed": bool}
            "teaser_text": None,
            "teaser_filename": None,
            "example_text": None,
            "example_filename": None,

            # Analysis results
            "analysis": None,
            "requirements": [],
            "compliance_result": None,
            "compliance_checks": [],
            "structure": [],
            "drafts": {},
            "current_section_index": 0,

            # User comments/additions
            "user_comments": [],  # Track all user additions for final synthesis

            # Sources used (for transparency)
            "rag_searches_done": [],  # Track RAG searches
            "examples_used": [],  # Track which examples were consulted
        }

    def _register_agent_responders(self):
        """Register agent responder functions for inter-agent communication."""

        # Create tracer-aware LLM caller wrapper
        def llm_with_tracer(prompt, model, temperature, max_tokens, agent_name):
            """Wrapper that passes the orchestrator's tracer to call_llm."""
            return call_llm(prompt, model, temperature, max_tokens, agent_name, tracer=self.tracer)

        # Process Analyst responder
        pa_responder = create_process_analyst_responder(
            llm_caller=llm_with_tracer,
            model=MODEL_PRO,
            governance_context=self.governance_context,
        )
        self.agent_bus.register_responder("ProcessAnalyst", pa_responder)

        # Compliance Advisor responder
        ca_responder = create_compliance_advisor_responder(
            llm_caller=llm_with_tracer,
            model=MODEL_PRO,
            rag_tool=self._rag_search_guidelines,
            governance_context=self.governance_context,
        )
        self.agent_bus.register_responder("ComplianceAdvisor", ca_responder)

    def _rag_search_guidelines(self, query: str, num_results: int = 3) -> dict:
        """RAG search wrapper for compliance advisor responder."""
        try:
            result = tool_search_guidelines(query, num_results=num_results)
            # Track search
            self.persistent_context["rag_searches_done"].append({
                "type": "guidelines",
                "query": query,
                "num_results": num_results,
                "status": result.get("status", "UNKNOWN"),
                "error": result.get("error"),
            })
            return result
        except Exception as e:
            # Record failed search for transparency
            self.persistent_context["rag_searches_done"].append({
                "type": "guidelines",
                "query": query,
                "num_results": num_results,
                "status": "ERROR",
                "error": str(e),
            })
            return {"status": "ERROR", "results": [], "error": str(e)}

    def search_procedure(self, query: str, num_results: int = 3):
        """Search procedure documents."""
        try:
            result = tool_search_procedure(query, num_results=num_results)
            # Track search
            self.persistent_context["rag_searches_done"].append({
                "type": "procedure",
                "query": query,
                "num_results": num_results,
                "status": result.get("status", "UNKNOWN"),
                "error": result.get("error"),
            })
            return result
        except RecursionError as e:
            # Log recursion error and return empty result
            import logging
            logging.error(f"RecursionError in search_procedure for query '{query}': {e}")
            self.persistent_context["rag_searches_done"].append({
                "type": "procedure",
                "query": query,
                "num_results": num_results,
                "status": "ERROR",
                "error": "RecursionError",
            })
            return {"status": "ERROR", "results": [], "error": "RecursionError"}
        except Exception as e:
            import logging
            logging.error(f"Error in search_procedure for query '{query}': {e}")
            self.persistent_context["rag_searches_done"].append({
                "type": "procedure",
                "query": query,
                "num_results": num_results,
                "status": "ERROR",
                "error": str(e),
            })
            return {"status": "ERROR", "results": [], "error": str(e)}

    def search_guidelines(self, query: str, num_results: int = 3):
        """Search guidelines documents."""
        try:
            result = tool_search_guidelines(query, num_results=num_results)
            # Track search
            self.persistent_context["rag_searches_done"].append({
                "type": "guidelines",
                "query": query,
                "num_results": num_results,
                "status": result.get("status", "UNKNOWN"),
                "error": result.get("error"),
            })
            return result
        except RecursionError as e:
            # Log recursion error and return empty result
            import logging
            logging.error(f"RecursionError in search_guidelines for query '{query}': {e}")
            self.persistent_context["rag_searches_done"].append({
                "type": "guidelines",
                "query": query,
                "num_results": num_results,
                "status": "ERROR",
                "error": "RecursionError",
            })
            return {"status": "ERROR", "results": [], "error": "RecursionError"}
        except Exception as e:
            import logging
            logging.error(f"Error in search_guidelines for query '{query}': {e}")
            self.persistent_context["rag_searches_done"].append({
                "type": "guidelines",
                "query": query,
                "num_results": num_results,
                "status": "ERROR",
                "error": str(e),
            })
            return {"status": "ERROR", "results": [], "error": str(e)}

    def _get_rag_error_summary(self) -> str | None:
        """Summarize RAG search errors for user-facing messages."""
        searches = self.persistent_context.get("rag_searches_done", [])
        if not searches:
            return None

        errors = [s for s in searches if s.get("status") == "ERROR"]
        if not errors:
            return None

        total = len(errors)
        types = sorted({e.get("type", "unknown") for e in errors})
        last_error = next(
            (e.get("error") for e in reversed(errors) if e.get("error")),
            None,
        )

        type_str = ", ".join(types)
        summary = f"{total} RAG search{'es' if total != 1 else ''} failed for {type_str} sources."
        if last_error:
            summary += f" Latest error: {last_error}"
        return summary

    def _rag_error_notice(self) -> str:
        """User-facing notice when any RAG searches failed. Append to response if non-empty."""
        summary = self._get_rag_error_summary()
        if not summary:
            return ""
        return "\n\n---\n⚠️ **Data sources:** " + summary

    def get_governance_context(self) -> dict[str, Any]:
        """Get current governance context."""
        return self.governance_context

    def get_task_state(self) -> TaskState:
        """Return a typed snapshot of the current workflow state.

        This provides an ADK-style high-level view that the UI and any future
        planners can use to show progress and drive next steps, without
        changing the underlying persistent_context structure.
        """
        return TaskState.from_context(
            persistent_context=self.persistent_context,
            conversation_turns=len(self.conversation_history),
        )

    def get_agent_communication_log(self) -> str:
        """Get formatted agent-to-agent communication log."""
        return self.agent_bus.get_log_formatted()

    def clear_agent_communication_log(self):
        """Clear agent communication history."""
        self.agent_bus.clear()

    def process_message(
        self,
        message: str,
        uploaded_files: dict[str, dict],
        on_thinking_step: Callable[[str], None] | None = None,
        on_agent_stream: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """
        Process user message with full conversation context.

        Args:
            message: User's chat message
            uploaded_files: Dict of {filename: {"content": bytes, "type": str, "size": int}}
            on_thinking_step: Optional callback for each status step (e.g. "⏳ Running...").
            on_agent_stream: Optional callback for live agent LLM output (model reasoning stream).

        Returns:
            {
                "response": str,  # Response text
                "thinking": [str],  # Thinking steps (extended reasoning)
                "reasoning": str | None,  # LLM reasoning (from thinking budget)
                "action": str | None,  # Action taken
                "requires_approval": bool,  # Needs user confirmation
                "next_suggestion": str | None,  # Suggested next step
                "agent_communication": str | None,  # Agent-to-agent comm log
                "sources_used": dict,  # What sources were consulted
            }
        """

        thinking: list[str] = StreamingThinkingList(on_thinking_step) if on_thinking_step else []

        # 🆕 AUTO-ANALYZE UPLOADED FILES
        new_files = self._analyze_uploaded_files(uploaded_files, thinking)

        # Add user message to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": message
        })

        # 🆕 FLEXIBLE INTENT DETECTION (LLM-based)
        intent, reasoning = self._detect_intent_with_reasoning(message, thinking)
        thinking.append(f"✓ Detected intent: {intent}")

        # Route to appropriate handler (pass on_agent_stream for live model output)
        result = None
        if intent == "analyze_deal":
            result = self._handle_analysis(message, thinking, reasoning, on_agent_stream)
        elif intent == "enhance_analysis":
            result = self._handle_enhance_analysis(message, thinking, reasoning)
        elif intent == "discover_requirements":
            result = self._handle_requirements(message, thinking, on_agent_stream)
        elif intent == "check_compliance":
            result = self._handle_compliance(message, thinking, on_agent_stream)
        elif intent == "search_examples":
            result = self._handle_search_examples(message, thinking)
        elif intent == "generate_structure":
            result = self._handle_structure(message, thinking, on_agent_stream)
        elif intent == "draft_section":
            result = self._handle_drafting(message, thinking, on_agent_stream)
        elif intent == "query_agent":
            result = self._handle_agent_query(message, thinking)
        elif intent == "show_communication":
            result = self._handle_show_communication(thinking)
        elif intent == "general_question":
            result = self._handle_general_question(message, thinking, reasoning)
        elif intent == "lookup_procedure":
            result = self._handle_lookup_procedure(message, thinking)
        else:
            result = self._handle_general(message, thinking)

        # Add assistant response to conversation history
        self.conversation_history.append({
            "role": "assistant",
            "content": result["response"]
        })

        # 🆕 RECORD STEP FOR CURSOR-LIKE TIMELINE (re-run from here)
        _record_step(self, intent, result, thinking)

        # 🆕 ADD SOURCES USED
        result["sources_used"] = {
            "rag_searches": len(self.persistent_context["rag_searches_done"]),
            "examples": len(self.persistent_context["examples_used"]),
            "uploaded_files": len([f for f in self.persistent_context["uploaded_files"].values() if f.get("analyzed")])
        }

        # Add extended reasoning if available.
        # Handlers that call LLMs with thinking_budget > 0 set result["reasoning"]
        # to llm_result.thinking directly. If no handler set it, fall back to the
        # reasoning returned by intent detection (always None currently — kept for
        # future use if intent detection gains a thinking budget).
        result.setdefault("reasoning", reasoning)

        return result

    def get_step_history(self) -> list[ProcessStepRecord]:
        """Return the process step timeline for Cursor-like UI (expandable steps, re-run from here)."""
        return self.step_history

    def process_replay_from_step(
        self,
        step_index: int,
        additional_instruction: str = "",
        on_thinking_step: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """
        Re-run from a given step (Cursor-like: go back and re-run with extra input).

        Restores context to the state after the previous step, truncates step history,
        then runs the handler for that step with additional_instruction as the message.
        """
        if step_index < 0 or step_index >= len(self.step_history):
            return {
                "response": f"❌ Invalid step index: {step_index}. Steps: 0–{len(self.step_history) - 1}.",
                "thinking": ["❌ Replay failed: invalid step index"],
                "action": None,
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
                "sources_used": {},
                "reasoning": None,
            }
        phase = self.step_history[step_index].phase
        label = self.step_history[step_index].label

        # Restore context to state *before* this step
        if step_index == 0:
            current_snapshot = {k: self.persistent_context.get(k) for k in ("uploaded_files", "teaser_text", "teaser_filename", "example_text", "example_filename") if k in self.persistent_context}
            self.persistent_context = self._init_persistent_context()
            for k, v in current_snapshot.items():
                if v is not None:
                    self.persistent_context[k] = v
        else:
            restore_context(self.persistent_context, self.step_history[step_index - 1].context_after)

        # Truncate step history so this step and later are removed
        self.step_history = self.step_history[:step_index]

        # Use StreamingThinkingList so UI can show thinking live (Cursor-like)
        thinking: list = (
            StreamingThinkingList(on_thinking_step) if on_thinking_step
            else []
        )

        message = additional_instruction.strip() or f"Re-run: {label}"
        self.conversation_history.append({"role": "user", "content": f"[Re-run from step {step_index}: {label}] {message}"})

        # Run the handler for this phase
        if phase == "analyze_deal":
            result = self._handle_analysis(message, thinking, None)
        elif phase == "enhance_analysis":
            result = self._handle_enhance_analysis(message, thinking, None)
        elif phase == "discover_requirements":
            result = self._handle_requirements(message, thinking)
        elif phase == "check_compliance":
            result = self._handle_compliance(message, thinking)
        elif phase == "generate_structure":
            result = self._handle_structure(message, thinking)
        elif phase == "draft_section":
            result = self._handle_drafting(message, thinking)
        else:
            result = self._handle_general(message, thinking)

        thinking_list = list(thinking) if hasattr(thinking, "__iter__") and not isinstance(thinking, str) else []

        self.conversation_history.append({"role": "assistant", "content": result["response"]})
        _record_step(self, phase, result, thinking_list)

        result["sources_used"] = {
            "rag_searches": len(self.persistent_context["rag_searches_done"]),
            "examples": len(self.persistent_context["examples_used"]),
            "uploaded_files": len([f for f in self.persistent_context["uploaded_files"].values() if f.get("analyzed")]),
        }
        return result

    def _analyze_uploaded_files(self, files: dict, thinking: list[str]) -> list[str]:
        """
        🆕 AUTO-ANALYZE uploaded files mid-conversation.

        Returns list of newly analyzed filenames.
        """
        new_files = []

        for filename, file_data in files.items():
            # Skip if already analyzed
            if filename in self.persistent_context["uploaded_files"]:
                if self.persistent_context["uploaded_files"][filename].get("analyzed"):
                    continue

            thinking.append(f"📄 New file uploaded: {filename}")

            # Extract content
            content = file_data.get("content", b"")
            if isinstance(content, bytes):
                try:
                    content = content.decode("utf-8")
                except UnicodeDecodeError:
                    thinking.append(f"⚠️ Could not decode {filename}")
                    continue

            # Store file
            self.persistent_context["uploaded_files"][filename] = {
                "content": content,
                "type": file_data.get("type", "unknown"),
                "analyzed": False
            }

            # Determine file type
            file_type = "unknown"
            if "teaser" in filename.lower():
                file_type = "teaser"
                self.persistent_context["teaser_text"] = content
                self.persistent_context["teaser_filename"] = filename
            elif any(kw in filename.lower() for kw in ["financial", "statement", "balance", "income"]):
                file_type = "financial_statement"
            elif any(kw in filename.lower() for kw in ["market", "report", "analysis", "consultant"]):
                file_type = "market_report"
            elif any(kw in filename.lower() for kw in ["example", "template", "sample"]):
                file_type = "example"
                self.persistent_context["example_text"] = content
                self.persistent_context["example_filename"] = filename

            # 🆕 AUTO-ANALYZE with LLM
            thinking.append(f"⏳ Analyzing {filename} ({file_type})...")

            analysis_prompt = f"""
            A file has been uploaded: {filename}
            File type: {file_type}

            Content preview (first 1000 chars):
            {content[:1000]}

            Current deal context: {json.dumps(self.persistent_context.get("analysis", {}), default=str)[:500]}

            TASK:
            1. Summarize what relevant information this file contains
            2. Identify if this changes or enhances the current analysis
            3. Suggest what should be updated

            Return a brief summary (2-3 sentences).
            """

            try:
                insights = call_llm(
                    prompt=analysis_prompt,
                    model=MODEL_FLASH,
                    tracer=self.tracer,
                    agent_name="FileAnalyzer",
                    temperature=0.3
                )

                # Mark as analyzed
                self.persistent_context["uploaded_files"][filename]["analyzed"] = True
                self.persistent_context["uploaded_files"][filename]["insights"] = insights.text

                thinking.append(f"✓ {filename}: {insights.text[:100]}...")
                new_files.append(filename)

            except Exception as e:
                thinking.append(f"⚠️ Could not analyze {filename}: {e}")

        return new_files

    def _detect_intent_with_reasoning(
        self,
        message: str,
        thinking: list[str]
    ) -> tuple[str, str | None]:
        """
        🆕 FLEXIBLE INTENT DETECTION using LLM (not keywords).

        Returns (intent, reasoning) tuple.
        """

        # Build context summary for intent detection
        context_summary = {
            "files_uploaded": list(self.persistent_context["uploaded_files"].keys()),
            "analysis_done": self.persistent_context.get("analysis") is not None,
            "requirements_done": len(self.persistent_context.get("requirements", [])) > 0,
            "compliance_done": self.persistent_context.get("compliance_result") is not None,
            "structure_done": len(self.persistent_context.get("structure", [])) > 0,
            "drafts_done": len(self.persistent_context.get("drafts", {})),
            "conversation_turns": len(self.conversation_history),
        }

        # Recent conversation context (last 3 turns)
        recent_context = self.conversation_history[-6:] if len(self.conversation_history) > 0 else []

        intent_prompt = f"""
        You are an intent classifier for a credit pack drafting system.

        USER MESSAGE: "{message}"

        RECENT CONVERSATION:
        {json.dumps(recent_context, indent=2)}

        CURRENT STATE:
        {json.dumps(context_summary, indent=2)}

        POSSIBLE INTENTS:
        1. analyze_deal - Initial deal analysis (user wants to analyze teaser)
        2. enhance_analysis - User wants to ADD/MODIFY existing analysis ("add more about X", "can you include Y")
        3. discover_requirements - Find required data fields from procedures
        4. check_compliance - Verify compliance with guidelines
        5. search_examples - User wants to see similar deals from examples database
        6. generate_structure - Generate document section structure
        7. draft_section - Draft a specific section
        8. query_agent - Direct query to an agent ("ask ProcessAnalyst about X")
        9. show_communication - Show agent-to-agent communication log
        10. general_question - User asks a question about the deal/analysis/teaser
        11. lookup_procedure - User wants to look up a specific guideline, procedure, or policy
            (e.g. "show me the SME guideline", "what does the procedure say about X",
            "what are the requirements for Y", "show me the rule for Z")
        12. general - General guidance or unclear intent

        RULES:
        - If user says "add", "more", "include", "enhance" → enhance_analysis
        - If user mentions "example", "similar", "reference deal" → search_examples
        - If analysis not done and user is asking about the deal → analyze_deal
        - If user is asking a question (what/how/why) about the deal or teaser → general_question
        - If user says "guideline", "procedure", "policy", "rule", "requirement", "show me" + topic → lookup_procedure
        - Be flexible with phrasing - understand natural language

        Return ONLY the intent name (one word/phrase from the list above).
        """

        try:
            # Use fast model for intent detection
            intent_response = call_llm(
                prompt=intent_prompt,
                model=MODEL_FLASH,
                tracer=self.tracer,
                agent_name="IntentDetector",
                temperature=0.1,
            )

            intent = intent_response.text.strip().lower()

            # Validate intent
            valid_intents = [
                "analyze_deal", "enhance_analysis", "discover_requirements",
                "check_compliance", "search_examples", "generate_structure",
                "draft_section", "query_agent", "show_communication",
                "general_question", "lookup_procedure", "general"
            ]

            if intent not in valid_intents:
                thinking.append(f"⚠️ Invalid intent detected: {intent}, defaulting to general")
                intent = "general"

            return intent, None  # No extended reasoning for intent detection (keep it fast)

        except Exception as e:
            thinking.append(f"⚠️ Intent detection failed: {e}, defaulting to general")
            return "general", None

    def _handle_enhance_analysis(
        self,
        message: str,
        thinking: list[str],
        reasoning: str | None
    ) -> dict:
        """
        🆕 Handle request to enhance/modify existing analysis.

        User says: "Add more about market risks", "Can you include sponsor background"
        """

        if not self.persistent_context.get("analysis"):
            return {
                "response": "❌ Please complete initial analysis first before enhancing it.",
                "thinking": thinking + ["❌ No analysis to enhance"],
                "action": None,
                "requires_approval": False,
                "next_suggestion": "Run analysis first: 'Analyze this deal'",
                "agent_communication": None,
            }

        thinking.append("⏳ Enhancing analysis based on user request...")

        # Store user comment
        self.persistent_context["user_comments"].append({
            "type": "enhance_analysis",
            "message": message
        })

        # Extract what user wants to add
        enhancement_prompt = f"""
        Current analysis:
        {self.persistent_context["analysis"]["full_analysis"][:2000]}...

        User request: "{message}"

        Available context:
        - Teaser: {self.persistent_context.get("teaser_text", "N/A")[:1000]}...
        - Uploaded files: {list(self.persistent_context["uploaded_files"].keys())}

        TASK:
        1. Understand what aspect user wants enhanced (e.g., market risks, sponsor background)
        2. Search RAG for relevant procedure/guideline sections
        3. Extract relevant info from teaser and uploaded files
        4. Generate enhanced analysis section

        Provide the ENHANCED analysis incorporating the user's request.
        """

        try:
            # Search RAG based on user's request
            search_query = message.replace("add", "").replace("more", "").replace("about", "").strip()
            thinking.append(f"🔍 Searching procedures for: {search_query}")

            rag_results = self.search_procedure(search_query, num_results=5)

            # Generate enhanced analysis
            enhancement = call_llm(
                prompt=enhancement_prompt + f"\n\nRAG Results:\n{json.dumps(rag_results, indent=2)[:1000]}",
                model=MODEL_PRO,
                tracer=self.tracer,
                agent_name="AnalysisEnhancer",
                temperature=0.3,
                thinking_budget=4000  # 🆕 Extended thinking
            )

            # Update analysis (use .text — enhancement is an LLMCallResult object)
            self.persistent_context["analysis"]["full_analysis"] += f"\n\n### Enhanced Analysis\n{enhancement.text}"

            thinking.append("✓ Analysis enhanced")

            return {
                "response": f"""## Analysis Enhanced

{enhancement.text}

---
💬 I've added the requested information to your analysis. Would you like me to:
- Add more details to another area?
- Proceed to discover requirements?
""",
                "thinking": thinking,
                "reasoning": enhancement.thinking or None,
                "action": "analysis_enhanced",
                "requires_approval": True,
                "next_suggestion": "Discover requirements?",
                "agent_communication": self.get_agent_communication_log() if self.agent_bus.message_count > 0 else None,
            }

        except Exception as e:
            thinking.append(f"❌ Enhancement failed: {e}")
            return {
                "response": f"❌ Could not enhance analysis: {str(e)}",
                "thinking": thinking,
                "action": None,
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
            }

    def _handle_search_examples(
        self,
        message: str,
        thinking: list[str]
    ) -> dict:
        """
        🆕 Handle request to search example credit packs.

        User says: "Show me similar deals", "Find examples", "Are there reference deals?"
        """

        thinking.append("🔍 Searching example credit packs...")

        # TODO: Implement tool_search_examples()
        # For now, placeholder response

        return {
            "response": """## Example Search

I can search our database of example credit packs, but this feature is still being implemented.

**What I'll be able to do:**
- Search data/examples/ folder for similar deals
- Filter by sector, amount, complexity
- Show relevant sections from example packs
- Suggest which examples to use as templates

For now, would you like me to proceed with the current analysis?
""",
            "thinking": thinking + ["⚠️ Example search not yet implemented"],
            "action": None,
            "requires_approval": False,
            "next_suggestion": "Proceed with requirements discovery?",
            "agent_communication": None,
        }

    def _handle_general_question(
        self,
        message: str,
        thinking: list[str],
        reasoning: str | None
    ) -> dict:
        """
        🆕 Handle general questions about the deal/analysis.

        User asks: "What's the loan amount?", "Who is the sponsor?", "What are the key risks?"
        """

        thinking.append("💬 Answering question based on current context...")

        # Build rich context — include raw teaser text so questions like
        # "what does the teaser say about EBITDA?" can be answered directly.
        teaser_text = self.persistent_context.get("teaser_text") or ""
        analysis_obj = self.persistent_context.get("analysis") or {}
        user_comments = self.persistent_context.get("user_comments") or []

        context_text = f"""TEASER TEXT (raw source document):
{teaser_text[:4000]}

ANALYSIS SUMMARY:
{json.dumps(analysis_obj, default=str, indent=2)[:1500]}

REQUIREMENTS DISCOVERED:
{json.dumps(self.persistent_context.get("requirements", []), indent=2)[:1000]}

USER ADDITIONS / COMMENTS:
{json.dumps(user_comments, indent=2)[:500]}

CONVERSATION HISTORY (last 6 turns):
{json.dumps(self.conversation_history[-6:], indent=2)}

UPLOADED FILES:
{list(self.persistent_context["uploaded_files"].keys())}"""

        qa_prompt = f"""You are a helpful credit pack assistant with access to the deal documents.

{context_text}

USER QUESTION: "{message}"

Answer clearly and concisely, grounding your answer in the teaser text or analysis above.
Quote specific figures, names, or facts from the source documents where relevant.
If the information is not available in the context, say so clearly and suggest what step
would surface it (e.g. "Run analysis first" or "Upload the financial model").
"""

        try:
            answer = call_llm(
                prompt=qa_prompt,
                model=MODEL_FLASH,
                tracer=self.tracer,
                agent_name="QuestionAnswerer",
                temperature=0.2,
                thinking_budget=4000,   # Enable extended thinking for Q&A
            )

            thinking.append("✓ Answer generated")

            return {
                "response": f"{answer.text}\n\n💬 Any other questions, or should we proceed?",
                "thinking": thinking,
                "reasoning": answer.thinking or None,
                "action": "question_answered",
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
            }

        except Exception as e:
            thinking.append(f"❌ Could not answer: {e}")
            return {
                "response": f"❌ Could not answer your question: {str(e)}",
                "thinking": thinking,
                "action": None,
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
            }

    def _handle_lookup_procedure(self, message: str, thinking: list[str]) -> dict:
        """
        Look up a specific guideline, procedure, or policy from the RAG knowledge base.

        Triggered when user says things like:
        - "show me the SME lending guideline"
        - "what does the procedure say about covenant requirements?"
        - "what are the rules for real estate lending?"
        """
        import re as _re

        thinking.append("🔍 Searching procedure and guideline knowledge base...")

        # Strip filler words to get a clean search query
        search_query = _re.sub(
            r"\b(show me|what does|what is|what are|the|guideline|guidelines|procedure|"
            r"procedures|policy|policies|rule|rules|requirement|requirements|about|for|"
            r"is|say|says|tell me|find|look up|search)\b",
            " ", message, flags=_re.IGNORECASE
        ).strip()
        if not search_query:
            search_query = message

        # Search both procedure AND guideline RAG stores
        proc_results = self.search_procedure(search_query, num_results=5)
        guide_results = self.search_guidelines(search_query, num_results=3)

        thinking.append(f"✓ Found {len(proc_results.get('results', []))} procedure results, "
                        f"{len(guide_results.get('results', []))} guideline results")

        result_prompt = f"""You are a credit policy expert. The user asked:

"{message}"

Here are the relevant procedure and guideline extracts retrieved from the knowledge base:

## PROCEDURE RESULTS
{json.dumps(proc_results, indent=2, default=str)[:3000]}

## GUIDELINE RESULTS
{json.dumps(guide_results, indent=2, default=str)[:1500]}

Summarise the relevant rules, requirements and procedures clearly.
- Quote specific requirements verbatim where important
- Indicate the source document/section for each point
- If the search did not return relevant results, say so and suggest refining the query
- Use bullet points or a table for clarity
"""

        try:
            answer = call_llm(
                prompt=result_prompt,
                model=MODEL_PRO,
                tracer=self.tracer,
                agent_name="ProcedureLookup",
                temperature=0.1,
                thinking_budget=4000,
            )

            thinking.append("✓ Procedure lookup complete")

            return {
                "response": answer.text,
                "thinking": thinking,
                "reasoning": answer.thinking or None,
                "action": "procedure_lookup",
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
            }

        except Exception as e:
            thinking.append(f"❌ Procedure lookup failed: {e}")
            return {
                "response": f"❌ Could not search the procedure knowledge base: {str(e)}",
                "thinking": thinking,
                "action": None,
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
            }

    # ... (Keep all existing handler methods from original file)
    # _handle_analysis, _handle_requirements, _handle_compliance, etc.
    # These remain unchanged from the original implementation

    def _handle_analysis(self, message: str, thinking: list[str], reasoning: str | None = None, on_agent_stream: Callable[[str], None] | None = None) -> dict:
        """Handle deal analysis request."""

        if not self.persistent_context.get("teaser_text"):
            return {
                "response": "❌ Please upload a teaser document first.",
                "thinking": thinking + ["❌ No teaser file found"],
                "action": None,
                "requires_approval": False,
                "next_suggestion": "Upload a teaser PDF or DOCX file to begin analysis.",
                "agent_communication": None,
            }

        thinking.append(f"📄 Using teaser: {self.persistent_context['teaser_filename']}")
        thinking.append("⏳ Running ProcessAnalyst analysis...")

        # Run analysis
        thinking_parts: list[str] = []
        try:
            result = self.analyst.analyze_deal(
                teaser_text=self.persistent_context["teaser_text"],
                use_native_tools=True,
                on_stream=on_agent_stream,
                on_thinking=thinking_parts.append,
            )

            # Update context
            self.persistent_context["analysis"] = result

            thinking.append("✓ Analysis complete")

            # Extract structured decision
            process_path = result.get('process_path', 'N/A')
            orig_method = result.get('origination_method', 'N/A')
            decision_found = result.get('decision_found', False)
            confidence = result.get('decision_confidence', 'NONE')

            thinking.append(f"✓ Process Path: {process_path}")
            thinking.append(f"✓ Origination: {orig_method}")
            thinking.append(f"✓ Decision: {'Found' if decision_found else 'Not found'} (confidence: {confidence})")

            # Format response with structured decision
            decision_status = "✅ **FOUND**" if decision_found else "⚠️ **NOT FOUND - Manual Selection Required**"

            response = f"""## Deal Analysis Complete

{result['full_analysis']}

---
### 📋 Structured Decision

**Status:** {decision_status}
**Confidence:** {confidence}

**Process Path (Assessment Approach):**
{process_path}

**Origination Method:**
{orig_method}

**Reasoning:**
- **Assessment:** {result.get('assessment_reasoning', 'N/A')}
- **Origination:** {result.get('origination_reasoning', 'N/A')}

---
💬 Would you like me to:
- Add more detail to any area? (Just ask: "Add more about X")
- Search for similar examples in our database?
- Proceed to discover requirements?
"""
            rag_notice = self._rag_error_notice()
            if rag_notice:
                response += rag_notice
                thinking.append("⚠️ Some Procedure/Guidelines searches failed — see notice in response")

            return {
                "response": response,
                "thinking": thinking,
                "reasoning": "\n\n".join(thinking_parts) or None,
                "action": "analysis_complete",
                "requires_approval": True,
                "next_suggestion": "Discover requirements based on this analysis?",
                "agent_communication": self.get_agent_communication_log() if self.agent_bus.message_count > 0 else None,
            }

        except Exception as e:
            thinking.append(f"❌ Analysis failed: {e}")
            return {
                "response": f"❌ Analysis failed: {str(e)}",
                "thinking": thinking,
                "action": None,
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
            }

    # Include all other existing handlers unchanged...
    # (I'll keep the file size manageable - these methods remain the same)

    def _suggest_next_step(self) -> str:
        """Suggest next logical step based on current state."""

        if not self.persistent_context.get("teaser_text"):
            return "1. Upload a teaser document\n2. Say 'Analyze this deal'"

        if not self.persistent_context.get("analysis"):
            return "Say 'Analyze this deal' to begin"

        if not self.persistent_context.get("requirements"):
            return "Say 'Discover requirements' to continue"

        if not self.persistent_context.get("compliance_checks"):
            return "Say 'Run compliance checks' to continue"

        if not self.persistent_context.get("structure"):
            return "Say 'Generate structure' to begin drafting"

        if self.persistent_context["current_section_index"] < len(self.persistent_context["structure"]):
            next_section = self.persistent_context["structure"][self.persistent_context["current_section_index"]]["name"]
            return f"Say 'Draft next section' to write '{next_section}'"

        return "All steps complete! Review your draft."

    def _handle_general(self, message: str, thinking: list[str]) -> dict:
        """Handle general questions and guidance (fallback when intent is unclear)."""

        thinking.append("💡 Providing general guidance")

        # Build status summary using persistent_context
        status_parts = []
        if self.persistent_context.get("teaser_text"):
            status_parts.append(f"✓ Teaser loaded: {self.persistent_context['teaser_filename']}")
        else:
            status_parts.append("○ No teaser uploaded")

        if self.persistent_context.get("analysis"):
            status_parts.append("✓ Analysis complete")
        else:
            status_parts.append("○ Analysis pending")

        if self.persistent_context.get("requirements"):
            status_parts.append(f"✓ {len(self.persistent_context['requirements'])} requirements discovered")
        else:
            status_parts.append("○ Requirements pending")

        if self.persistent_context.get("compliance_checks"):
            status_parts.append(f"✓ {len(self.persistent_context['compliance_checks'])} compliance checks")
        else:
            status_parts.append("○ Compliance pending")

        if self.persistent_context.get("structure"):
            status_parts.append(f"✓ {len(self.persistent_context['structure'])} sections structured")
            status_parts.append(f"✓ {len(self.persistent_context['drafts'])} sections drafted")
        else:
            status_parts.append("○ Structure pending")

        status = "\n".join(status_parts)

        response = f"""## Credit Pack Assistant

I can help you draft credit packs through natural conversation.

**Current Status:**
{status}

**What I can do:**
- **Analyze deals**: Upload a teaser and ask me to analyze it
- **Discover requirements**: Extract key data points from the deal
- **Check compliance**: Verify against regulatory guidelines
- **Draft sections**: Generate credit pack sections with citations
- **Agent queries**: Ask ProcessAnalyst or ComplianceAdvisor specific questions

**Agent Communication:**
- Agents can consult each other autonomously during drafting
- Use "Show communication log" to see agent-to-agent queries
- Ask agents directly: "Ask ProcessAnalyst about the loan amount"

**Next Steps:**
{self._suggest_next_step()}
"""
        rag_notice = self._rag_error_notice()
        if rag_notice:
            response += rag_notice

        return {
            "response": response,
            "thinking": thinking,
            "action": None,
            "requires_approval": False,
            "next_suggestion": None,
            "agent_communication": None,
        }
    def _handle_requirements(self, message: str, thinking: list[str], on_agent_stream: Callable[[str], None] | None = None) -> dict:
        """Handle requirements discovery request."""

        if not self.persistent_context.get("analysis"):
            return {
                "response": "❌ Please complete deal analysis first.",
                "thinking": thinking + ["❌ No analysis found"],
                "action": None,
                "requires_approval": False,
                "next_suggestion": "Run analysis first: 'Analyze this deal'",
                "agent_communication": None,
            }

        thinking.append("⏳ Discovering requirements via ProcessAnalyst...")

        # NOTE: analyze_deal() stores assessment approach under "process_path" key
        # (not "assessment_approach"), so we must read from the correct key.
        analysis = self.persistent_context["analysis"]
        assessment_approach = (
            analysis.get("process_path")
            or analysis.get("assessment_approach")
            or ""
        )
        origination_method = analysis.get("origination_method", "")

        thinking.append(f"📋 Using approach={assessment_approach!r}, method={origination_method!r}")

        thinking_parts: list[str] = []
        try:
            requirements = self.analyst.discover_requirements(
                analysis_text=analysis["full_analysis"],
                assessment_approach=assessment_approach,
                origination_method=origination_method,
                identified_gaps=analysis.get("identified_gaps", []),
                on_stream=on_agent_stream,
                on_thinking=thinking_parts.append,
            )

            # Update context
            self.persistent_context["requirements"] = requirements

            filled = [r for r in requirements if r.get("status") == "filled"]
            empty = [r for r in requirements if r.get("status") != "filled"]

            thinking.append(f"✓ Discovered {len(requirements)} requirements ({len(filled)} pre-filled, {len(empty)} need data)")

            # Format requirements grouped by status
            lines: list[str] = []

            if filled:
                lines.append("### ✅ Pre-Filled from Analysis\n")
                for i, r in enumerate(filled, 1):
                    ref = f" _{r['procedure_ref']}_" if r.get("procedure_ref") else ""
                    lines.append(f"{i}. **{r['name']}**: {r['value']}{ref}")

            if empty:
                lines.append("\n### ⬜ Still Needed\n")
                for i, r in enumerate(empty, 1):
                    hint = f" — _{r.get('source_hint', '')}_" if r.get("source_hint") else ""
                    ref = f" _{r.get('procedure_ref', '')}_" if r.get("procedure_ref") else ""
                    lines.append(f"{i}. **{r['name']}**: (empty){hint}{ref}")

            req_list = "\n".join(lines)

            response = f"""## Requirements Discovered

{req_list}

---
**Total:** {len(requirements)} requirements — **{len(filled)}** pre-filled from analysis, **{len(empty)}** still needed
"""
            rag_notice = self._rag_error_notice()
            if rag_notice:
                response += rag_notice
                thinking.append("⚠️ Some Procedure searches failed — requirements may be incomplete")

            return {
                "response": response,
                "thinking": thinking,
                "reasoning": "\n\n".join(thinking_parts) or None,
                "action": "requirements_discovered",
                "requires_approval": True,
                "next_suggestion": "Run compliance checks on these requirements?",
                "agent_communication": self.get_agent_communication_log() if self.agent_bus.message_count > 0 else None,
            }

        except Exception as e:
            thinking.append(f"❌ Requirements discovery failed: {e}")
            return {
                "response": f"❌ Requirements discovery failed: {str(e)}",
                "thinking": thinking,
                "action": None,
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
            }

    def _handle_compliance(self, message: str, thinking: list[str], on_agent_stream: Callable[[str], None] | None = None) -> dict:
        """Handle compliance check request."""

        if not self.persistent_context.get("requirements"):
            return {
                "response": "❌ Please discover requirements first.",
                "thinking": thinking + ["❌ No requirements found"],
                "action": None,
                "requires_approval": False,
                "next_suggestion": "Discover requirements first",
                "agent_communication": None,
            }

        thinking.append("⏳ Running ComplianceAdvisor assessment...")
        thinking.append(f"📋 Checking {len(self.persistent_context['requirements'])} requirements...")

        thinking_parts: list[str] = []
        try:
            result_text, checks = self.advisor.assess_compliance(
                requirements=self.persistent_context["requirements"],
                teaser_text=self.persistent_context["teaser_text"],
                extracted_data=self.persistent_context["analysis"]["full_analysis"],
                use_native_tools=True,
                on_stream=on_agent_stream,
                on_thinking=thinking_parts.append,
            )

            # Update context
            self.persistent_context["compliance_result"] = result_text
            self.persistent_context["compliance_checks"] = checks

            thinking.append(f"✓ Found {len(checks)} compliance considerations")

            # Format checks (keys from ComplianceCheck: criterion, evidence, status, severity)
            checks_list = "\n".join([
                _format_one_check(c) for c in checks[:10]  # Show first 10
            ])

            response = f"""## Compliance Assessment Complete

{result_text}

---
**Key Findings:**
{checks_list}

Total Checks: {len(checks)}
"""
            rag_notice = self._rag_error_notice()
            if rag_notice:
                response += rag_notice
                thinking.append("⚠️ Some Guidelines searches failed — compliance context may be partial")

            return {
                "response": response,
                "thinking": thinking,
                "reasoning": "\n\n".join(thinking_parts) or None,
                "action": "compliance_complete",
                "requires_approval": True,
                "next_suggestion": "Generate document structure for drafting?",
                "agent_communication": self.get_agent_communication_log() if self.agent_bus.message_count > 0 else None,
            }

        except Exception as e:
            thinking.append(f"❌ Compliance check failed: {e}")
            return {
                "response": f"❌ Compliance check failed: {str(e)}",
                "thinking": thinking,
                "action": None,
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
            }

    def _handle_structure(self, message: str, thinking: list[str], on_agent_stream: Callable[[str], None] | None = None) -> dict:
        """Handle structure generation request."""

        if not self.persistent_context.get("analysis"):
            return {
                "response": "❌ Please complete analysis first.",
                "thinking": thinking + ["❌ No analysis found"],
                "action": None,
                "requires_approval": False,
                "next_suggestion": "Run analysis first",
                "agent_communication": None,
            }

        thinking.append("⏳ Generating document structure via Writer...")

        # NOTE: analyze_deal() stores assessment approach under "process_path" key
        analysis = self.persistent_context["analysis"]
        assessment_approach = (
            analysis.get("process_path")
            or analysis.get("assessment_approach")
            or ""
        )

        try:
            structure = self.writer.generate_structure(
                example_text=self.persistent_context.get("example_text", ""),
                assessment_approach=assessment_approach,
                origination_method=analysis.get("origination_method", ""),
                analysis_text=analysis["full_analysis"],
                on_stream=on_agent_stream,
            )

            # Update context
            self.persistent_context["structure"] = structure
            self.persistent_context["current_section_index"] = 0

            thinking.append(f"✓ Generated {len(structure)} sections")

            # Format structure
            structure_list = "\n".join([
                f"{i+1}. **{s['name']}**\n   {s.get('description', 'No description')[:100]}..."
                for i, s in enumerate(structure)
            ])

            response = f"""## Document Structure Generated

{structure_list}

---
**Total Sections:** {len(structure)}
"""

            return {
                "response": response,
                "thinking": thinking,
                "action": "structure_generated",
                "requires_approval": True,
                "next_suggestion": f"Draft first section: '{structure[0]['name']}'?",
                "agent_communication": self.get_agent_communication_log() if self.agent_bus.message_count > 0 else None,
            }

        except Exception as e:
            thinking.append(f"❌ Structure generation failed: {e}")
            return {
                "response": f"❌ Structure generation failed: {str(e)}",
                "thinking": thinking,
                "action": None,
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
            }

    def _build_previously_drafted(self, before_index: int) -> str:
        """Build concatenated text of all sections already drafted (in structure order) for Writer context."""
        structure = self.persistent_context.get("structure") or []
        drafts = self.persistent_context.get("drafts") or {}
        parts = []
        for i in range(min(before_index, len(structure))):
            sec = structure[i]
            name = sec.get("name", "")
            if not name:
                continue
            d = drafts.get(name)
            if d is None:
                continue
            content = getattr(d, "content", d) if not isinstance(d, str) else d
            if content:
                parts.append(f"# {name}\n\n{content}")
        return "\n\n---\n\n".join(parts) if parts else ""

    def _handle_drafting(self, message: str, thinking: list[str], on_agent_stream: Callable[[str], None] | None = None) -> dict:
        """Handle section drafting request."""

        if not self.persistent_context.get("structure"):
            thinking.append("⚠️ No structure found, generating first...")
            # Auto-generate structure
            structure_result = self._handle_structure(message, thinking, on_agent_stream)
            if structure_result["action"] != "structure_generated":
                return structure_result

        # Determine which section to draft
        section_index = self.persistent_context["current_section_index"]

        if section_index >= len(self.persistent_context["structure"]):
            return {
                "response": "✅ All sections have been drafted!",
                "thinking": thinking + ["✓ Drafting complete"],
                "action": "drafting_complete",
                "requires_approval": False,
                "next_suggestion": "Review and finalize the document",
                "agent_communication": self.get_agent_communication_log() if self.agent_bus.message_count > 0 else None,
            }

        section = self.persistent_context["structure"][section_index]
        thinking.append(f"✏️ Drafting section {section_index + 1}/{len(self.persistent_context['structure'])}: '{section['name']}'")

        # Build previously_drafted: all sections already written (in structure order) for continuity
        previously_drafted = self._build_previously_drafted(section_index)

        # Check if Writer might query other agents
        if self.agent_bus.message_count == 0:
            thinking.append("💬 Writer may consult ProcessAnalyst or ComplianceAdvisor...")

        # Build user additions summary from all stored comments
        user_comments = self.persistent_context.get("user_comments", [])
        user_additions_summary = ""
        if user_comments:
            additions_lines = [
                f"- {c['message']}" for c in user_comments
                if c.get("type") in ("enhance_analysis", "general", "user_addition")
            ]
            if additions_lines:
                user_additions_summary = (
                    "USER REQUESTED ADDITIONS (apply these across all sections):\n"
                    + "\n".join(additions_lines)
                )
                thinking.append(f"📝 Applying {len(additions_lines)} user addition(s) to this section")
                # Also persist so Writer can access via persistent_context if needed
                self.persistent_context["user_additions_summary"] = user_additions_summary

        thinking_parts: list[str] = []
        try:
            draft = self.writer.draft_section(
                section=section,
                context={
                    "teaser_text": self.persistent_context["teaser_text"],
                    "analysis": self.persistent_context.get("analysis", {}),
                    "extracted_data": self.persistent_context["analysis"]["full_analysis"] if self.persistent_context.get("analysis") else "",
                    "requirements": self.persistent_context.get("requirements", []),
                    "compliance_result": self.persistent_context.get("compliance_result", ""),
                    "compliance_checks": self.persistent_context.get("compliance_checks", []),
                    "example_text": self.persistent_context.get("example_text") or "",
                    "previously_drafted": previously_drafted,
                    "user_additions_summary": user_additions_summary,  # ← User's requested additions
                },
                on_stream=on_agent_stream,
                on_thinking=thinking_parts.append,
            )

            # Update context
            self.persistent_context["drafts"][section["name"]] = draft
            self.persistent_context["current_section_index"] += 1

            thinking.append(f"✓ Draft complete ({len(draft.content)} chars)")

            # Check for agent communications
            agent_comm_log = None
            if self.agent_bus.message_count > 0:
                thinking.append(f"💬 {self.agent_bus.message_count} agent-to-agent queries made")
                agent_comm_log = self.get_agent_communication_log()

            response = f"""## {section['name']}

{draft.content}

---
**Draft Status:** {section_index + 1}/{len(self.persistent_context['structure'])} sections complete
"""

            next_section = None
            if self.persistent_context["current_section_index"] < len(self.persistent_context["structure"]):
                next_section = self.persistent_context["structure"][self.persistent_context["current_section_index"]]["name"]

            return {
                "response": response,
                "thinking": thinking,
                "reasoning": "\n\n".join(thinking_parts) or None,
                "action": "section_drafted",
                "requires_approval": True,
                "next_suggestion": f"Draft next section: '{next_section}'?" if next_section else "All sections complete!",
                "agent_communication": agent_comm_log,
            }

        except Exception as e:
            thinking.append(f"❌ Drafting failed: {e}")
            return {
                "response": f"❌ Drafting failed: {str(e)}",
                "thinking": thinking,
                "action": None,
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
            }

    def _handle_agent_query(self, message: str, thinking: list[str]) -> dict:
        """Handle direct agent query (user asking one agent to query another)."""

        # Parse query: "Ask ProcessAnalyst about loan amount"
        message_lower = message.lower()

        if "analyst" in message_lower or "process" in message_lower:
            to_agent = "ProcessAnalyst"
        elif "compliance" in message_lower or "advisor" in message_lower:
            to_agent = "ComplianceAdvisor"
        else:
            return {
                "response": "❌ Please specify which agent to query (ProcessAnalyst or ComplianceAdvisor)",
                "thinking": thinking,
                "action": None,
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
            }

        # Extract query
        query = message.split("about", 1)[-1].strip() if "about" in message_lower else message

        thinking.append(f"💬 Querying {to_agent}...")

        # Execute query via bus
        try:
            response_text = self.agent_bus.query(
                from_agent="User",
                to_agent=to_agent,
                query=query,
                context={
                    "teaser_text": self.persistent_context.get("teaser_text", ""),
                    "extracted_data": self.persistent_context["analysis"]["full_analysis"] if self.persistent_context.get("analysis") else "",
                    "requirements": self.persistent_context.get("requirements", []),
                    "compliance_result": self.persistent_context.get("compliance_result", ""),
                }
            )

            thinking.append(f"✓ {to_agent} responded")

            return {
                "response": f"**{to_agent}:** {response_text}",
                "thinking": thinking,
                "action": "agent_query",
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": self.get_agent_communication_log(),
            }

        except Exception as e:
            thinking.append(f"❌ Query failed: {e}")
            return {
                "response": f"❌ Query failed: {str(e)}",
                "thinking": thinking,
                "action": None,
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
            }

    def _handle_show_communication(self, thinking: list[str]) -> dict:
        """Show agent-to-agent communication log."""

        thinking.append("📋 Retrieving agent communication log...")

        comm_log = self.get_agent_communication_log()

        if comm_log == "(No agent communications)":
            return {
                "response": "No agent-to-agent communications yet.",
                "thinking": thinking,
                "action": None,
                "requires_approval": False,
                "next_suggestion": None,
                "agent_communication": None,
            }

        return {
            "response": f"## Agent Communication Log\n\n{comm_log}",
            "thinking": thinking,
            "action": "show_communication",
            "requires_approval": False,
            "next_suggestion": None,
            "agent_communication": comm_log,
        }
