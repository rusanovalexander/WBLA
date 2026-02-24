"""
Persistent deal memory: user edits, facts, overrides.

Persisted per deal/session and merged into runtime persistent_context on load.
Write-through on updates. Chat turn history remains ephemeral unless explicitly saved.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class UserFact(BaseModel):
    """A user-added fact (key-value or free text)."""
    key: str = ""
    value: str = ""
    source: str = "user"  # user | override
    note: str = ""


class RequirementEdit(BaseModel):
    """User edit to a requirement (name -> new value)."""
    requirement_name: str = ""
    old_value: str = ""
    new_value: str = ""
    note: str = ""


class SectionEdit(BaseModel):
    """User edit to a drafted section."""
    section_name: str = ""
    old_content_preview: str = ""
    new_content: str = ""
    note: str = ""


class ManualOverride(BaseModel):
    """Manual process-path or decision override."""
    field: str = ""  # e.g. process_path, origination_method
    value: str = ""
    rationale: str = ""


class PersistentDealMemory(BaseModel):
    """
    Durable state for one deal/session: user facts, edits, overrides.
    Persisted to disk and merged into persistent_context at runtime.
    """
    deal_id: str = ""  # e.g. teaser filename or session id
    user_facts: list[UserFact] = Field(default_factory=list)
    requirement_edits: list[RequirementEdit] = Field(default_factory=list)
    section_edits: list[SectionEdit] = Field(default_factory=list)
    manual_overrides: list[ManualOverride] = Field(default_factory=list)

    def to_merge_dict(self) -> dict[str, Any]:
        """Export as dict to merge into persistent_context."""
        return {
            "user_added_facts": [f.model_dump() for f in self.user_facts],
            "requirement_edits": [e.model_dump() for e in self.requirement_edits],
            "section_edits": [e.model_dump() for e in self.section_edits],
            "manual_overrides": [o.model_dump() for o in self.manual_overrides],
        }

    @classmethod
    def merge_into_context(cls, context: dict[str, Any], memory: "PersistentDealMemory | None") -> None:
        """Merge persisted memory into persistent_context (in-place)."""
        if not memory:
            return
        d = memory.to_merge_dict()
        for key, value in d.items():
            if key not in context:
                context[key] = value
            elif isinstance(context[key], list) and isinstance(value, list):
                context[key] = value
            else:
                context[key] = value

    def add_fact(self, key: str, value: str, note: str = "") -> None:
        """Add or update a user fact."""
        for f in self.user_facts:
            if f.key == key:
                f.value = value
                f.note = note or f.note
                return
        self.user_facts.append(UserFact(key=key, value=value, note=note))

    def add_requirement_edit(self, name: str, old_value: str, new_value: str, note: str = "") -> None:
        """Record a requirement edit."""
        self.requirement_edits.append(
            RequirementEdit(requirement_name=name, old_value=old_value, new_value=new_value, note=note)
        )

    def add_section_edit(self, section_name: str, old_preview: str, new_content: str, note: str = "") -> None:
        """Record a section edit."""
        self.section_edits.append(
            SectionEdit(section_name=section_name, old_content_preview=old_preview, new_content=new_content, note=note)
        )

    def add_override(self, field: str, value: str, rationale: str = "") -> None:
        """Record a manual decision override."""
        self.manual_overrides.append(ManualOverride(field=field, value=value, rationale=rationale))


def get_memory_path(deal_id: str, base_dir: Path | None = None) -> Path:
    """Return file path for persisted deal memory."""
    if base_dir is None:
        from config.settings import BASE_DIR
        base_dir = BASE_DIR
    sessions_dir = base_dir / "data" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in deal_id)[:100]
    return sessions_dir / f"deal_memory_{safe_id}.json"


def load_persistent_memory(deal_id: str, base_dir: Path | None = None) -> PersistentDealMemory | None:
    """Load persisted deal memory from disk. Returns None if not found or invalid."""
    path = get_memory_path(deal_id, base_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return PersistentDealMemory(**data)
    except Exception as e:
        logger.warning("Failed to load persistent memory from %s: %s", path, e)
        return None


def save_persistent_memory(memory: PersistentDealMemory, base_dir: Path | None = None) -> bool:
    """Save deal memory to disk. Returns True on success."""
    if not memory.deal_id:
        return False
    path = get_memory_path(memory.deal_id, base_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(memory.model_dump_json(indent=2), encoding="utf-8")
        return True
    except Exception as e:
        logger.warning("Failed to save persistent memory to %s: %s", path, e)
        return False
