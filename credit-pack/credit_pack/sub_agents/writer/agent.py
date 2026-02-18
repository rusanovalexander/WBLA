# Phase 2: LlmAgent for structure and section drafting.
from google.adk.agents import LlmAgent

from .prompt import get_instruction

writer_agent = LlmAgent(
    model="gemini-2.5-flash",
    name="writer",
    instruction=get_instruction(),
    tools=[],
)
