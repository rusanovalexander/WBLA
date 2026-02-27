"""
Phase Management System for Credit Pack v3

Manages workflow phases with state saving/restoration to allow navigation
back through phases without losing work.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
import json
import copy

from models.schemas import WorkflowPhase


class PhaseManager:
    """Manages workflow phases with state snapshots for navigation."""

    # Single source of truth: derived from WorkflowPhase enum (no manual sync needed)
    PHASES: List[str] = [p.value for p in WorkflowPhase]
    
    def __init__(self):
        self.current_phase = "SETUP"
        self.phase_snapshots: Dict[str, Dict[str, Any]] = {}
        self.phase_history: List[Dict[str, str]] = []
    
    def get_current_phase(self) -> str:
        """Get current phase name."""
        return self.current_phase
    
    def get_phase_index(self, phase: Optional[str] = None) -> int:
        """Get index of phase in workflow (0-5)."""
        phase = phase or self.current_phase
        try:
            return self.PHASES.index(phase)
        except ValueError:
            return 0
    
    def can_advance(self) -> bool:
        """Check if can advance to next phase."""
        return self.get_phase_index() < len(self.PHASES) - 1
    
    def can_go_back(self) -> bool:
        """Check if can go back to previous phase."""
        return self.get_phase_index() > 0
    
    def advance_to(self, next_phase: str, state_snapshot: Dict[str, Any]):
        """
        Advance to next phase, saving current state.
        
        Args:
            next_phase: Name of next phase
            state_snapshot: Current session state to save
        """
        if next_phase not in self.PHASES:
            raise ValueError(f"Invalid phase: {next_phase}")

        # AG-M5: Validate transition ordering — no skipping phases
        current_idx = self.get_phase_index()
        next_idx = self.PHASES.index(next_phase)
        if next_idx != current_idx + 1:
            raise ValueError(
                f"Cannot skip from {self.current_phase} to {next_phase}. "
                f"Expected next phase: {self.PHASES[current_idx + 1] if current_idx + 1 < len(self.PHASES) else 'NONE'}"
            )

        # Save current state before advancing
        self.save_phase_state(self.current_phase, state_snapshot)
        
        # Record transition
        self.phase_history.append({
            "from": self.current_phase,
            "to": next_phase,
            "timestamp": datetime.now().isoformat()
        })
        
        # Advance
        old_phase = self.current_phase
        self.current_phase = next_phase
        
        return {
            "success": True,
            "from": old_phase,
            "to": next_phase,
            "can_go_back": self.can_go_back()
        }
    
    def go_back_to(self, target_phase: str) -> Dict[str, Any]:
        """
        Navigate back to a previous phase and restore its state.
        
        Args:
            target_phase: Phase to return to
            
        Returns:
            Dict with restored state snapshot
        """
        if target_phase not in self.PHASES:
            raise ValueError(f"Invalid phase: {target_phase}")
        
        target_idx = self.get_phase_index(target_phase)
        current_idx = self.get_phase_index()
        
        if target_idx >= current_idx:
            raise ValueError("Can only go back to previous phases")
        
        # Get saved state
        if target_phase not in self.phase_snapshots:
            # No saved state - return empty restoration
            return {
                "success": True,
                "phase": target_phase,
                "restored_state": {},
                "warning": "No saved state found for this phase"
            }
        
        # Record transition
        self.phase_history.append({
            "from": self.current_phase,
            "to": target_phase,
            "timestamp": datetime.now().isoformat(),
            "navigation": "backward"
        })
        
        # Restore
        self.current_phase = target_phase
        restored_state = copy.deepcopy(self.phase_snapshots[target_phase])
        
        return {
            "success": True,
            "phase": target_phase,
            "restored_state": restored_state,
            "can_advance": self.can_advance(),
            "can_go_back": self.can_go_back()
        }
    
    def save_phase_state(self, phase: str, state: Dict[str, Any]):
        """
        Save snapshot of session state for a phase.
        
        Args:
            phase: Phase name
            state: Session state dict to save
        """
        # Create deep copy to avoid reference issues
        snapshot = copy.deepcopy(state)
        snapshot["_saved_at"] = datetime.now().isoformat()
        
        self.phase_snapshots[phase] = snapshot
    
    def get_phase_state(self, phase: str) -> Optional[Dict[str, Any]]:
        """Get saved state for a phase."""
        return self.phase_snapshots.get(phase)
    
    def has_completed_phase(self, phase: str) -> bool:
        """Check if a phase has been completed (has saved state)."""
        return phase in self.phase_snapshots
    
    def get_completed_phases(self) -> List[str]:
        """Get list of completed phases."""
        return [
            phase for phase in self.PHASES 
            if phase in self.phase_snapshots
        ]
    
    def get_phase_history(self) -> List[Dict]:
        """Get chronological phase transition history."""
        return self.phase_history.copy()
    
    def clear_phase_state(self, phase: str):
        """Clear saved state for a phase (forces re-execution)."""
        if phase in self.phase_snapshots:
            del self.phase_snapshots[phase]
    
    def reset_all(self):
        """Reset to SETUP phase, clearing all state."""
        self.current_phase = "SETUP"
        self.phase_snapshots.clear()
        self.phase_history.clear()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for session state storage."""
        return {
            "current_phase": self.current_phase,
            "phase_snapshots": self.phase_snapshots,
            "phase_history": self.phase_history
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'PhaseManager':
        """Restore from dictionary."""
        manager = cls()
        manager.current_phase = data.get("current_phase", "SETUP")
        manager.phase_snapshots = data.get("phase_snapshots", {})
        manager.phase_history = data.get("phase_history", [])
        return manager
    
    def get_navigation_info(self) -> Dict[str, Any]:
        """Get complete navigation state for UI."""
        current_idx = self.get_phase_index()
        
        nav_info = {
            "current_phase": self.current_phase,
            "current_index": current_idx,
            "total_phases": len(self.PHASES),
            "can_advance": self.can_advance(),
            "can_go_back": self.can_go_back(),
            "completed_phases": self.get_completed_phases(),
            "available_back_phases": [
                self.PHASES[i] for i in range(current_idx)
            ],
            "next_phase": self.PHASES[current_idx + 1] if self.can_advance() else None
        }
        
        return nav_info
