from __future__ import annotations

import html
import re
import textwrap
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.utils import ImageReader


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "user-guide-uk.md"
OUT = ROOT / "output" / "pdf" / "agent-factory-user-guide-uk.pdf"

FONT_REGULAR = Path(r"C:\Windows\Fonts\arial.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\arialbd.ttf")
FONT_MONO = Path(r"C:\Windows\Fonts\consola.ttf")
if FONT_REGULAR.exists() and FONT_BOLD.exists():
    pdfmetrics.registerFont(TTFont("AFArial", str(FONT_REGULAR)))
    pdfmetrics.registerFont(TTFont("AFArialBold", str(FONT_BOLD)))
    BODY_FONT, BOLD_FONT = "AFArial", "AFArialBold"
else:
    BODY_FONT, BOLD_FONT = "Helvetica", "Helvetica-Bold"
if FONT_MONO.exists():
    pdfmetrics.registerFont(TTFont("AFConsolas", str(FONT_MONO)))
    CODE_FONT = "AFConsolas"
else:
    CODE_FONT = BODY_FONT

NAVY = colors.HexColor("#0B172A")
INK = colors.HexColor("#203247")
MUTED = colors.HexColor("#64748B")
BLUE = colors.HexColor("#2563EB")
CYAN = colors.HexColor("#0891B2")
PALE = colors.HexColor("#EFF6FF")
LINE = colors.HexColor("#CBD5E1")


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, 15 * mm, 192 * mm, 15 * mm)
    canvas.setFont(BODY_FONT, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10 * mm, "Agent Factory - повний посібник оператора")
    canvas.drawRightString(192 * mm, 10 * mm, f"Сторінка {doc.page}")
    canvas.restoreState()


styles = getSampleStyleSheet()
styles.add(ParagraphStyle(
    name="GuideTitle", fontName=BOLD_FONT, fontSize=26, leading=31,
    textColor=NAVY, alignment=TA_CENTER, spaceAfter=10,
))
styles.add(ParagraphStyle(
    name="GuideSub", fontName=BODY_FONT, fontSize=11, leading=16,
    textColor=MUTED, alignment=TA_CENTER, spaceAfter=16,
))
styles.add(ParagraphStyle(
    name="GuideH1", fontName=BOLD_FONT, fontSize=16, leading=20,
    textColor=NAVY, spaceBefore=10, spaceAfter=7, keepWithNext=True,
))
styles.add(ParagraphStyle(
    name="GuideH2", fontName=BOLD_FONT, fontSize=12, leading=16,
    textColor=CYAN, spaceBefore=8, spaceAfter=5, keepWithNext=True,
))
styles.add(ParagraphStyle(
    name="GuideBody", fontName=BODY_FONT, fontSize=9.2, leading=13.2,
    textColor=INK, spaceAfter=5,
))
styles.add(ParagraphStyle(
    name="GuideBullet", parent=styles["GuideBody"], leftIndent=12,
    firstLineIndent=-7, bulletIndent=2, spaceAfter=3,
))
styles.add(ParagraphStyle(
    name="GuideSmall", fontName=BODY_FONT, fontSize=7.7, leading=10.5,
    textColor=MUTED,
))
styles.add(ParagraphStyle(
    name="GuideCaption", fontName=BODY_FONT, fontSize=8, leading=11,
    textColor=MUTED, alignment=TA_CENTER, spaceBefore=3, spaceAfter=9,
))
styles.add(ParagraphStyle(
    name="GuideCode", fontName=CODE_FONT, fontSize=6.7, leading=8.6,
    textColor=colors.HexColor("#DCE7F7"),
    spaceBefore=4, spaceAfter=8,
))


def inline_markup(value: str) -> str:
    safe = html.escape(value, quote=False)
    safe = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', safe)
    safe = re.sub(r"\*\*([^*]+)\*\*", rf'<font name="{BOLD_FONT}">\1</font>', safe)
    return safe


def paragraph(value: str, style: str = "GuideBody") -> Paragraph:
    return Paragraph(inline_markup(value), styles[style])


