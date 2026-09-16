# -*- coding: utf-8 -*-
"""
Generate HAV DPS Memorial Day YoY PDF report (2025 vs 2026).
Output: reports/hav-dps-memorial-day-yoy-2025-2026.pdf
All source chars are ASCII; unicode output via ReportLab HTML entities.
"""

import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak,
)

NAVY       = colors.HexColor("#1A2B4A")
TEAL       = colors.HexColor("#2E7D89")
GOLD       = colors.HexColor("#C8963E")
LIGHT_BG   = colors.HexColor("#F4F6F9")
MID_GRAY   = colors.HexColor("#8E9BAD")
RULE_COLOR = colors.HexColor("#D0D8E4")
WHITE      = colors.white
RED_SOFT   = colors.HexColor("#C0392B")
GREEN_SOFT = colors.HexColor("#27AE60")
GOLD_BG    = colors.HexColor("#FDF3E3")
TEAL_BG    = colors.HexColor("#EAF4F6")

def S(name, **kw):
    return ParagraphStyle(name, **kw)

TITLE    = S("RPT_Title",  fontName="Helvetica-Bold",   fontSize=22, textColor=NAVY,     spaceAfter=4,  leading=26)
SUBTITLE = S("RPT_Sub",    fontName="Helvetica",         fontSize=11, textColor=MID_GRAY, spaceAfter=16, leading=14)
H1       = S("RPT_H1",     fontName="Helvetica-Bold",   fontSize=13, textColor=NAVY,     spaceBefore=18, spaceAfter=6, leading=16)
BODY     = S("RPT_Body",   fontName="Helvetica",         fontSize=9,  textColor=colors.HexColor("#2C3E50"), leading=13, spaceAfter=6)
SMALL    = S("RPT_Small",  fontName="Helvetica",         fontSize=8,  textColor=MID_GRAY, leading=11)
ANNOT    = S("RPT_Annot",  fontName="Helvetica-Oblique", fontSize=8,  textColor=MID_GRAY, leading=11, spaceAfter=4)
NOTE     = S("RPT_Note",   fontName="Helvetica-Oblique", fontSize=7.5,textColor=MID_GRAY, leading=10, spaceAfter=8)
TH       = S("RPT_TH",     fontName="Helvetica-Bold",   fontSize=8,  textColor=WHITE,    alignment=TA_CENTER, leading=10)
TD       = S("RPT_TD",     fontName="Helvetica",         fontSize=8,  textColor=colors.HexColor("#2C3E50"), leading=10)
TD_C     = S("RPT_TD_C",   fontName="Helvetica",         fontSize=8,  textColor=colors.HexColor("#2C3E50"), alignment=TA_CENTER, leading=10)

def rule(color=RULE_COLOR, thickness=0.5):
    return HRFlowable(width="100%", thickness=thickness, color=color, spaceAfter=6, spaceBefore=4)

def section_header(text):
    return [rule(TEAL, 1.2), Paragraph(text, H1)]

def p(text, style=BODY):
    return Paragraph(text, style)

def sp(n=6):
    return Spacer(1, n)

def make_table(data, col_widths, extra_styles=None):
    base = [
        ("BACKGROUND",     (0, 0), (-1, 0),  NAVY),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  WHITE),
        ("FONTNAME",       (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BG]),
        ("GRID",           (0, 0), (-1, -1), 0.25, RULE_COLOR),
        ("LINEBELOW",      (0, 0), (-1, 0),  1,    TEAL),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
        ("LEFTPADDING",    (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 5),
    ]
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle(base + (extra_styles or [])))
    return t

