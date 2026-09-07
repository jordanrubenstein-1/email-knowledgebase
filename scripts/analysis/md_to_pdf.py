"""
Convert a markdown report to a styled PDF using reportlab.
Usage: uv run --with reportlab --with markdown python scripts/analysis/md_to_pdf.py <input.md> <output.pdf>
"""
import sys
import re
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

# ── Brand palette ────────────────────────────────────────────────────────────
NAVY      = HexColor("#1B2A3B")
TEAL      = HexColor("#2A7F7F")
TEAL_LIGHT= HexColor("#EAF4F4")
GRAY_RULE = HexColor("#D0D8DF")
GRAY_TEXT = HexColor("#4A5568")
STRIPE    = HexColor("#F7FAFB")
WHITE     = white

# ── Styles ───────────────────────────────────────────────────────────────────
BASE = getSampleStyleSheet()

def make_styles():
    return {
        "title": ParagraphStyle(
            "RPT_Title", fontName="Helvetica-Bold", fontSize=22,
            textColor=NAVY, spaceAfter=4, leading=28),
        "subtitle": ParagraphStyle(
            "RPT_Subtitle", fontName="Helvetica", fontSize=10,
            textColor=GRAY_TEXT, spaceAfter=2, leading=14),
        "meta": ParagraphStyle(
            "RPT_Meta", fontName="Helvetica-Oblique", fontSize=9,
            textColor=GRAY_TEXT, spaceAfter=14, leading=12),
        "h1": ParagraphStyle(
            "RPT_H1", fontName="Helvetica-Bold", fontSize=14,
            textColor=NAVY, spaceBefore=18, spaceAfter=6, leading=18,
            borderPad=0),
        "h2": ParagraphStyle(
            "RPT_H2", fontName="Helvetica-Bold", fontSize=11,
            textColor=TEAL, spaceBefore=12, spaceAfter=4, leading=14),
        "h3": ParagraphStyle(
            "RPT_H3", fontName="Helvetica-BoldOblique", fontSize=10,
            textColor=NAVY, spaceBefore=8, spaceAfter=3, leading=13),
        "body": ParagraphStyle(
            "RPT_Body", fontName="Helvetica", fontSize=9.5,
            textColor=black, spaceAfter=6, leading=14),
        "bullet": ParagraphStyle(
            "RPT_Bullet", fontName="Helvetica", fontSize=9.5,
            textColor=black, spaceAfter=3, leading=13,
            leftIndent=14, bulletIndent=0),
        "note": ParagraphStyle(
            "RPT_Note", fontName="Helvetica-Oblique", fontSize=8.5,
            textColor=GRAY_TEXT, spaceAfter=6, leading=12),
        "tldr": ParagraphStyle(
            "RPT_TLDR", fontName="Helvetica", fontSize=9.5,
            textColor=NAVY, spaceAfter=0, leading=14,
            leftIndent=12, rightIndent=12),
    }

# ── Markdown inline → ReportLab XML ─────────────────────────────────────────
def md_inline(text):
    """Convert inline markdown (**bold**, *italic*, `code`) to RL tags."""
    # Escape XML special chars first (except ones we'll reintroduce)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Bold+italic
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Italic
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    # Inline code
    text = re.sub(r'`([^`]+)`', r'<font name="Courier" size="8.5">\1</font>', text)
    return text

# ── Table parser ─────────────────────────────────────────────────────────────
def parse_md_table(lines):
    """Parse a markdown table block into a list of row lists."""
    rows = []
    for line in lines:
        if re.match(r'\s*\|[-:| ]+\|\s*$', line):
            continue  # separator row
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        rows.append(cells)
    return rows

