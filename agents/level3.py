"""
Level 3 Infrastructure for Credit Pack PoC v3.2.

Agent communication bus and responder factories.
Simplified from v3.0 — parsing logic moved to core/parsers.py.
"""

from __future__ import annotations

from typing import Any, Callable

from models.schemas import AgentMessage
from core.parsers import format_requirements_for_context


# =============================================================================
# Agent Communication Bus
# =============================================================================

class AgentCommunicationBus:
    """
    Enables agents to query each other directly for genuine gaps.

    Use Cases:
    - Writer queries ProcessAnalyst for data clarification
    - Writer queries ComplianceAdvisor for guideline context
    """

    def __init__(self):
        self.message_log: list[AgentMessage] = []
        self._responders: dict[str, Callable] = {}

    def register_responder(self, agent_name: str, responder_func: Callable):
        """Register a responder function for an agent."""
        self._responders[agent_name] = responder_func

    def query(
        self,
        from_agent: str,
        to_agent: str,
        query: str,
        context: dict[str, Any],
    ) -> str:
        """Route a query from one agent to another."""
        message = AgentMessage(
            from_agent=from_agent,
            to_agent=to_agent,
            query=query,
        )

        if to_agent in self._responders:
            response = self._responders[to_agent](query, context)
        else:
            response = f"[Agent {to_agent} not registered]"

        message.response = response
        self.message_log.append(message)
        return response

    def get_log_formatted(self) -> str:
        """Get formatted communication log for audit trail."""
        if not self.message_log:
            return "(No agent communications)"

        lines: list[str] = []
        for msg in self.message_log:
            lines.append(f"**[{msg.timestamp}]** {msg.from_agent} → {msg.to_agent}")
            lines.append(f"  Q: {msg.query}")
            preview = msg.response[:200] + "..." if len(msg.response) > 200 else msg.response
            lines.append(f"  A: {preview}")
            lines.append("")
        return "\n".join(lines)

    def clear(self):
        self.message_log = []

    @property
    def message_count(self) -> int:
        return len(self.message_log)


# =============================================================================
# Responder Factories
# =============================================================================

def create_process_analyst_responder(
    llm_caller: Callable,
    model: str,
) -> Callable:
    """Create a responder function for Process Analyst inter-agent queries."""

    def responder(query: str, context: dict) -> str:
        teaser_text = context.get("teaser_text", "")
        extracted_data = context.get("extracted_data", "")
        requirements = context.get("requirements", [])
        filled_reqs = format_requirements_for_context(requirements)

        prompt = f"""You are the Process Analyst. Another agent needs information from your analysis.

## THEIR QUESTION
{query}

## YOUR KNOWLEDGE BASE

### Original Teaser:
{teaser_text}

### Your Extracted Analysis:
{extracted_data}

### Filled Requirements:
{filled_reqs}

## INSTRUCTIONS

Answer their question based on the teaser and your analysis:
- Be specific and cite source quotes where possible
- If the information is not available, say so clearly
- Keep response focused (under 400 words)
"""
        result = llm_caller(prompt, model, 0.0, 1200, "ProcessAnalyst")
        return result.text if hasattr(result, "text") else str(result)

    return responder


def create_compliance_advisor_responder(
    llm_caller: Callable,
    model: str,
    rag_tool: Callable,
) -> Callable:
    """Create a responder function for Compliance Advisor inter-agent queries."""

    def responder(query: str, context: dict) -> str:
        rag_result = rag_tool(query, num_results=3)
        rag_text = ""
        if rag_result.get("status") == "OK":
            for r in rag_result.get("results", [])[:2]:
                title = r.get("title", "Guideline")
                content = r.get("content", "")[:1000]
                rag_text += f"\n**{title}:**\n{content}\n"

        compliance_result = context.get("compliance_result", "")

        prompt = f"""You are the Compliance Advisor. Another agent needs compliance information.

## THEIR QUESTION
{query}

## GUIDELINES (from RAG search)
{rag_text if rag_text else "(No specific guidelines found)"}

## YOUR COMPLIANCE ASSESSMENT
{compliance_result[:4000] if compliance_result else "(Not yet completed)"}

## INSTRUCTIONS

Answer their question based on the Guidelines:
- Cite specific section numbers from the Guidelines document
- Provide exact limits/thresholds where relevant
- Keep response focused (under 400 words)
"""
        result = llm_caller(prompt, model, 0.0, 1200, "ComplianceAdvisor")
        return result.text if hasattr(result, "text") else str(result)

    return responder
