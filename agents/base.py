"""
Base Agent class for Credit Pack PoC v3.2.

Provides common infrastructure for all agents:
- Configuration management
- Instruction building
- Tool declaration access
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentConfig:
    """Configuration for a specialist agent."""
    name: str
    display_name: str
    emoji: str
    model: str
    temperature: float
    instruction: str
    tools: list[str] = field(default_factory=list)
    delegates_to: list[str] = field(default_factory=list)

    @property
    def short_name(self) -> str:
        """Short name for display (without 'Agent' suffix)."""
        return self.name.replace("Agent", "")
