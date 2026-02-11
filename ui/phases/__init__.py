"""
UI Phases - Phase-specific rendering modules

Each phase is a self-contained module with a render_phase_XXX() function.
"""

from .setup import render_phase_setup
from .analysis import render_phase_analysis
from .process_gaps import render_phase_process_gaps
from .compliance import render_phase_compliance
from .drafting import render_phase_drafting
from .complete import render_phase_complete

__all__ = [
    "render_phase_setup",
    "render_phase_analysis",
    "render_phase_process_gaps",
    "render_phase_compliance",
    "render_phase_drafting",
    "render_phase_complete",
]