def build_rl_table(rows, styles):
    if not rows:
        return None
    col_count = max(len(r) for r in rows)
    # Pad rows
    padded = [r + [''] * (col_count - len(r)) for r in rows]

    # Convert cell text
    header = [Paragraph(f"<b>{md_inline(c)}</b>", styles["body"]) for c in padded[0]]
    data = [header]
    for row in padded[1:]:
        data.append([Paragraph(md_inline(c), styles["body"]) for c in row])

    # Column widths: distribute evenly within text area
    available = 6.5 * inch
    col_w = available / col_count

    ts = TableStyle([
        ('BACKGROUND',   (0, 0), (-1, 0),  NAVY),
        ('TEXTCOLOR',    (0, 0), (-1, 0),  WHITE),
        ('FONTNAME',     (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, STRIPE]),
        ('GRID',         (0, 0), (-1, -1), 0.4, GRAY_RULE),
        ('VALIGN',       (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING',   (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 5),
        ('LEFTPADDING',  (0, 0), (-1, -1), 7),
        ('RIGHTPADDING', (0, 0), (-1, -1), 7),
    ])
    return Table(data, colWidths=[col_w] * col_count, style=ts, hAlign='LEFT',
                 repeatRows=1)

# ── Main parser ───────────────────────────────────────────────────────────────
def md_to_story(md_text, styles):
    story = []
    lines = md_text.splitlines()
    i = 0
    in_table = False
    table_lines = []

    def flush_table():
        nonlocal table_lines, in_table
        if table_lines:
            rows = parse_md_table(table_lines)
            tbl = build_rl_table(rows, styles)
            if tbl:
                story.append(Spacer(1, 4))
                story.append(tbl)
                story.append(Spacer(1, 6))
        table_lines = []
        in_table = False

    while i < len(lines):
        line = lines[i]

        # --- Table detection ---
        if '|' in line and re.search(r'\|', line):
            # Check if next line is separator
            next_line = lines[i+1] if i+1 < len(lines) else ''
            if re.match(r'\s*\|[-:| ]+\|\s*$', next_line) or in_table:
                in_table = True
                table_lines.append(line)
                i += 1
                continue
        if in_table:
            flush_table()

        # --- Blank line ---
        if not line.strip():
            i += 1
            continue

        # --- Horizontal rule ---
        if re.match(r'^---+\s*$', line):
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="100%", thickness=1, color=GRAY_RULE))
            story.append(Spacer(1, 6))
            i += 1
            continue

        # --- H1 (# ) ---
        m = re.match(r'^# (.+)', line)
        if m:
            text = m.group(1)
            # First H1 = report title
            if not story:
                story.append(Paragraph(md_inline(text), styles["title"]))
            else:
                story.append(Paragraph(md_inline(text), styles["h1"]))
                story.append(HRFlowable(width="100%", thickness=1.5, color=TEAL, spaceAfter=4))
            i += 1
            continue

        # --- H2 (## ) ---
        m = re.match(r'^## (.+)', line)
        if m:
            story.append(Paragraph(md_inline(m.group(1)), styles["h2"]))
            i += 1
            continue

        # --- H3 (### ) ---
        m = re.match(r'^### (.+)', line)
        if m:
            story.append(Paragraph(md_inline(m.group(1)), styles["h3"]))
            i += 1
            continue

        # --- Italic-only line (metadata / subtitle under title) ---
        m = re.match(r'^\*(.+)\*$', line)
        if m:
            story.append(Paragraph(m.group(1), styles["meta"]))
            i += 1
            continue

        # --- Bold-only line (sub-label) ---
        m = re.match(r'^\*\*(.+)\*\*$', line)
        if m:
            story.append(Paragraph(f"<b>{md_inline(m.group(1))}</b>", styles["subtitle"]))
            i += 1
            continue

        # --- Bullet (- or * at start) ---
        m = re.match(r'^[-*] (.+)', line)
        if m:
            story.append(Paragraph(f"• {md_inline(m.group(1))}", styles["bullet"]))
            i += 1
            continue

        # --- Note / italic paragraph (lines starting with *Note) ---
        if line.startswith('*Note') or line.startswith('_Note') or line.startswith('*Data sources'):
            story.append(Paragraph(md_inline(line.strip('*_ ')), styles["note"]))
            i += 1
            continue

        # --- Regular paragraph ---
        story.append(Paragraph(md_inline(line), styles["body"]))
        i += 1

    if in_table:
        flush_table()

    return story


def add_header_footer(canvas, doc):
    canvas.saveState()
    w, h = letter
    # Header bar
    canvas.setFillColor(NAVY)
    canvas.rect(0, h - 36, w, 36, fill=1, stroke=0)
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(0.5 * inch, h - 22, "Interior Define — Trade Email Performance Report")
    canvas.setFont("Helvetica", 9)
    canvas.drawRightString(w - 0.5 * inch, h - 22, "Confidential · May 2026")
    # Footer
    canvas.setFillColor(GRAY_RULE)
    canvas.rect(0, 0, w, 28, fill=1, stroke=0)
    canvas.setFillColor(GRAY_TEXT)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(0.5 * inch, 10, "Havenly Brands · Email CRM")
    canvas.drawRightString(w - 0.5 * inch, 10, f"Page {doc.page}")
    canvas.restoreState()


def convert(input_md, output_pdf):
    with open(input_md, encoding="utf-8") as f:
        md_text = f.read()

    styles = make_styles()
    story = md_to_story(md_text, styles)

    doc = SimpleDocTemplate(
        output_pdf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.55 * inch,
    )
    doc.build(story, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
    print(f"✓ PDF written to {output_pdf}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python md_to_pdf.py <input.md> <output.pdf>")
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