def markdown_table(lines: list[str]) -> Table:
    rows: list[list[Paragraph]] = []
    for index, line in enumerate(lines):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if index == 1 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        style = "GuideSmall" if index else "GuideBody"
        rows.append([paragraph(cell, style) for cell in cells])
    count = max(len(row) for row in rows)
    if count == 3:
        widths = [47 * mm, 27 * mm, 100 * mm]
    elif count == 2:
        widths = [50 * mm, 124 * mm]
    else:
        widths = [174 * mm / count] * count
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), BOLD_FONT),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def image_block(alt: str, relative: str) -> list:
    path = (SOURCE.parent / relative).resolve()
    if not path.exists():
        return [paragraph(f"[Зображення недоступне: {relative}]", "GuideSmall")]
    width, height = ImageReader(str(path)).getSize()
    max_width, max_height = 174 * mm, 103 * mm
    scale = min(max_width / width, max_height / height)
    figure = Image(str(path), width=width * scale, height=height * scale)
    figure.hAlign = "CENTER"
    return [KeepTogether([figure, paragraph(alt, "GuideCaption")])]


def code_block(lines: list[str]) -> Table:
    content = Preformatted("\n".join(lines), styles["GuideCode"])
    block = Table([[content]], colWidths=[174 * mm], hAlign="LEFT")
    block.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("BOX", (0, 0), (-1, -1), 0.5, NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return block


def build_story() -> list:
    text = SOURCE.read_text(encoding="utf-8")
    lines = text.splitlines()
    headings = [line[3:] for line in lines if line.startswith("## ")]
    story: list = [
        Spacer(1, 28 * mm),
        paragraph("AGENT FACTORY", "GuideTitle"),
        paragraph("Повний посібник оператора", "GuideTitle"),
        paragraph(
            "Запуск, конфігурація, нові проєкти, людська й агентна верифікація, "
            "Temporal recovery, артефакти та всі вебінтерфейси",
            "GuideSub",
        ),
        Spacer(1, 5 * mm),
        Table(
            [
                [paragraph("Актуальність", "GuideSmall"), paragraph("18 серпня 2026", "GuideSmall")],
                [paragraph("Основна платформа", "GuideSmall"), paragraph("Windows + PowerShell + Docker Desktop", "GuideSmall")],
                [paragraph("Безпечна межа", "GuideSmall"), paragraph("Агенти не можуть final approve, merge, push або release", "GuideSmall")],
            ],
            colWidths=[48 * mm, 116 * mm],
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), PALE),
                ("BOX", (0, 0), (-1, -1), 0.7, BLUE),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]),
        ),
        PageBreak(),
        paragraph("Зміст", "GuideH1"),
    ]
    toc_cells = [[paragraph(item, "GuideBody") for item in headings[i:i + 2]] for i in range(0, len(headings), 2)]
    story.append(Table(toc_cells, colWidths=[87 * mm, 87 * mm], style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
    ])))
    story.append(PageBreak())

    index = 1  # skip source H1
    in_code = False
    code_lines: list[str] = []
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            if in_code:
                wrapped: list[str] = []
                for code_line in code_lines:
                    wrapped.extend(textwrap.wrap(code_line, width=92, subsequent_indent="  ", replace_whitespace=False, drop_whitespace=False) or [""])
                story.extend([code_block(wrapped), Spacer(1, 5)])
                code_lines = []
            in_code = not in_code
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if line.startswith("| "):
            table_lines = []
            while index < len(lines) and lines[index].startswith("|"):
                table_lines.append(lines[index])
                index += 1
            story.extend([markdown_table(table_lines), Spacer(1, 5)])
            continue
        image_match = re.fullmatch(r"!\[([^]]+)]\(([^)]+)\)", line.strip())
        if image_match:
            story.extend(image_block(image_match.group(1), image_match.group(2)))
        elif line.startswith("## "):
            story.append(paragraph(line[3:], "GuideH1"))
        elif line.startswith("### "):
            story.append(paragraph(line[4:], "GuideH2"))
        elif re.match(r"^\d+\. ", line):
            story.append(paragraph(line, "GuideBullet"))
        elif line.startswith("- "):
            story.append(Paragraph(inline_markup(line[2:]), styles["GuideBullet"], bulletText="•"))
        elif line.strip():
            story.append(paragraph(line))
        else:
            story.append(Spacer(1, 2))
        index += 1
    return story


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    document = BaseDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=19 * mm,
        title="Agent Factory - повний посібник оператора",
        author="Agent Factory",
        subject="Durable local agent orchestration with Temporal",
    )
    frame = Frame(document.leftMargin, document.bottomMargin, document.width, document.height, id="main")
    document.addPageTemplates([PageTemplate(id="guide", frames=frame, onPage=footer)])
    document.build(build_story())
    print(OUT)


if __name__ == "__main__":
    build()
