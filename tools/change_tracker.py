"""
Change Tracking System for Credit Pack v3

Tracks all human modifications to ensure they're preserved through the workflow
and included in final export with full audit trail.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
import json


class ChangeLog:
    """Tracks all human changes to generated content."""
    
    def __init__(self):
        self.changes: List[Dict[str, Any]] = []
    
    def record_change(
        self,
        change_type: str,
        field_name: str,
        old_value: str,
        new_value: str,
        phase: str,
        user_note: str = "",
        metadata: Optional[Dict] = None
    ):
        """
        Record a change made by human.
        
        Args:
            change_type: "requirement_edit", "section_edit", "manual_input", etc.
            field_name: Which field/section was changed
            old_value: Original AI-generated or extracted value
            new_value: Human-provided value
            phase: Which workflow phase (ANALYSIS, PROCESS_GAPS, etc.)
            user_note: Optional explanation from user
            metadata: Additional context
        """
        change_entry = {
            "id": len(self.changes) + 1,
            "timestamp": datetime.now().isoformat(),
            "type": change_type,
            "field": field_name,
            "old_value": old_value[:1000] if old_value else "",
            "new_value": new_value[:1000] if new_value else "",
            "phase": phase,
            "user_note": user_note,
            "metadata": metadata or {},
        }
        self.changes.append(change_entry)
    
    def get_changes_by_phase(self, phase: str) -> List[Dict]:
        """Get all changes for a specific phase."""
        return [c for c in self.changes if c["phase"] == phase]
    
    def get_changes_by_field(self, field_name: str) -> List[Dict]:
        """Get all changes for a specific field."""
        return [c for c in self.changes if c["field"] == field_name]
    
    def get_all_changes(self) -> List[Dict]:
        """Get all changes in chronological order."""
        return self.changes.copy()
    
    def has_changes(self) -> bool:
        """Check if any changes have been recorded."""
        return len(self.changes) > 0
    
    def get_change_count(self) -> int:
        """Get total number of changes."""
        return len(self.changes)
    
    def generate_audit_trail(self) -> str:
        """Generate markdown audit trail for export."""
        if not self.changes:
            return "## Audit Trail\n\nNo human modifications recorded.\n"
        
        trail = "## Audit Trail\n\n"
        trail += f"**Total Modifications:** {len(self.changes)}\n\n"
        
        # Group by phase
        phases = {}
        for change in self.changes:
            phase = change["phase"]
            if phase not in phases:
                phases[phase] = []
            phases[phase].append(change)
        
        for phase, phase_changes in phases.items():
            trail += f"### {phase} Phase ({len(phase_changes)} changes)\n\n"
            trail += "| # | Field | Type | Timestamp |\n"
            trail += "|---|-------|------|------------|\n"
            
            for c in phase_changes:
                timestamp = c["timestamp"].split("T")[1][:8]  # HH:MM:SS
                trail += f"| {c['id']} | {c['field']} | {c['type']} | {timestamp} |\n"
            
            trail += "\n"
        
        return trail
    
    def export_to_json(self) -> str:
        """Export complete change log as JSON."""
        return json.dumps(self.changes, indent=2)
    
    def verify_before_export(self) -> Dict[str, Any]:
        """
        Verify all changes are accounted for before export.
        Returns verification status and warnings.
        """
        verification = {
            "status": "OK",
            "total_changes": len(self.changes),
            "warnings": [],
            "change_types": {},
        }
        
        # Count by type
        for change in self.changes:
            change_type = change["type"]
            verification["change_types"][change_type] = \
                verification["change_types"].get(change_type, 0) + 1
        
        # Warnings for missing notes on critical changes
        critical_without_notes = [
            c for c in self.changes 
            if c["type"] in ["requirement_edit", "section_edit"] 
            and not c.get("user_note")
        ]
        
        if critical_without_notes:
            verification["warnings"].append(
                f"{len(critical_without_notes)} critical changes lack explanatory notes"
            )
        
        return verification
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for session state storage."""
        return {
            "changes": self.changes
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ChangeLog':
        """Restore from dictionary."""
        log = cls()
        log.changes = data.get("changes", [])
        return log
