#!/usr/bin/env python3
"""Render the engagement drafts in drafts/*.md to Word documents in out/.

The drafts are the authoritative source: they are what gets reviewed and
diffed. This script only puts them into the house format used by the rest of
the Certainti working documents on this file — navy headings, grey straplines,
ten-point tables — so that what leaves the engagement looks like everything
else that has left it.

Supported Markdown: a YAML-ish front-matter block (eyebrow, subtitle, title,
strapline), ## and ### headings, paragraphs, - bullets, > callouts, pipe
tables with a header rule, --- horizontal rules, **bold** and _italic_ inline,
and a bare <br/> for a blank line.

Run:  python3 build_docs.py
"""

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

NAVY = RGBColor(0x1F, 0x38, 0x64)
GREY = RGBColor(0x59, 0x59, 0x59)
CALLOUT_FILL = "EAF0F8"
HEADER_FILL = "1F3864"

HERE = Path(__file__).resolve().parent
DRAFTS, OUT = HERE / "drafts", HERE / "documents"


def shade(cell, fill):
    el = OxmlElement("w:shd")
    el.set(qn("w:val"), "clear")
    el.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(el)


def inline(paragraph, text, *, bold=False, size=None, color=None):
    """Write text into a paragraph, honouring **bold** and _italic_ runs."""
    for piece in re.split(r"(\*\*[^*]+\*\*|_[^_]+_)", text):
        if not piece:
            continue
        run = paragraph.add_run()
        if piece.startswith("**") and piece.endswith("**"):
            run.text, run.bold = piece[2:-2], True
        elif piece.startswith("_") and piece.endswith("_") and len(piece) > 2:
            run.text, run.italic = piece[1:-1], True
        else:
            run.text = piece
        if bold:
            run.bold = True
        if size:
            run.font.size = Pt(size)
        if color:
            run.font.color.rgb = color
    return paragraph


def front_matter(lines):
    meta = {}
    if lines and lines[0].strip() == "---":
        end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
        for line in lines[1:end]:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
        lines = lines[end + 1:]
    return meta, lines


def masthead(doc, meta):
    if meta.get("eyebrow"):
        inline(doc.add_paragraph(), meta["eyebrow"], bold=True, size=10, color=NAVY)
    if meta.get("subtitle"):
        inline(doc.add_paragraph(), meta["subtitle"], size=9, color=GREY)
    if meta.get("title"):
        inline(doc.add_paragraph(), meta["title"], bold=True, size=16, color=NAVY)
    if meta.get("strapline"):
        inline(doc.add_paragraph(), meta["strapline"], size=11, color=GREY)
    doc.add_paragraph()


def add_table(doc, rows):
    header, body = rows[0], rows[1:]
    table = doc.add_table(rows=len(rows), cols=len(header))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    for j, text in enumerate(header):
        cell = table.rows[0].cells[j]
        shade(cell, HEADER_FILL)
        para = cell.paragraphs[0]
        inline(para, text, bold=True, size=10, color=RGBColor(0xFF, 0xFF, 0xFF))
    for i, row in enumerate(body, 1):
        for j, text in enumerate(row):
            if j >= len(header):
                continue
            inline(table.rows[i].cells[j].paragraphs[0], text, size=10)
    doc.add_paragraph()


def add_callout(doc, text):
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.rows[0].cells[0]
    shade(cell, CALLOUT_FILL)
    inline(cell.paragraphs[0], text, size=10.5)
    doc.add_paragraph()


def render(path):
    lines = path.read_text().splitlines()
    meta, lines = front_matter(lines)

    doc = Document()
    section = doc.sections[0]
    section.left_margin = section.right_margin = Inches(0.75)
    section.top_margin = section.bottom_margin = Inches(0.75)
    masthead(doc, meta)

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("|"):                      # table
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    block.append(cells)
                i += 1
            if block:
                add_table(doc, block)
            continue

        if stripped.startswith(">"):                      # callout
            block = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                block.append(lines[i].strip().lstrip(">").strip())
                i += 1
            add_callout(doc, " ".join(block))
            continue

        if stripped == "---":                             # rule
            doc.add_paragraph("─" * 60).runs[0].font.color.rgb = GREY
        elif stripped == "<br/>":
            doc.add_paragraph()
        elif stripped.startswith("### "):
            inline(doc.add_paragraph(), stripped[4:], bold=True, size=11.5, color=NAVY)
        elif stripped.startswith("## "):
            doc.add_paragraph()
            inline(doc.add_paragraph(), stripped[3:], bold=True, size=13, color=NAVY)
        elif stripped.startswith("- "):
            para = doc.add_paragraph(style="List Bullet")
            inline(para, stripped[2:])
        elif re.match(r"^\d+\. ", stripped):
            para = doc.add_paragraph(style="List Number")
            inline(para, re.sub(r"^\d+\. ", "", stripped))
        elif stripped.startswith("_") and stripped.endswith("_"):
            para = doc.add_paragraph()
            inline(para, stripped, size=9, color=GREY)
        else:
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.LEFT
            inline(para, stripped)
        i += 1

    OUT.mkdir(exist_ok=True)
    target = OUT / (re.sub(r"^\d+_", "", path.stem) + "_TM_31874271.docx")
    doc.save(target)
    return target


if __name__ == "__main__":
    drafts = sorted(DRAFTS.glob("*.md"))
    if not drafts:
        sys.exit(f"no drafts found in {DRAFTS}")
    for draft in drafts:
        print(f"{draft.name}  ->  documents/{render(draft).name}")
