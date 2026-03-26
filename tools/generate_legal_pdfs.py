#!/usr/bin/env python3
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)


PAGE_WIDTH, PAGE_HEIGHT = A4
TEXT = colors.HexColor("#111111")
MUTED = colors.HexColor("#555555")
RULE = colors.HexColor("#C8C8C8")
TOP_MARGIN = 24 * mm
BOTTOM_MARGIN = 18 * mm
LEFT_MARGIN = 24 * mm
RIGHT_MARGIN = 24 * mm


@dataclass(frozen=True)
class DocumentSpec:
    source: Path
    output: Path
    kind: str


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="Body",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.2,
            leading=14.5,
            textColor=TEXT,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TitleBlock",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=TEXT,
            alignment=TA_LEFT,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Meta",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=11.5,
            textColor=MUTED,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="H2",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=16,
            textColor=TEXT,
            spaceBefore=10,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="LegalBullet",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.2,
            leading=14.5,
            leftIndent=12,
            firstLineIndent=0,
            textColor=TEXT,
            spaceAfter=3,
        )
    )
    return styles


def escape_inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(
        r"`([^`]+)`",
        lambda match: f'<font face="Courier">{html.escape(match.group(1), quote=False)}</font>',
        escaped,
    )
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda match: f'<link href="{html.escape(match.group(2), quote=True)}" color="#1E5A96">{html.escape(match.group(1), quote=False)}</link>',
        escaped,
    )
    return escaped


def iter_blocks(lines: list[str]) -> Iterable[tuple[str, object]]:
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("# "):
            yield ("h1", stripped[2:].strip())
            i += 1
            continue
        if stripped.startswith("## "):
            yield ("h2", stripped[3:].strip())
            i += 1
            continue
        if stripped.startswith("- "):
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:].strip())
                i += 1
            yield ("ul", items)
            continue
        if re.match(r"\d+\.\s", stripped):
            items = []
            while i < len(lines) and re.match(r"\d+\.\s", lines[i].strip()):
                items.append(re.sub(r"^\d+\.\s*", "", lines[i].strip()))
                i += 1
            yield ("ol", items)
            continue
        para = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt:
                i += 1
                break
            if nxt.startswith("# ") or nxt.startswith("## ") or nxt.startswith("- ") or re.match(r"\d+\.\s", nxt):
                break
            para.append(nxt)
            i += 1
        yield ("p", " ".join(para))


def build_story(spec: DocumentSpec):
    styles = build_styles()
    text = spec.source.read_text(encoding="utf-8")
    lines = text.splitlines()
    story = []

    title = ""
    last_updated = None
    start_idx = 0
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        start_idx = 1
    for idx in range(start_idx, min(len(lines), start_idx + 6)):
        stripped = lines[idx].strip()
        if stripped.lower().startswith("last updated:"):
            last_updated = stripped.split(":", 1)[1].strip()
            start_idx = idx + 1
            break

    story.append(Paragraph(escape_inline(title or spec.output.stem.replace("_", " ")), styles["TitleBlock"]))
    if last_updated:
        story.append(Paragraph(f"Last updated: {html.escape(last_updated)}", styles["Meta"]))
    story.append(Spacer(1, 8))

    for block_type, payload in iter_blocks(lines[start_idx:]):
        if block_type == "h1":
            if story:
                story.append(PageBreak())
            story.append(Paragraph(escape_inline(str(payload)), styles["TitleBlock"]))
            continue
        if block_type == "h2":
            story.append(Paragraph(escape_inline(str(payload)), styles["H2"]))
            continue
        if block_type == "p":
            story.append(Paragraph(escape_inline(str(payload)), styles["Body"]))
            continue
        if block_type in {"ul", "ol"}:
            numbered = block_type == "ol"
            for idx, item in enumerate(payload, start=1):
                bullet = f"{idx}." if numbered else u"\u2022"
                story.append(Paragraph(escape_inline(item), styles["LegalBullet"], bulletText=bullet))
            story.append(Spacer(1, 3))
            continue
    return story


def draw_frame(canvas, doc, title: str):
    canvas.saveState()
    canvas.setTitle(title)
    canvas.setAuthor("Planetka")
    canvas.setSubject(title)

    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(LEFT_MARGIN, BOTTOM_MARGIN - 4 * mm, PAGE_WIDTH - RIGHT_MARGIN, BOTTOM_MARGIN - 4 * mm)

    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    page_label = f"Page {doc.page}"
    canvas.drawString(LEFT_MARGIN, 10 * mm, "Planetka")
    canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, 10 * mm, page_label)

    canvas.restoreState()


def build_pdf(spec: DocumentSpec):
    spec.output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(spec.output),
        pagesize=A4,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title=spec.output.stem,
        author="Planetka",
    )
    story = build_story(spec)
    title = spec.source.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
    doc.build(story, onFirstPage=lambda c, d: draw_frame(c, d, title), onLaterPages=lambda c, d: draw_frame(c, d, title))


def main():
    root = Path(__file__).resolve().parents[1]
    specs = [
        DocumentSpec(
            source=root / "Documentation" / "Licencing" / "TERMS_OF_SERVICE.md",
            output=root / "Documentation" / "Licencing" / "TERMS_OF_SERVICE.pdf",
            kind="Terms of Service",
        ),
        DocumentSpec(
            source=root / "Documentation" / "Licencing" / "PRIVACY_POLICY.md",
            output=root / "Documentation" / "Licencing" / "PRIVACY_POLICY.pdf",
            kind="Privacy Policy",
        ),
    ]
    for spec in specs:
        build_pdf(spec)
        print(f"Wrote {spec.output}")


if __name__ == "__main__":
    main()
