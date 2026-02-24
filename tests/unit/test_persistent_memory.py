"""
Unit tests for persistent deal memory.

- PersistentDealMemory merge into context
- load/save roundtrip
- add_fact, add_requirement_edit, add_override
"""

from __future__ import annotations

import json
import tempfile
import pytest
from pathlib import Path

from models.persistent_memory import (
    PersistentDealMemory,
    UserFact,
    RequirementEdit,
    ManualOverride,
    load_persistent_memory,
    save_persistent_memory,
    get_memory_path,
)


def test_persistent_deal_memory_to_merge_dict():
    """to_merge_dict exports lists that can be merged into persistent_context."""
    mem = PersistentDealMemory(deal_id="teaser1.pdf")
    mem.add_fact("sector", "infrastructure", "user said")
    mem.add_override("process_path", "Standard", "manual choice")
    d = mem.to_merge_dict()
    assert "user_added_facts" in d
    assert len(d["user_added_facts"]) == 1
    assert d["user_added_facts"][0]["key"] == "sector"
    assert d["user_added_facts"][0]["value"] == "infrastructure"
    assert "manual_overrides" in d
    assert len(d["manual_overrides"]) == 1


def test_merge_into_context():
    """merge_into_context updates context in-place."""
    context = {"uploaded_files": {}, "user_added_facts": []}
    mem = PersistentDealMemory(deal_id="x")
    mem.add_fact("key1", "value1")
    PersistentDealMemory.merge_into_context(context, mem)
    assert len(context["user_added_facts"]) == 1
    assert context["user_added_facts"][0]["key"] == "key1"


def test_merge_into_context_none():
    """merge_into_context with None does nothing."""
    context = {"user_added_facts": []}
    PersistentDealMemory.merge_into_context(context, None)
    assert context["user_added_facts"] == []


def test_add_fact_updates_existing():
    """add_fact updates value when key already exists."""
    mem = PersistentDealMemory(deal_id="x")
    mem.add_fact("a", "v1")
    mem.add_fact("a", "v2")
    assert len(mem.user_facts) == 1
    assert mem.user_facts[0].value == "v2"


def test_save_and_load_roundtrip(tmp_path):
    """Save and load PersistentDealMemory roundtrip."""
    mem = PersistentDealMemory(deal_id="test_deal")
    mem.add_fact("sector", "real_estate")
    mem.add_requirement_edit("LTV", "old", "new", "user edit")
    saved = save_persistent_memory(mem, base_dir=tmp_path)
    assert saved is True
    loaded = load_persistent_memory("test_deal", base_dir=tmp_path)
    assert loaded is not None
    assert loaded.deal_id == mem.deal_id
    assert len(loaded.user_facts) == 1
    assert loaded.user_facts[0].key == "sector"
    assert len(loaded.requirement_edits) == 1
    assert loaded.requirement_edits[0].requirement_name == "LTV"


def test_load_missing_returns_none(tmp_path):
    """load_persistent_memory returns None for missing file."""
    loaded = load_persistent_memory("nonexistent_id_123", base_dir=tmp_path)
    assert loaded is None