def kpi_row(items):
    cells = []
    for label, v25, v26, delta, direction in items:
        if direction == "+":
            arrow, dclr = "^", "#27AE60"
        elif direction == "-":
            arrow, dclr = "v", "#C0392B"
        else:
            arrow, dclr = "~", "#8E9BAD"
        inner = [
            [Paragraph(label, S("_kl%s"%label[:4], fontName="Helvetica", fontSize=7.5, textColor=MID_GRAY, alignment=TA_CENTER, leading=10))],
            [Paragraph("<b>%s</b>" % v25, S("_kv%s"%v25, fontName="Helvetica-Bold", fontSize=10, textColor=colors.HexColor("#2C3E50"), alignment=TA_CENTER))],
            [Paragraph("<font color='#2E7D89'>%s</font>" % v26, S("_kv2%s"%v26, fontName="Helvetica-Bold", fontSize=10, alignment=TA_CENTER))],
            [Paragraph("<font color='%s'>%s %s</font>" % (dclr, arrow, delta), S("_kd%s"%delta, fontName="Helvetica-Bold", fontSize=8, alignment=TA_CENTER, leading=10))],
        ]
        box = Table(inner, colWidths=[1.3 * inch])
        box.setStyle(TableStyle([
            ("BOX",           (0,0),(-1,-1), 0.5, RULE_COLOR),
            ("BACKGROUND",    (0,0),(-1,-1), WHITE),
            ("TOPPADDING",    (0,0),(-1,-1), 4),
            ("BOTTOMPADDING", (0,0),(-1,-1), 4),
            ("LEFTPADDING",   (0,0),(-1,-1), 4),
            ("RIGHTPADDING",  (0,0),(-1,-1), 4),
        ]))
        cells.append(box)
    legend = Table([[
        Paragraph("2025", S("_lg", fontName="Helvetica-Bold", fontSize=7.5, textColor=colors.HexColor("#2C3E50"), alignment=TA_CENTER)),
        Paragraph("2026", S("_lg2", fontName="Helvetica-Bold", fontSize=7.5, textColor=TEAL, alignment=TA_CENTER)),
        Paragraph("YoY",  S("_lg3", fontName="Helvetica-Bold", fontSize=7.5, textColor=MID_GRAY, alignment=TA_CENTER)),
    ]], colWidths=[0.42 * inch] * 3)
    legend.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]))
    row = Table([cells + [legend]], colWidths=[1.4 * inch] * len(items) + [1.4 * inch])
    row.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),2),("RIGHTPADDING",(0,0),(-1,-1),2)]))
    return row


