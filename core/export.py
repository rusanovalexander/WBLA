"""
Export module for Credit Pack PoC v3.2.

Generates professional DOCX output and audit trail files.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import BASE_DIR, VERSION
from core.tracing import TraceStore, get_tracer

logger = logging.getLogger(__name__)


# =============================================================================
# DOCX Generation — Professional Banking Format
# =============================================================================

def generate_docx(
    content: str,
    filename: str,
    metadata: dict[str, str] | None = None,
) -> str:
    """
    Generate professional DOCX from markdown content.

    Args:
        content: Markdown content
        filename: Output filename
        metadata: Optional metadata (deal_name, process_path, etc.)

    Returns:
        Path to saved file, or "" on error
    """
    try:
        from docx import Document
        from docx.shared import Pt, Inches, Cm, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.enum.section import WD_ORIENT
        from docx.oxml.ns import qn

        doc = Document()

        # ---- Page Setup ----
        section = doc.sections[0]
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(1.2)
        section.right_margin = Inches(1.2)

        # ---- Styles ----
        style = doc.styles["Normal"]
        style.font.name = "Calibri"
        style.font.size = Pt(10.5)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.line_spacing = 1.15

        for level, (size, bold) in enumerate([(18, True), (14, True), (12, True)], 1):
            heading_style = doc.styles[f"Heading {level}"]
            heading_style.font.name = "Calibri"
            heading_style.font.size = Pt(size)
            heading_style.font.bold = bold
            heading_style.font.color.rgb = RGBColor(0x1B, 0x3A, 0x5C)  # Dark blue
            heading_style.paragraph_format.space_before = Pt(18 if level == 1 else 12)
            heading_style.paragraph_format.space_after = Pt(8)

        # ---- Cover Page ----
        doc.add_paragraph()
        doc.add_paragraph()
        doc.add_paragraph()

        title_para = doc.add_paragraph()
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_run = title_para.add_run("CREDIT PACK")
        title_run.font.size = Pt(28)
        title_run.font.bold = True
        title_run.font.color.rgb = RGBColor(0x1B, 0x3A, 0x5C)
        title_run.font.name = "Calibri"

        if metadata:
            subtitle = doc.add_paragraph()
            subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
            deal_name = metadata.get("deal_name", "")
            if deal_name:
                sub_run = subtitle.add_run(deal_name)
                sub_run.font.size = Pt(16)
                sub_run.font.color.rgb = RGBColor(0x4A, 0x4A, 0x4A)

        doc.add_paragraph()

        # Metadata table on cover
        meta_para = doc.add_paragraph()
        meta_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        meta_items = [
            f"Generated: {datetime.now().strftime('%d %B %Y')}",
            f"System: Credit Pack Multi-Agent PoC v{VERSION}",
        ]
        if metadata:
            if metadata.get("process_path"):
                meta_items.append(f"Assessment: {metadata['process_path']}")
            if metadata.get("origination_method"):
                meta_items.append(f"Origination: {metadata['origination_method']}")

        for item in meta_items:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(item)
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

        doc.add_paragraph()
        _add_classification_banner(doc, "CONFIDENTIAL — FOR INTERNAL USE ONLY")

        # Page break after cover
        doc.add_page_break()

        # ---- Content ----
        _render_markdown_to_docx(doc, content)

        # ---- Footer ----
        footer = doc.sections[0].footer
        footer_para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        footer_run = footer_para.add_run(
            f"Credit Pack — Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} — "
            f"Multi-Agent System v{VERSION}"
        )
        footer_run.font.size = Pt(8)
        footer_run.font.color.rgb = RGBColor(0xA0, 0xA0, 0xA0)

        # ---- Save ----
        output_dir = BASE_DIR / "outputs"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / filename
        doc.save(str(output_path))

        logger.info("DOCX saved: %s", output_path)
        return str(output_path)

    except ImportError:
        logger.error("python-docx not installed")
        return ""
    except Exception as e:
        logger.error("DOCX generation failed: %s", e, exc_info=True)
        return ""


def _add_classification_banner(doc, text: str):
    """Add a classification banner paragraph."""
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    run.font.size = Pt(9)
    run.font.bold = True
    run.font.color.rgb = RGBColor(0xCC, 0x00, 0x00)


def _render_markdown_to_docx(doc, content: str):
    """Convert markdown content to DOCX elements with proper formatting."""
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    lines = content.split("\n")
    current_table_rows: list[list[str]] = []
    in_table = False

    for line in lines:
        stripped = line.strip()

        # Table detection
        if stripped.startswith("|") and "|" in stripped[1:]:
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            # Skip separator rows
            if cells and not all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
                current_table_rows.append(cells)
                in_table = True
            continue
        elif in_table and current_table_rows:
            _add_styled_table(doc, current_table_rows)
            current_table_rows = []
            in_table = False

        # Skip empty lines
        if not stripped:
            continue

        # Headings — full hierarchy
        if stripped.startswith("# ") and not stripped.startswith("## "):
            doc.add_heading(stripped[2:].strip(), level=1)
        elif stripped.startswith("## ") and not stripped.startswith("### "):
            doc.add_heading(stripped[3:].strip(), level=2)
        elif stripped.startswith("### ") and not stripped.startswith("#### "):
            doc.add_heading(stripped[4:].strip(), level=3)
        elif stripped.startswith("#### "):
            doc.add_heading(stripped[5:].strip(), level=3)
        elif stripped.startswith("---"):
            # Horizontal rule — subtle spacing
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(6)
        elif stripped.startswith("- ") or stripped.startswith("* "):
            # Bullet point
            bullet_text = stripped[2:].strip()
            try:
                p = doc.add_paragraph(style="List Bullet")
            except KeyError:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.5)
                # Add bullet character manually
                bullet_text = f"• {bullet_text}"
            _add_formatted_text(p, bullet_text)
        elif len(stripped) > 2 and stripped[0].isdigit() and ". " in stripped[:5]:
            # Numbered list (e.g., "1. Item")
            num_prefix = stripped.split(". ", 1)[0]
            num_text = stripped.split(". ", 1)[1] if ". " in stripped else stripped
            try:
                p = doc.add_paragraph(style="List Number")
                _add_formatted_text(p, num_text)
            except KeyError:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.5)
                _add_formatted_text(p, f"{num_prefix}. {num_text}")
        else:
            # Regular paragraph with inline formatting
            p = doc.add_paragraph()
            _add_formatted_text(p, stripped)

    # Flush remaining table
    if current_table_rows:
        _add_styled_table(doc, current_table_rows)


def _add_formatted_text(paragraph, text: str):
    """Add text to paragraph with bold/italic formatting preserved."""
    from docx.shared import RGBColor

    # Handle [INFORMATION REQUIRED: ...] markers
    if "[INFORMATION REQUIRED:" in text:
        parts = re.split(r"(\[INFORMATION REQUIRED:[^\]]+\])", text)
        for part in parts:
            if part.startswith("[INFORMATION REQUIRED:"):
                run = paragraph.add_run(part)
                run.font.color.rgb = RGBColor(0xCC, 0x00, 0x00)
                run.font.bold = True
            else:
                _add_inline_formatted(paragraph, part)
        return

    _add_inline_formatted(paragraph, text)


def _add_inline_formatted(paragraph, text: str):
    """Handle **bold** and *italic* inline formatting."""
    # Split on bold markers
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.font.bold = True
        elif part.startswith("*") and part.endswith("*"):
            run = paragraph.add_run(part[1:-1])
            run.font.italic = True
        elif part:
            # Clean remaining markdown (preserve whitespace-only parts for word spacing)
            clean = re.sub(r"\*([^*]+)\*", r"\1", part)
            paragraph.add_run(clean)


def _add_styled_table(doc, rows: list[list[str]]):
    """Add a professionally styled table to the document."""
    from docx.shared import Pt, Inches, RGBColor, Cm
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.oxml.ns import qn

    if not rows:
        return

    # Normalize column count
    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]

    table = doc.add_table(rows=len(normalized), cols=max_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for i, row_data in enumerate(normalized):
        for j, cell_text in enumerate(row_data):
            cell = table.cell(i, j)
            cell.text = ""
            p = cell.paragraphs[0]
            run = p.add_run(cell_text.strip())
            run.font.size = Pt(9)
            run.font.name = "Calibri"

            # Header row styling
            if i == 0:
                run.font.bold = True
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                shading = cell._element.get_or_add_tcPr()
                shading_elm = shading.makeelement(
                    qn("w:shd"),
                    {qn("w:val"): "clear", qn("w:color"): "auto", qn("w:fill"): "1B3A5C"}
                )
                shading.append(shading_elm)
            elif i % 2 == 0:
                # Alternating row color
                shading = cell._element.get_or_add_tcPr()
                shading_elm = shading.makeelement(
                    qn("w:shd"),
                    {qn("w:val"): "clear", qn("w:color"): "auto", qn("w:fill"): "F2F7FB"}
                )
                shading.append(shading_elm)

    doc.add_paragraph()  # Spacing after table


# =============================================================================
# Audit Trail Export
# =============================================================================

def generate_audit_trail(
    session_state: dict[str, Any],
    tracer: TraceStore | None = None,
    filename: str = "",
) -> str:
    """
    Generate comprehensive audit trail file.

    Collects all in-memory audit data: process decisions, agent activity,
    inter-agent communication, human changes, phase history, RAG sources.
    """
    if tracer is None:
        tracer = get_tracer()

    if not filename:
        filename = f"audit_trail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    lines = [
        "=" * 70,
        f"CREDIT PACK AUDIT TRAIL — v{VERSION}",
        f"Generated: {datetime.now().isoformat()}",
        "=" * 70,
        "",
    ]

    # 1. Process Decision
    decision = session_state.get("process_decision")
    if decision:
        lines.extend([
            "─" * 50,
            "PROCESS DECISION",
            "─" * 50,
            f"Assessment Approach: {decision.get('assessment_approach', 'N/A')}",
            f"Origination Method: {decision.get('origination_method', 'N/A')}",
            f"Locked: {decision.get('locked', False)}",
            f"Timestamp: {decision.get('timestamp', 'N/A')}",
        ])
        evidence = decision.get("evidence", {})
        if evidence:
            lines.append(f"Deal Size: {evidence.get('deal_size', 'Unknown')}")
            lines.append(f"Reasoning: {evidence.get('reasoning', 'N/A')}")
        lines.append("")

    # 2. Agent Activity Trace
    lines.extend([
        "─" * 50,
        "AGENT ACTIVITY TRACE",
        "─" * 50,
        tracer.format_for_export(),
        "",
    ])

    # 3. Agent Summary
    summary = tracer.get_agent_summary()
    if summary:
        lines.extend(["─" * 50, "AGENT COST SUMMARY", "─" * 50])
        for agent, stats in summary.items():
            lines.append(
                f"  {agent:25s} | Calls: {stats['calls']:2d} | "
                f"Tokens: {stats['tokens_in']:,} in / {stats['tokens_out']:,} out | "
                f"Cost: ${stats['cost_usd']:.4f} | Time: {stats['total_ms']}ms"
            )
        tokens_in, tokens_out = tracer.total_tokens
        lines.extend([
            "",
            f"  TOTAL: {tracer.total_calls} calls | "
            f"{tokens_in:,} in / {tokens_out:,} out | ${tracer.total_cost:.4f}",
            "",
        ])

    # 4. Change Log
    change_log = session_state.get("change_log")
    if change_log and hasattr(change_log, "has_changes") and change_log.has_changes():
        lines.extend(["─" * 50, "HUMAN CHANGES", "─" * 50])
        lines.append(change_log.generate_audit_trail())
        lines.append("")

    # 5. Agent Communication
    agent_bus = session_state.get("agent_bus")
    if agent_bus and hasattr(agent_bus, "message_count") and agent_bus.message_count > 0:
        lines.extend([
            "─" * 50,
            "AGENT-TO-AGENT COMMUNICATION",
            "─" * 50,
            agent_bus.get_log_formatted(),
            "",
        ])

    # 6. Phase History
    phase_manager = session_state.get("phase_manager")
    if phase_manager and hasattr(phase_manager, "get_phase_history"):
        history = phase_manager.get_phase_history()
        if history:
            lines.extend(["─" * 50, "PHASE NAVIGATION HISTORY", "─" * 50])
            for h in history:
                nav = h.get("navigation", "forward")
                lines.append(f"  {h.get('timestamp', '')} | {h['from']} → {h['to']} ({nav})")
            lines.append("")

    # Save
    output_dir = BASE_DIR / "outputs"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / filename

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    logger.info("Audit trail saved: %s", output_path)
    return str(output_path)
