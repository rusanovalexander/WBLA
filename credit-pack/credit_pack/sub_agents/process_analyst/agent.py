# Phase 2: LlmAgent for deal analysis + RAG tools.
# Will wrap existing ProcessAnalyst logic or use AgentTool from root.
from google.adk.agents import LlmAgent

from .prompt import get_instruction

process_analyst_agent = LlmAgent(
    model="gemini-2.5-flash",
    name="process_analyst",
    instruction=get_instruction(),
    tools=[],  # Phase 2: RAG tools
)
