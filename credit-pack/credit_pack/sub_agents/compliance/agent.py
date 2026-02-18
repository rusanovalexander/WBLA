# Phase 2: LlmAgent for compliance check.
from google.adk.agents import LlmAgent

from .prompt import get_instruction

compliance_agent = LlmAgent(
    model="gemini-2.5-flash",
    name="compliance",
    instruction=get_instruction(),
    tools=[],
)
