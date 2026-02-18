"""
Unit tests for Credit Pack tools (error paths only — no LLM/RAG).

Run: uv run pytest credit-pack/tests/ -v
"""

import asyncio
import pytest

# Import after ensuring path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from credit_pack import tools as credit_pack_tools


class MockToolContext:
    def __init__(self):
        self.state = {}


@pytest.mark.asyncio
async def test_analyze_deal_without_teaser_returns_error():
    ctx = MockToolContext()
    out = await credit_pack_tools.analyze_deal(teaser_text="", tool_context=ctx)
    assert out["status"] == "error"
    assert "message" in out
    assert "teaser" in out["message"].lower() or "set_teaser" in out["message"].lower()


@pytest.mark.asyncio
async def test_discover_requirements_without_analysis_returns_error():
    ctx = MockToolContext()
    out = await credit_pack_tools.discover_requirements(analysis_text="", tool_context=ctx)
    assert out["status"] == "error"
    assert "message" in out


@pytest.mark.asyncio
async def test_set_teaser_stores_and_returns_success():
    ctx = MockToolContext()
    out = await credit_pack_tools.set_teaser(teaser_text="Short teaser.", tool_context=ctx)
    assert out["status"] == "success"
    assert ctx.state.get("teaser_text") == "Short teaser."


@pytest.mark.asyncio
async def test_check_compliance_without_requirements_returns_error():
    ctx = MockToolContext()
    out = await credit_pack_tools.check_compliance(requirements_json="", tool_context=ctx)
    assert out["status"] == "error"
    assert "message" in out


@pytest.mark.asyncio
async def test_generate_structure_without_analysis_returns_error():
    ctx = MockToolContext()
    out = await credit_pack_tools.generate_structure(example_text="", tool_context=ctx)
    assert out["status"] == "error"
    assert "message" in out


@pytest.mark.asyncio
async def test_draft_section_without_structure_returns_error():
    ctx = MockToolContext()
    out = await credit_pack_tools.draft_section(section_name="Executive Summary", tool_context=ctx)
    assert out["status"] == "error"
    assert "message" in out


@pytest.mark.asyncio
async def test_export_credit_pack_without_drafts_returns_error():
    ctx = MockToolContext()
    out = await credit_pack_tools.export_credit_pack(filename="", tool_context=ctx)
    assert out["status"] == "error"
    assert "message" in out


@pytest.mark.asyncio
async def test_set_example_stores_and_returns_success():
    ctx = MockToolContext()
    out = await credit_pack_tools.set_example(example_text="Example credit memo.", tool_context=ctx)
    assert out["status"] == "success"
    assert ctx.state.get("example_text") == "Example credit memo."