def build():
    out_path = "/Users/mina.cohen/AI Email/email-knowledgebase/reports/hav-dps-memorial-day-yoy-2025-2026.pdf"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc = SimpleDocTemplate(out_path, pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.75*inch,  bottomMargin=0.75*inch,
        title="HAV DPS Memorial Day Email - YoY Deep Dive", author="Email Analytics")
    W = letter[0] - 1.5 * inch
    story = []

    # Title
    story += [
        sp(4),
        p("HAV DPS Email", S("_ck", fontName="Helvetica", fontSize=10, textColor=TEAL, leading=14)),
        p("Memorial Day &mdash; Year-over-Year Deep Dive", TITLE),
        p("Memorial Day 2025 (Mon May 26)  &middot;  Memorial Day 2026 (Mon May 25)  &middot;  Day-of-week aligned comparison", SUBTITLE),
        rule(TEAL, 1.5),
        sp(4),
        p("AT A GLANCE", S("_ag", fontName="Helvetica-Bold", fontSize=8, textColor=MID_GRAY, leading=12, spaceAfter=4)),
    ]
    story.append(kpi_row([
        ("Full-list\nSend Size",       "~219K", "~284K",  "+31%",   "+"),
        ("Avg Open Rate\n(MD window)",  "~43%",  "~34%",   "-9 pts", "-"),
        ("Avg Click Rate\n(MD window)", "0.40%", "0.24%",  "-40%",   "-"),
        ("Campaigns\n(~3-wk window)",  "25",    "14+*",   "varies", "~"),
    ]))
    story.append(p("* 2026 window not yet closed; 3-4 extension sends queued. All figures for campaigns with analytics available.", NOTE))
    story.append(sp(8))

    # 1. List size
    story += section_header("1 &middot; List Size &amp; Send Volume")
    story.append(sp(2))
    vol_data = [
        [p("Metric",TH),p("2025",TH),p("2026",TH),p("Notes",TH)],
        [p("Full PC list size",TD),p("~213K-220K",TD_C),p("~283K-285K",TD_C),p("List grew ~31% YoY",TD)],
        [p("Segmented sub-sends",TD),p("None - all sends full list",TD_C),p("~68-70K segment for some MD reminders",TD_C),p("New in 2026; ~1/4 of full list",TD)],
        [p("Campaigns in ~3-wk window",TD),p("25",TD_C),p("14 (+ 3-4 queued)",TD_C),p("2025 window ran through May 31",TD)],
        [p("Double-send days",TD),p("May 25 + May 26 - 2 emails each",TD_C),p("May 26 is the final-day send",TD_C),p("2025 used AM/PM splits on key days",TD)],
    ]
    story.append(make_table(vol_data, col_widths=[1.7*inch,1.6*inch,2.0*inch,1.85*inch], extra_styles=[("ALIGN",(1,1),(2,-1),"CENTER")]))
    story.append(sp(4))
    story.append(p("The PC audience grew by roughly 31% year over year, which is important context when comparing raw open rates. "
        "Actual unique opens per campaign are <b>broadly stable</b> &mdash; 219K x 42% &asymp; 92K opens in 2025 "
        "vs 284K x 34% &asymp; 97K opens in 2026.", BODY))

    # 2. Day-of-week table
    story += section_header("2 &middot; Day-of-Week Aligned Comparison")
    story.append(p("Memorial Day = Monday. Dates are aligned by day of week, not calendar date.", ANNOT))

    def drow(dow, d25, sl25, or25, d26, sl26, or26, highlight=None):
        if highlight == "md":
            ds = S("_dmd", fontName="Helvetica-Bold", fontSize=8, textColor=GOLD, alignment=TA_CENTER, leading=10)
        elif highlight == "wk":
            ds = S("_dwk", fontName="Helvetica-Bold", fontSize=8, textColor=TEAL, alignment=TA_CENTER, leading=10)
        else:
            ds = TD_C
        return [p(dow,ds), p(d25,TD_C), p(sl25,TD), p(or25,TD_C), p(d26,TD_C), p(sl26,TD), p(or26,TD_C)]

    dow_data = [
        [p("DOW",TH),p("2025 Date",TH),p("2025 Campaign / Subject",TH),p("OR",TH),
         p("2026 Date",TH),p("2026 Campaign / Subject",TH),p("OR",TH)],
        drow("Mon -2wk","5/12","PT Reminder: 'Start your week off with savings'","44.3%","5/11","&mdash;","&mdash;"),
        drow("Tue","5/13","&mdash;","&mdash;","5/12","Reminder: 'A better room is only $99 away'","35.6%"),
        drow("Wed","5/14","Designed Reminder (corrected resend) + Editorial: '9 kitchen reno regrets'","94.8%* / 41.2%","5/13","&mdash;","&mdash;"),
        drow("Thu","5/15","Editorial resend: '9 kitchen reno regrets'","43.8%","5/14","AI feature: 'AI design, backed by real designers'","35.3%"),
        drow("Fri","5/16","PT Reminder: 'Kick off your weekend with savings'","43.8%","5/15","68K seg: 'Big design plans, smaller price tag'","38.1%"),
        drow("Sat","5/17","Editorial: '23 kid + pet-friendly sofas'  &middot;  SEG HIP reminder","43.0% / 54.7%*","5/16","Full list: 'Nursery goals'","35.5%"),
        drow("Sun","5/18","Editorial: 'Living Rooms We Love'","43.1%","5/17","Full list: 'Your room called - it wants a designer'","36.6%"),
        drow("Mon -1wk","5/19","Designed Reminder: 'Design magic for less than a night out'","42.5%","5/18","Designer feature: 'This is what good design looks like'","34.9%",highlight="wk"),
        drow("Tue","5/20","PT Reminder: 'Design packages are HALF OFF'","44.1%","5/19","68K seg: 'A designer-approved summer refresh'","38.3%"),
        drow("Wed","5/21","Editorial: 'This 1970s design trend is BACK'","43.4%","5/20","AI feature: 'One room, three totally different looks'","&mdash;"),
        drow("Thu","5/22","Designed: 'Memorial Day deals have arrived - up to 70% off'","42.2%","5/21","68K seg: 'The countdown to your summer refresh is on'","37.1%"),
        drow("Fri","5/23","Designed Reminder: 'What can $99 get you?'","42.0%","5/22","Full-list PT: '$99 to transform your space'","33.6%"),
        drow("Sat","5/24","Designed: 'Your dream room is just one click away'","42.4%","5/23","Full list: 'The countdown to your summer refresh is on'","32.1%"),
        drow("Sun","5/25","Designed editorial + PM PT: 'Last chance: Save 50% on design packages'","42.7% / 43.8%","5/24","Full list: 'Stop scrolling. Start designing.'","28.5%"),
        drow("[MD] MON","5/26","<b>AM:</b> 'Design Dreams, Final Hours - 50% Off Ends Tomorrow'<br/><b>PM:</b> 'You are THIS CLOSE to Your Dream Home'","42.1% / 42.6%","5/25","68K engaged seg, STO with 11am local fallback &mdash; analytics captured before bulk sends launched+","early+","md"),
        drow("Tue","5/27","Designed + PM PT: 'Do not let the clock run out - 50% off ends tonight'","41.7% / 43.8%","5/26","Final-day designed (sending today - analytics pending)","&mdash;"),
        drow("Wed","5/28","PT Extended: 'Sale extended!'","43.4%","5/27","Extension launch (queued)","&mdash;"),
        drow("Thu","5/29","Designed: 'LAST CHANCE - ends at midnight'","41.9%","5/28","Extension final (queued)","&mdash;"),
        drow("Fri","5/30","Editorial: 'TRENDING: Nancy Meyers Aesthetic'","43.0%","5/29","DPS AI email (queued)","&mdash;"),
        drow("Sat","5/31","Editorial: 'The #1 Pattern Trend Everyone is Trying'","42.8%","&mdash;","&mdash;","&mdash;"),
    ]
    col_w = [0.65*inch, 0.45*inch, 2.15*inch, 0.55*inch, 0.45*inch, 2.15*inch, 0.55*inch]
    md_idx = 15   # 1-based row index of Memorial Day row (header=0, first data=1)
    wk_idx = 8
    story.append(make_table(dow_data, col_widths=col_w, extra_styles=[
        ("BACKGROUND",(0,md_idx),(-1,md_idx), GOLD_BG),
        ("LINEABOVE", (0,md_idx),(-1,md_idx), 1.2, GOLD),
        ("LINEBELOW", (0,md_idx),(-1,md_idx), 1.2, GOLD),
        ("BACKGROUND",(0,wk_idx),(-1,wk_idx), TEAL_BG),
    ]))
    story.append(p("* Corrected resend (94.8%) and geo-segmented HIP send (54.7%) are outliers - not representative of full-list performance.  "
        "+ 5/25/2026 send used STO with 11am local fallback; analytics shown reflect an early data pull before the bulk of sends launched. "
        "Final send count and OR will be materially higher once STO completes.", NOTE))

    # 3. Messaging
    story += section_header("3 &middot; Messaging &amp; Content Mix")
    msg_data = [
        [p("",TH),p("Memorial Day 2025",TH),p("Memorial Day 2026",TH)],
        [p("Sale offer",TD),p("50% off design services / packages from $99",TD),p("Same &mdash; 50% off / from $99",TD)],
        [p("Tone",TD),p("<i>HALF OFF, Last chance, Final Countdown, LAST CHANCE</i> &mdash; high urgency countdown language",TD),
         p("<i>A better room is only $99 away, Big design plans, smaller price tag</i> &mdash; aspirational / benefit-led",TD)],
        [p("Editorial interleaving",TD),
         p("Heavy &mdash; kitchen reno regrets, pet-friendly sofas, 1970s trend, Nancy Meyers, pattern mixing all ran throughout the sale window",TD),
         p("Lighter &mdash; editorial slots replaced with AI product features + one designer profile",TD)],
        [p("Memorial Day send",TD),p("2 emails: AM (sale final hours) + PM (you are THIS CLOSE)",TD),
         p("Planned final-day email sending today (5/26) &mdash; holiday send appears to have misfired at 1,478 sends",TD)],
        [p("Sale extension",TD),p("Yes &mdash; 3 days post-MD (through May 29)",TD),p("Yes &mdash; planned through May 27-28 (+DPS AI on 5/29)",TD)],
        [p("Segmentation",TD),p("Full list only throughout",TD),p("Mix: full list + ~68K sub-segment for select reminder sends",TD)],
    ]
    story.append(make_table(msg_data, col_widths=[1.3*inch, 2.9*inch, 2.9*inch], extra_styles=[("ALIGN",(0,0),(0,-1),"LEFT")]))

    # 4. OR Trend
    story.append(PageBreak())
    story += section_header("4 &middot; Open Rate Trend &mdash; Program-Wide Context")
    story.append(p("The OR decline in the 2026 Memorial Day window is <b>not a Memorial Day-specific phenomenon</b> &mdash; "
        "it tracks a steady program-wide decline over the past 12 months.", BODY))
    story.append(sp(4))
    trend_data = [
        [p("Period",TH),p("Avg OR (HAV PC email)",TH),p("Context",TH)],
        [p("May-Jun 2025",TD_C),p("~43-44%",TD_C),p("Peak engagement period",TD)],
        [p("Jul-Sep 2025",TD_C),p("~43%",TD_C),p("Stable summer",TD)],
        [p("Oct-Dec 2025",TD_C),p("~40-42%",TD_C),p("Gradual decline begins",TD)],
        [p("Jan-Mar 2026",TD_C),p("~36-38%",TD_C),p("Accelerated decline",TD)],
        [p("Apr-May 2026",TD_C),
         p("<font color='#C0392B'><b>~33-36%</b></font>", S("_orl", fontName="Helvetica-Bold", fontSize=8, alignment=TA_CENTER)),
         p("Current &mdash; Memorial Day 2026 window",TD)],
    ]
    story.append(make_table(trend_data, col_widths=[1.6*inch,1.8*inch,3.7*inch],
        extra_styles=[("BACKGROUND",(0,5),(-1,5),colors.HexColor("#FDECEA"))]))
    story.append(sp(6))
    story.append(p("<b>Unique opens per campaign are largely holding:</b> the list's 31% growth partially offsets "
        "the rate decline. A 219K-send campaign at 42% OR produces ~92K opens; a 284K-send campaign at 34% OR "
        "produces ~97K opens &mdash; a net <i>increase</i> in absolute opens.", BODY))

    # 5. Click rate
    story += section_header("5 &middot; Click Rate Comparison")
    story.append(p("Unlike open rates, click rates show a <b>real, not just proportional, decline</b> &mdash; "
        "the difference is largely driven by content mix.", BODY))
    story.append(sp(4))
    cr_data = [
        [p("Category",TH),p("2025 MD window Avg CR",TH),p("2026 MD window Avg CR",TH),p("n (2025 / 2026)",TH)],
        [p("Editorial",TD_C),p("0.577%",TD_C),p("0.200%",TD_C),p("6 / 1",TD_C)],
        [p("Reminder",TD_C),p("0.355%",TD_C),p("0.279%",TD_C),p("12 / 7",TD_C)],
        [p("Other",TD_C),p("0.438%",TD_C),p("0.153%",TD_C),p("4 / 3",TD_C)],
        [p("Sale Promo",TD_C),p("0.153%",TD_C),p("0.260%",TD_C),p("3 / 1",TD_C)],
        [p("<b>Window avg</b>",TD_C),
         p("<b>0.397%</b>",S("_crb", fontName="Helvetica-Bold",fontSize=8,alignment=TA_CENTER)),
         p("<font color='#C0392B'><b>0.239%</b></font>",S("_crb2",fontName="Helvetica-Bold",fontSize=8,alignment=TA_CENTER)),
         p("25 / 12",TD_C)],
    ]
    story.append(make_table(cr_data, col_widths=[1.6*inch,1.8*inch,1.8*inch,1.95*inch],
        extra_styles=[("BACKGROUND",(0,5),(-1,5),LIGHT_BG),("FONTNAME",(0,5),(-1,5),"Helvetica-Bold")]))
    story.append(sp(4))
    story.append(p("The largest contributor to the CR gap is <b>editorial content interleaving</b>. In 2025, "
        "editorial emails (kitchen reno, pet-friendly sofas, trend round-ups) ran throughout the sale window, "
        "averaging 0.58% CR. In 2026 those slots were replaced with AI product feature emails running at "
        "0.12-0.17% CR. Sale promo CR is actually <i>higher</i> in 2026 (0.26% vs 0.15%).", BODY))

    # 6. Cadence
    story += section_header("6 &middot; Cadence &amp; Timing Summary")
    cad_data = [
        [p("",TH),p("2025",TH),p("2026",TH)],
        [p("Sale start",TD),p("~May 12",TD),p("~May 9-12",TD)],
        [p("Memorial Day sends",TD),p("2 emails (AM + PM, full list)",TD),
         p("5/25: 68K engaged seg via STO (11am local fallback) &mdash; analytics captured early, pre-bulk. "
           "5/26: full-list final-day send (analytics pending)",TD)],
        [p("Sale extension",TD),p("3 days post-MD (through May 29)",TD),p("Planned May 27-28 (+DPS AI May 29)",TD)],
        [p("Post-MD editorial",TD),p("Resumed May 30-31",TD),p("DPS AI email planned May 29",TD)],
        [p("Total campaigns (~3 wks)",TD),p("~25 campaigns",TD),p("~14 sent + 3-4 queued",TD)],
        [p("Segmentation",TD),p("Full list only",TD),p("Full list + ~68K sub-segment for some reminders",TD)],
    ]
    story.append(make_table(cad_data, col_widths=[1.7*inch,2.45*inch,2.95*inch]))

    # 7. Key takeaways
    story += section_header("7 &middot; Key Takeaways")
    story.append(sp(2))
    takeaways = [
        ("<b>List grew 31%</b> &mdash; the PC audience is meaningfully larger, which cushions the OR "
         "decline in absolute open terms.", "+"),
        ("<b>OR is down ~9 points</b> &mdash; this is a program-wide trend predating Memorial Day, not "
         "a campaign-specific issue. It began in earnest in Oct-Nov 2025 and has continued through Q1/Q2 2026.", "-"),
        ("<b>CR is genuinely softer</b> &mdash; editorial content drove high clicks in 2025 (0.5-0.9% "
         "for trend/guide emails). Replacing editorial slots with AI product features in 2026 is the "
         "primary driver of the CR gap.", "-"),
        ("<b>Sale cadence is structurally similar</b> &mdash; both years featured a ~3-week sale window, "
         "daily sends, and a post-Memorial Day extension.", "+"),
        ("<b>Tone shifted from urgency to aspiration</b> &mdash; 2025 leaned on countdown language "
         "(HALF OFF, Final Countdown); 2026 is more benefit-focused ($99 to transform your space, "
         "Big design plans, smaller price tag).", "~"),
        ("<b>New in 2026: segmented reminder sends</b> &mdash; three Memorial Day reminder emails went "
         "to ~68K rather than the full ~284K. These ran at higher ORs (37-38% vs 33-35% for full list), "
         "suggesting better list targeting but lower reach.", "~"),
        ("<b>2026 Memorial Day Day-of send used STO, not a fixed time</b> &mdash; the 5/25 send went to "
         "the ~68K engaged segment with Send Time Optimization (11am local fallback). Analytics at time "
         "of reporting reflect an early data pull before the bulk of sends launched; final figures will "
         "be materially higher. The full-list final-day email sent on 5/26.", "~"),
    ]
    for text, direction in takeaways:
        dclr = "#27AE60" if direction=="+" else ("#C0392B" if direction=="-" else "#2E7D89")
        dot_cell = Paragraph("<font color='%s'>&#x25CF;</font>" % dclr,
            S("_dot"+direction+text[:6], fontName="Helvetica-Bold", fontSize=10, textColor=TEAL, leading=13))
        bullet_row = Table([[dot_cell, Paragraph(text, BODY)]], colWidths=[0.2*inch, W-0.2*inch])
        bullet_row.setStyle(TableStyle([
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("TOPPADDING",(0,0),(-1,-1),1),
            ("BOTTOMPADDING",(0,0),(-1,-1),3),
            ("LEFTPADDING",(0,0),(-1,-1),0),
            ("RIGHTPADDING",(0,0),(-1,-1),0),
        ]))
        story.append(bullet_row)

    story.append(sp(8))
    story.append(rule(RULE_COLOR))
    story.append(p("Report generated May 26, 2026  &middot;  "
        "Source: email-knowledgebase YAML archive (~9,200 campaigns)  &middot;  "
        "HAV DPS = Pre-Converted audience (PC campaigns)", SMALL))

    doc.build(story)
    print("Saved: %s" % out_path)

if __name__ == "__main__":
    build()
