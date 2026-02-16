"""
Internal helper for streaming thinking steps to the UI.

A list-like that invokes an optional callback on each append,
so the orchestrator can push steps in real time without changing handler signatures.
"""

from __future__ import annotations

from typing import Callable


class StreamingThinkingList(list):
    """List that forwards each appended item to an optional callback (for live UI updates)."""

    def __init__(self, on_step: Callable[[str], None] | None = None):
        super().__init__()
        self._on_step = on_step

    def append(self, step: str) -> None:
        super().append(step)
        if self._on_step is not None:
            try:
                self._on_step(step)
            except Exception:
                pass
