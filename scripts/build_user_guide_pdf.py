from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Preformatted, PageBreak, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pdf" / "agent-factory-user-guide-uk.pdf"
font = Path(r"C:\Windows\Fonts\Arial.ttf")
if font.exists():
    pdfmetrics.registerFont(TTFont("Arial", str(font)))
    FONT = "Arial"
else:
    FONT = "Helvetica"

def footer(canvas, doc):
    canvas.saveState(); canvas.setFont(FONT, 8); canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(18*mm, 12*mm, "Agent Factory · Інструкція користувача · 0.1.0")
    canvas.drawRightString(192*mm, 12*mm, f"Сторінка {doc.page}"); canvas.restoreState()

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="UGTitle", parent=styles["Title"], fontName=FONT, fontSize=24, leading=30, textColor=colors.HexColor("#102A43"), alignment=TA_CENTER, spaceAfter=14))
styles.add(ParagraphStyle(name="UGSub", parent=styles["Normal"], fontName=FONT, fontSize=11, leading=16, textColor=colors.HexColor("#486581"), alignment=TA_CENTER, spaceAfter=20))
styles.add(ParagraphStyle(name="UGH1", parent=styles["Heading1"], fontName=FONT, fontSize=16, leading=21, textColor=colors.HexColor("#102A43"), spaceBefore=10, spaceAfter=8))
styles.add(ParagraphStyle(name="UGH2", parent=styles["Heading2"], fontName=FONT, fontSize=12, leading=16, textColor=colors.HexColor("#0B7285"), spaceBefore=8, spaceAfter=5))
styles.add(ParagraphStyle(name="UGBody", parent=styles["BodyText"], fontName=FONT, fontSize=9.5, leading=14, spaceAfter=6, textColor=colors.HexColor("#243B53")))
styles.add(ParagraphStyle(name="UGSmall", parent=styles["BodyText"], fontName=FONT, fontSize=8, leading=11, textColor=colors.HexColor("#486581")))
styles.add(ParagraphStyle(name="UGCode", parent=styles["Code"], fontName=FONT, fontSize=7.4, leading=9.5, backColor=colors.HexColor("#F1F5F9"), borderColor=colors.HexColor("#CBD5E1"), borderWidth=.4, borderPadding=6, spaceBefore=4, spaceAfter=8))

def para(text, style="UGBody"):
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe, styles[style])

def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(OUT), pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=16*mm, bottomMargin=20*mm, title="Agent Factory - Інструкція користувача", author="Agent Factory")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="main", frames=frame, onPage=footer)])
    story = [Spacer(1, 25*mm), para("Agent Factory", "UGTitle"), para("Інструкція користувача", "UGTitle"), para("Від першого запуску до безпечної роботи з агентами, веб-інтерфейсом, approvals і recovery", "UGSub"), Spacer(1, 8*mm)]
    story.append(Table([[para("Версія", "UGSmall"), para("0.1.0", "UGSmall")], [para("Дата", "UGSmall"), para("12 серпня 2026", "UGSmall")], [para("Режим за замовчуванням", "UGSmall"), para("offline / simulation-safe", "UGSmall")]], colWidths=[55*mm, 110*mm], style=TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#E6FFFA")), ("BOX", (0,0), (-1,-1), .6, colors.HexColor("#0B7285")), ("INNERGRID", (0,0), (-1,-1), .3, colors.HexColor("#B2F5EA")), ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("LEFTPADDING", (0,0), (-1,-1), 8)])))
    story += [PageBreak(), para("Зміст", "UGH1")]
    headings = [line[3:] for line in (ROOT / "docs" / "user-guide-uk.md").read_text(encoding="utf-8").splitlines() if line.startswith("## ")]
    story += [para("• " + heading) for heading in headings]
    story.append(PageBreak())
    in_code = False; code = []
    for line in (ROOT / "docs" / "user-guide-uk.md").read_text(encoding="utf-8").splitlines()[5:]:
        if line.startswith("```"):
            if in_code: story.append(Preformatted("\n".join(code), styles["UGCode"])); code = []
            in_code = not in_code; continue
        if in_code: code.append(line); continue
        if not line.strip(): story.append(Spacer(1, 2)); continue
        if line.startswith("### "): story.append(para(line[4:], "UGH2")); continue
        if line.startswith("## "): story.append(para(line[3:], "UGH1")); continue
        if line.startswith("- "): story.append(para("• " + line[2:])); continue
        story.append(para(line))
    doc.build(story); print(OUT)

if __name__ == "__main__": build()
