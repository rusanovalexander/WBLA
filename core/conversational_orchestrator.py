"""
Conversational Orchestrator for Credit Pack PoC v3.2.

Replaces phase-based workflow with natural conversation flow.
Integrates agent-to-agent communication for collaborative analysis.
"""

from __future__ import annotations

from typing import Any, Callable
from pathlib import Path

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
from config.settings import MODEL_PRO
from core.tracing import get_tracer, TraceStore


class ConversationalOrchestrator:
    """
    Conversational orchestrator for autonomous multi-agent system.

    Features:
    - Natural conversation flow (no rigid phases)
    - Agent-to-agent communication via AgentCommunicationBus
    - Autonomous decision-making with approval checkpoints
    - Context-aware intent detection
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
        )

        self.writer = Writer(
            search_procedure_fn=self.search_procedure,
            governance_context=self.governance_context,
            agent_bus=self.agent_bus,  # Writer can query other agents
            tracer=self.tracer,
        )

        # Conversation state
        self.context = {
            "teaser_text": None,
            "teaser_filename": None,
            "example_text": None,
            "example_filename": None,
            "analysis": None,
            "requirements": [],
            "compliance_result": None,
            "compliance_checks": [],
            "structure": [],
            "drafts": {},
            "current_section_index": 0,
        }

    def _load_governance(self) -> dict[str, Any]:
        """Load governance frameworks at startup."""
        result = run_governance_discovery(
            search_procedure_fn=tool_search_procedure,
            search_guidelines_fn=tool_search_guidelines,
            tracer=self.tracer
        )
        return {
            "frameworks": result.get("frameworks", []),
            "summary": result.get("summary", ""),
            "full_context": result  # Include full governance context
        }

    def _register_agent_responders(self):
        """Register agent responder functions for inter-agent communication."""

        # Process Analyst responder
        pa_responder = create_process_analyst_responder(
            llm_caller=call_llm,
            model=MODEL_PRO,
            governance_context=self.governance_context,
        )
        self.agent_bus.register_responder("ProcessAnalyst", pa_responder)

        # Compliance Advisor responder
        ca_responder = create_compliance_advisor_responder(
            llm_caller=call_llm,
            model=MODEL_PRO,
            rag_tool=self._rag_search_guidelines,
            governance_context=self.governance_context,
        )
        self.agent_bus.register_responder("ComplianceAdvisor", ca_responder)

    def _rag_search_guidelines(self, query: str, num_results: int = 3) -> dict:
        """RAG search wrapper for compliance advisor responder."""
        try:
            return tool_search_guidelines(query, num_results=num_results)
        except Exception as e:
            return {"status": "ERROR", "results": []}

    def search_procedure(self, query: str, top_k: int = 3):
        """Search procedure documents."""
        return tool_search_procedure(query, num_results=top_k)

    def search_guidelines(self, query: str, top_k: int = 3):
        """Search guidelines documents."""
        return tool_search_guidelines(query, num_results=top_k)

    def get_governance_context(self) -> dict[str, Any]:
        """Get current governance context."""
        return self.governance_context

    def get_agent_communication_log(self) -> str:
        """Get formatted agent-to-agent communication log."""
        return self.agent_bus.get_log_formatted()

    def clear_agent_communication_log(self):
        """Clear agent communication history."""
        self.agent_bus.clear()

    def process_message(
        self,
        message: str,
        uploaded_files: dict[str, dict]
    ) -> dict[str, Any]:
        """
        Process user message and route to appropriate agent.

        Args:
            message: User's chat message
            uploaded_files: Dict of {filename: {"content": bytes, "type": str, "size": int}}

        Returns:
            {
                "response": str,  # Response text
                "thinking": [str],  # Thinking steps
                "action": str | None,  # Action taken
                "requires_approval": bool,  # Needs user confirmation
                "next_suggestion": str | None,  # Suggested next step
                "agent_communication": str | None,  # Agent-to-agent comm log
            }
        """

        thinking = []

        # Update file context
        self._update_file_context(uploaded_files, thinking)

        # Detect intent
        intent = self._detect_intent(message)
        thinking.append(f"✓ Detected intent: {intent}")

        # Route to appropriate handler
        if intent == "analyze_deal":
            return self._handle_analysis(message, thinking)
        elif intent == "discover_requirements":
            return self._handle_requirements(message, thinking)
        elif intent == "check_compliance":
            return self._handle_compliance(message, thinking)
        elif intent == "generate_structure":
            return self._handle_structure(message, thinking)
        elif intent == "draft_section":
            return self._handle_drafting(message, thinking)
        elif intent == "query_agent":
            return self._handle_agent_query(message, thinking)
        elif intent == "show_communication":
            return self._handle_show_communication(thinking)
        else:
            return self._handle_general(message, thinking)

    def _update_file_context(self, files: dict, thinking: list[str]):
        """Update context with uploaded files."""

        # Look for teaser
        teaser_file = next((f for f in files if "teaser" in f.lower()), None)
        if teaser_file and self.context["teaser_filename"] != teaser_file:
            try:
                content = files[teaser_file]["content"]
                if isinstance(content, bytes):
                    content = content.decode("utf-8")
                self.context["teaser_text"] = content
                self.context["teaser_filename"] = teaser_file
                thinking.append(f"✓ Loaded teaser: {teaser_file}")
            except Exception as e:
                thinking.append(f"⚠️ Error loading teaser: {e}")

        # Look for example pack
        example_file = next(
            (f for f in files if any(kw in f.lower() for kw in ["example", "template", "sample"])),
            None
        )
        if example_file and self.context["example_filename"] != example_file:
            try:
                content = files[example_file]["content"]
                if isinstance(content, bytes):
                    content = content.decode("utf-8")
                self.context["example_text"] = content
                self.context["example_filename"] = example_file
                thinking.append(f"✓ Loaded example: {example_file}")
            except Exception as e:
                thinking.append(f"⚠️ Error loading example: {e}")

    def _detect_intent(self, message: str) -> str:
        """Detect user intent from message."""
        message_lower = message.lower()

        # Agent communication queries
        if "show communication" in message_lower or "agent comm" in message_lower:
            return "show_communication"

        if "ask" in message_lower and any(agent in message_lower for agent in ["analyst", "compliance", "advisor"]):
            return "query_agent"

        # Workflow intents
        if any(word in message_lower for word in ["analyze", "analysis", "review deal", "start"]):
            return "analyze_deal"

        if any(word in message_lower for word in ["requirement", "discover", "what data", "what information"]):
            return "discover_requirements"

        if any(word in message_lower for word in ["compliance", "check", "regulatory", "guideline"]):
            return "check_compliance"

        if any(word in message_lower for word in ["structure", "outline", "sections", "generate structure"]):
            return "generate_structure"

        if any(word in message_lower for word in ["draft", "write", "generate", "section"]):
            return "draft_section"

        return "general"

    def _handle_analysis(self, message: str, thinking: list[str]) -> dict:
        """Handle deal analysis request."""

        if not self.context["teaser_text"]:
            return {
                "response": "❌ Please upload a teaser document first.",
                "thinking": thinking + ["❌ No teaser file found"],
                "action": None,
                "requires_approval": False,
                "next_suggestion": "Upload a teaser PDF or DOCX file to begin analysis.",
                "agent_communication": None,
            }

        thinking.append(f"📄 Using teaser: {self.context['teaser_filename']}")
        thinking.append("⏳ Running ProcessAnalyst analysis...")

        # Run analysis
        try:
            result = self.analyst.analyze_deal(
                teaser_text=self.context["teaser_text"],
                use_native_tools=True
            )

            # Update context
            self.context["analysis"] = result

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
"""

            return {
                "response": response,
                "thinking": thinking,
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

    def _handle_requirements(self, message: str, thinking: list[str]) -> dict:
        """Handle requirements discovery request."""

        if not self.context.get("analysis"):
            return {
                "response": "❌ Please complete deal analysis first.",
                "thinking": thinking + ["❌ No analysis found"],
                "action": None,
                "requires_approval": False,
                "next_suggestion": "Run analysis first: 'Analyze this deal'",
                "agent_communication": None,
            }

        thinking.append("⏳ Discovering requirements via ProcessAnalyst...")

        try:
            requirements = self.analyst.discover_requirements(
                analysis_text=self.context["analysis"]["full_analysis"],
                assessment_approach=self.context["analysis"].get("assessment_approach", ""),
                origination_method=self.context["analysis"].get("origination_method", ""),
            )

            # Update context
            self.context["requirements"] = requirements

            thinking.append(f"✓ Discovered {len(requirements)} requirements")

            # Format requirements for display
            req_list = "\n".join([
                f"{i+1}. **{r['name']}**: {r.get('value', 'Not filled')} ({r.get('status', 'pending')})"
                for i, r in enumerate(requirements)
            ])

            response = f"""## Requirements Discovered

{req_list}

---
**Total Requirements:** {len(requirements)}
"""

            return {
                "response": response,
                "thinking": thinking,
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

    def _handle_compliance(self, message: str, thinking: list[str]) -> dict:
        """Handle compliance check request."""

        if not self.context.get("requirements"):
            return {
                "response": "❌ Please discover requirements first.",
                "thinking": thinking + ["❌ No requirements found"],
                "action": None,
                "requires_approval": False,
                "next_suggestion": "Discover requirements first",
                "agent_communication": None,
            }

        thinking.append("⏳ Running ComplianceAdvisor assessment...")
        thinking.append(f"📋 Checking {len(self.context['requirements'])} requirements...")

        try:
            result_text, checks = self.advisor.assess_compliance(
                requirements=self.context["requirements"],
                teaser_text=self.context["teaser_text"],
                extracted_data=self.context["analysis"]["full_analysis"],
                use_native_tools=True
            )

            # Update context
            self.context["compliance_result"] = result_text
            self.context["compliance_checks"] = checks

            thinking.append(f"✓ Found {len(checks)} compliance considerations")

            # Format checks
            checks_list = "\n".join([
                f"- **{c.get('requirement', 'General')}**: {c.get('finding', 'N/A')} [{c.get('severity', 'info')}]"
                for c in checks[:5]  # Show first 5
            ])

            response = f"""## Compliance Assessment Complete

{result_text}

---
**Key Findings:**
{checks_list}

Total Checks: {len(checks)}
"""

            return {
                "response": response,
                "thinking": thinking,
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

    def _handle_structure(self, message: str, thinking: list[str]) -> dict:
        """Handle structure generation request."""

        if not self.context.get("analysis"):
            return {
                "response": "❌ Please complete analysis first.",
                "thinking": thinking + ["❌ No analysis found"],
                "action": None,
                "requires_approval": False,
                "next_suggestion": "Run analysis first",
                "agent_communication": None,
            }

        thinking.append("⏳ Generating document structure via Writer...")

        try:
            structure = self.writer.generate_structure(
                example_text=self.context.get("example_text", ""),
                assessment_approach=self.context["analysis"].get("assessment_approach", ""),
                origination_method=self.context["analysis"].get("origination_method", ""),
                analysis_text=self.context["analysis"]["full_analysis"],
            )

            # Update context
            self.context["structure"] = structure
            self.context["current_section_index"] = 0

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

    def _handle_drafting(self, message: str, thinking: list[str]) -> dict:
        """Handle section drafting request."""

        if not self.context.get("structure"):
            thinking.append("⚠️ No structure found, generating first...")
            # Auto-generate structure
            structure_result = self._handle_structure(message, thinking)
            if structure_result["action"] != "structure_generated":
                return structure_result

        # Determine which section to draft
        section_index = self.context["current_section_index"]

        if section_index >= len(self.context["structure"]):
            return {
                "response": "✅ All sections have been drafted!",
                "thinking": thinking + ["✓ Drafting complete"],
                "action": "drafting_complete",
                "requires_approval": False,
                "next_suggestion": "Review and finalize the document",
                "agent_communication": self.get_agent_communication_log() if self.agent_bus.message_count > 0 else None,
            }

        section = self.context["structure"][section_index]
        thinking.append(f"✏️ Drafting section {section_index + 1}/{len(self.context['structure'])}: '{section['name']}'")

        # Check if Writer might query other agents
        if self.agent_bus.message_count == 0:
            thinking.append("💬 Writer may consult ProcessAnalyst or ComplianceAdvisor...")

        try:
            draft = self.writer.draft_section(
                section=section,
                context={
                    "teaser_text": self.context["teaser_text"],
                    "analysis": self.context.get("analysis", {}),
                    "extracted_data": self.context["analysis"]["full_analysis"] if self.context.get("analysis") else "",
                    "requirements": self.context.get("requirements", []),
                    "compliance_result": self.context.get("compliance_result", ""),
                    "compliance_checks": self.context.get("compliance_checks", []),
                }
            )

            # Update context
            self.context["drafts"][section["name"]] = draft
            self.context["current_section_index"] += 1

            thinking.append(f"✓ Draft complete ({len(draft.content)} chars)")

            # Check for agent communications
            agent_comm_log = None
            if self.agent_bus.message_count > 0:
                thinking.append(f"💬 {self.agent_bus.message_count} agent-to-agent queries made")
                agent_comm_log = self.get_agent_communication_log()

            response = f"""## {section['name']}

{draft.content}

---
**Draft Status:** {section_index + 1}/{len(self.context['structure'])} sections complete
"""

            next_section = None
            if self.context["current_section_index"] < len(self.context["structure"]):
                next_section = self.context["structure"][self.context["current_section_index"]]["name"]

            return {
                "response": response,
                "thinking": thinking,
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
                    "teaser_text": self.context.get("teaser_text", ""),
                    "extracted_data": self.context["analysis"]["full_analysis"] if self.context.get("analysis") else "",
                    "requirements": self.context.get("requirements", []),
                    "compliance_result": self.context.get("compliance_result", ""),
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

    def _handle_general(self, message: str, thinking: list[str]) -> dict:
        """Handle general questions and guidance."""

        thinking.append("💡 Providing general guidance")

        # Build status summary
        status_parts = []
        if self.context.get("teaser_text"):
            status_parts.append(f"✓ Teaser loaded: {self.context['teaser_filename']}")
        else:
            status_parts.append("○ No teaser uploaded")

        if self.context.get("analysis"):
            status_parts.append("✓ Analysis complete")
        else:
            status_parts.append("○ Analysis pending")

        if self.context.get("requirements"):
            status_parts.append(f"✓ {len(self.context['requirements'])} requirements discovered")
        else:
            status_parts.append("○ Requirements pending")

        if self.context.get("compliance_checks"):
            status_parts.append(f"✓ {len(self.context['compliance_checks'])} compliance checks")
        else:
            status_parts.append("○ Compliance pending")

        if self.context.get("structure"):
            status_parts.append(f"✓ {len(self.context['structure'])} sections structured")
            status_parts.append(f"✓ {len(self.context['drafts'])} sections drafted")
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

        return {
            "response": response,
            "thinking": thinking,
            "action": None,
            "requires_approval": False,
            "next_suggestion": None,
            "agent_communication": None,
        }

    def _suggest_next_step(self) -> str:
        """Suggest next logical step based on current state."""

        if not self.context.get("teaser_text"):
            return "1. Upload a teaser document\n2. Say 'Analyze this deal'"

        if not self.context.get("analysis"):
            return "Say 'Analyze this deal' to begin"

        if not self.context.get("requirements"):
            return "Say 'Discover requirements' to continue"

        if not self.context.get("compliance_checks"):
            return "Say 'Run compliance checks' to continue"

        if not self.context.get("structure"):
            return "Say 'Generate structure' to begin drafting"

        if self.context["current_section_index"] < len(self.context["structure"]):
            next_section = self.context["structure"][self.context["current_section_index"]]["name"]
            return f"Say 'Draft next section' to write '{next_section}'"

        return "All steps complete! Review your draft."
