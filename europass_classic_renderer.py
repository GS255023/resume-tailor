"""Classic two-column Europass renderer.

Full-page layout:
  - EU-blue header band with name + role
  - LEFT sidebar (~33%): personal info, languages with CEFR, digital skills (bulleted),
    certifications
  - RIGHT main column (~67%): about me, work experience, education and training

Designed to fill the A4 page (no wasted whitespace) and stay ATS-extractable —
the BaseDocTemplate stacks left then right per page, so text extraction reads
sidebar content first, then the main column.
"""
from __future__ import annotations

import io
from html import escape

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

EUROPASS_BLUE = HexColor("#003399")
EUROPASS_BLUE_DARK = HexColor("#002266")
EUROPASS_DARK = HexColor("#1A1A1A")
EUROPASS_GREY = HexColor("#4D4D4D")
EUROPASS_LIGHT = HexColor("#E8EEF7")
EUROPASS_SIDEBAR = HexColor("#F1F5FB")


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def _styles():
    base = ParagraphStyle(
        name="base", fontName="Helvetica", fontSize=9.5, leading=12,
        textColor=EUROPASS_DARK, alignment=TA_LEFT,
    )
    return {
        # Header band (white-on-blue)
        "header_name": ParagraphStyle(
            "header_name", parent=base, fontName="Helvetica-Bold", fontSize=22,
            leading=26, textColor=white,
        ),
        "header_title": ParagraphStyle(
            "header_title", parent=base, fontSize=12, leading=14, textColor=white,
        ),
        # Sidebar
        "side_section": ParagraphStyle(
            "side_section", parent=base, fontName="Helvetica-Bold", fontSize=10,
            leading=13, textColor=EUROPASS_BLUE, spaceBefore=10, spaceAfter=4,
            textTransform="uppercase",
        ),
        "side_label": ParagraphStyle(
            "side_label", parent=base, fontName="Helvetica-Bold", fontSize=8.5,
            leading=11, textColor=EUROPASS_BLUE,
        ),
        "side_value": ParagraphStyle(
            "side_value", parent=base, fontSize=9, leading=11.5,
            textColor=EUROPASS_DARK,
        ),
        "side_bullet": ParagraphStyle(
            "side_bullet", parent=base, fontSize=9, leading=11.5,
            leftIndent=8, bulletIndent=0, spaceAfter=1,
        ),
        # Main column
        "main_section": ParagraphStyle(
            "main_section", parent=base, fontName="Helvetica-Bold", fontSize=12,
            leading=15, textColor=EUROPASS_BLUE, spaceBefore=10, spaceAfter=4,
        ),
        "main_date": ParagraphStyle(
            "main_date", parent=base, fontName="Helvetica-Bold", fontSize=9,
            leading=11, textColor=EUROPASS_GREY,
        ),
        "main_role": ParagraphStyle(
            "main_role", parent=base, fontName="Helvetica-Bold", fontSize=10.5,
            leading=13,
        ),
        "main_company": ParagraphStyle(
            "main_company", parent=base, fontSize=9.5, leading=12,
            textColor=EUROPASS_GREY, spaceAfter=3,
        ),
        "main_body": ParagraphStyle(
            "main_body", parent=base, fontSize=10, leading=13,
        ),
        "main_bullet": ParagraphStyle(
            "main_bullet", parent=base, fontSize=9.5, leading=12,
            leftIndent=8, bulletIndent=0, spaceAfter=1,
        ),
        "main_sector": ParagraphStyle(
            "main_sector", parent=base, fontSize=8.5, leading=11,
            textColor=EUROPASS_GREY, fontName="Helvetica-Oblique",
        ),
    }


CEFR_DESC = {
    "A1": "Basic User", "A2": "Basic User",
    "B1": "Independent User", "B2": "Independent User",
    "C1": "Proficient User", "C2": "Proficient User",
}


def _cefr_pretty(level: str) -> str:
    level = (level or "").strip().upper()
    if level in CEFR_DESC:
        return f"{level} ({CEFR_DESC[level]})"
    return level or ""


# ---------------------------------------------------------------------------
# Section header (main column) — blue text + underline
# ---------------------------------------------------------------------------
def _main_section(title: str, st) -> list:
    return [
        Paragraph(title, st["main_section"]),
        HRFlowable(width="100%", thickness=0.6, color=EUROPASS_BLUE,
                   spaceBefore=0, spaceAfter=4),
    ]


def _side_section(title: str, st) -> list:
    return [
        Paragraph(title.upper(), st["side_section"]),
        HRFlowable(width="100%", thickness=0.4, color=EUROPASS_BLUE,
                   spaceBefore=0, spaceAfter=4),
    ]


# ---------------------------------------------------------------------------
# Sidebar content (Personal info / Languages / Skills / Certifications)
# ---------------------------------------------------------------------------
def _sidebar(resume: dict, st) -> list:
    flow: list = []
    contact = resume.get("contact", {}) or {}

    flow += _side_section("Personal information", st)
    fields = [
        ("Email", contact.get("email", "")),
        ("Phone", contact.get("phone", "")),
        ("Address", contact.get("address", "") or contact.get("location", "")),
        ("LinkedIn", contact.get("linkedin", "")),
        ("Website", contact.get("website", "")),
        ("Nationality", contact.get("nationality", "")),
        ("Date of birth", contact.get("date_of_birth", "")),
    ]
    for label, value in fields:
        if not value:
            continue
        flow.append(Paragraph(escape(label), st["side_label"]))
        flow.append(Paragraph(escape(value), st["side_value"]))
        flow.append(Spacer(0, 3))

    # Languages
    langs = resume.get("languages", []) or []
    if langs:
        flow += _side_section("Languages", st)
        mother = [l for l in langs if l.get("is_mother_tongue")]
        other = [l for l in langs if not l.get("is_mother_tongue")]
        if mother:
            flow.append(Paragraph("Mother tongue", st["side_label"]))
            flow.append(Paragraph(
                escape(", ".join(l.get("language", "") for l in mother)),
                st["side_value"],
            ))
            flow.append(Spacer(0, 4))
        if other:
            flow.append(Paragraph("Other languages", st["side_label"]))
            for l in other:
                line = (
                    f"<b>{escape(l.get('language',''))}</b><br/>"
                    f"<font size=8>{escape(_cefr_pretty(l.get('level','')))}</font>"
                )
                flow.append(Paragraph(line, st["side_value"]))
                flow.append(Spacer(0, 3))

    # Digital skills — cap at 20 to prevent sidebar overflow into right frame.
    all_skills = [s for s in (resume.get("skills") or []) if s and s.strip()]
    skills = all_skills[:20]
    if skills:
        flow += _side_section("Digital skills", st)
        bullet = '<font color="#003399"><b>&#183;</b></font>'
        chips = [
            f'{bullet}&nbsp;{escape(s).replace(" ", "&nbsp;")}'
            for s in skills
        ]
        if len(all_skills) > 20:
            chips.append(
                f'<font color="#4D4D4D"><i>+{len(all_skills) - 20} more</i></font>'
            )
        joined = '   '.join(chips)
        flow.append(Paragraph(joined, st["side_value"]))

    # Certifications are intentionally NOT in the sidebar — long URLs cause the
    # left frame to overflow into the right frame, pushing work experience to page 2.
    # They are rendered at the end of the main column instead.

    return flow


# ---------------------------------------------------------------------------
# Main column content (About me / Work / Education)
# ---------------------------------------------------------------------------
def _main(resume: dict, st) -> list:
    flow: list = []

    summary = (resume.get("summary") or "").strip()
    if summary:
        flow += _main_section("About me", st)
        flow.append(Paragraph(escape(summary), st["main_body"]))

    experience = resume.get("experience") or []
    if experience:
        flow += _main_section("Work experience", st)
        for exp in experience:
            start = (exp.get("start") or "").strip()
            end = (exp.get("end") or "").strip()
            date_str = f"{start} – {end}" if start and end else (start or end or "")
            role = (exp.get("role") or "").strip()
            company = (exp.get("company") or "").strip()
            location = (exp.get("location") or "").strip()
            sector = (exp.get("sector") or "").strip()
            bullets = [b for b in (exp.get("bullets") or []) if b and b.strip()]

            block: list = []
            if date_str:
                block.append(Paragraph(escape(date_str), st["main_date"]))
            if role:
                block.append(Paragraph(f"<b>{escape(role)}</b>", st["main_role"]))
            co_parts = [p for p in [company, location] if p]
            if co_parts:
                block.append(Paragraph(
                    escape(" — ".join(co_parts)), st["main_company"],
                ))
            if bullets:
                block.append(ListFlowable(
                    [
                        ListItem(Paragraph(escape(b), st["main_bullet"]),
                                 leftIndent=8)
                        for b in bullets
                    ],
                    bulletType="bullet", start="-", leftIndent=8,
                    bulletFontSize=9.5, spaceBefore=2, spaceAfter=2,
                ))
            if sector:
                block.append(Paragraph(
                    f"Business or sector: {escape(sector)}", st["main_sector"],
                ))
            block.append(Spacer(0, 6))
            flow.append(KeepTogether(block))

    education = resume.get("education") or []
    if education:
        flow += _main_section("Education and training", st)
        for ed in education:
            year = (ed.get("year") or "").strip()
            degree = (ed.get("degree") or "").strip()
            institution = (ed.get("institution") or "").strip()
            location = (ed.get("location") or "").strip()
            block: list = []
            if year:
                block.append(Paragraph(escape(year), st["main_date"]))
            if degree:
                block.append(Paragraph(f"<b>{escape(degree)}</b>", st["main_role"]))
            inst_parts = [p for p in [institution, location] if p]
            if inst_parts:
                block.append(Paragraph(
                    escape(" — ".join(inst_parts)), st["main_company"],
                ))
            block.append(Spacer(0, 4))
            flow.append(KeepTogether(block))

    # Certifications — placed here so long URLs don't overflow the narrow sidebar.
    certs = [c for c in (resume.get("certifications") or []) if c and c.strip()]
    if certs:
        flow += _main_section("Certifications", st)
        flow.append(ListFlowable(
            [
                ListItem(Paragraph(escape(c), st["main_bullet"]), leftIndent=8)
                for c in certs
            ],
            bulletType="bullet", start="-", leftIndent=8, bulletFontSize=9.5,
            spaceBefore=0, spaceAfter=2,
        ))

    # All skills (sidebar shows top 20; overflow shown here for completeness).
    all_skills = [s for s in (resume.get("skills") or []) if s and s.strip()]
    if len(all_skills) > 20:
        flow += _main_section("Additional skills", st)
        bullet = '<font color="#003399"><b>&#183;</b></font>'
        chips = [
            f'{bullet}&nbsp;{escape(s).replace(" ", "&nbsp;")}'
            for s in all_skills[20:]
        ]
        flow.append(Paragraph('   '.join(chips), st["main_body"]))

    return flow


# ---------------------------------------------------------------------------
# Document assembly with two frames (sidebar + main) + canvas-drawn header
# ---------------------------------------------------------------------------
def build_pdf_classic(resume: dict) -> bytes:
    """Build a classic two-column Europass PDF.

    Layout:
      Page 1: blue header band + left tinted sidebar (personal info, languages,
              skills, certs) + right main column (about me, work, education).
      Page 2+: thin header + single full-width column for overflow content
              (so work experience doesn't spill into a pretend "sidebar").
    """
    st = _styles()
    buf = io.BytesIO()

    page_w, page_h = A4
    margin_l = 1.2 * cm
    margin_r = 1.2 * cm
    margin_t = 1.2 * cm
    margin_b = 1.2 * cm
    header_h = 2.2 * cm
    cont_header_h = 0.9 * cm
    gap = 0.3 * cm

    usable_w = page_w - margin_l - margin_r
    sidebar_w = usable_w * 0.34
    main_w = usable_w - sidebar_w - gap
    frame_h = page_h - margin_t - margin_b - header_h - 0.3 * cm
    cont_frame_h = page_h - margin_t - margin_b - cont_header_h - 0.3 * cm

    name = resume.get("name", "")
    title = resume.get("title", "")

    def _draw_first_page(canvas, doc):
        canvas.saveState()
        band_y = page_h - margin_t - header_h
        # Blue header band
        canvas.setFillColor(EUROPASS_BLUE)
        canvas.rect(margin_l, band_y, usable_w, header_h, fill=1, stroke=0)
        # Sidebar tint (page 1 only)
        canvas.setFillColor(EUROPASS_SIDEBAR)
        canvas.rect(margin_l, margin_b, sidebar_w, frame_h + 0.3 * cm,
                    fill=1, stroke=0)
        # Name + role
        canvas.setFillColor(white)
        canvas.setFont("Helvetica-Bold", 22)
        canvas.drawString(margin_l + 14, band_y + header_h - 26, name[:60])
        canvas.setFont("Helvetica", 12)
        canvas.drawString(margin_l + 14, band_y + header_h - 50, title[:80])
        canvas.restoreState()

    def _draw_cont_page(canvas, doc):
        canvas.saveState()
        # Thin blue rule + name+role text + page number, NO sidebar tint
        top_y = page_h - margin_t
        canvas.setStrokeColor(EUROPASS_BLUE)
        canvas.setLineWidth(1.5)
        canvas.line(margin_l, top_y - 4, page_w - margin_r, top_y - 4)
        header_line = (
            f"{name} — {title}".strip(" —") if name or title else ""
        )
        canvas.setFillColor(EUROPASS_BLUE)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(margin_l, top_y - 18, header_line)
        canvas.setFillColor(EUROPASS_GREY)
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(page_w - margin_r, top_y - 18,
                                f"Page {doc.page}")
        canvas.restoreState()

    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=margin_l, rightMargin=margin_r,
        topMargin=margin_t, bottomMargin=margin_b,
        title=f"{name or 'Resume'} — Europass CV",
        author=name,
    )

    # Page 1: two-column (sidebar + main)
    left_frame = Frame(
        margin_l, margin_b, sidebar_w, frame_h,
        leftPadding=10, rightPadding=8, topPadding=8, bottomPadding=8,
        id="left", showBoundary=0,
    )
    right_frame = Frame(
        margin_l + sidebar_w + gap, margin_b, main_w, frame_h,
        leftPadding=8, rightPadding=4, topPadding=8, bottomPadding=8,
        id="right", showBoundary=0,
    )
    # Page 2+: single wide column for overflow
    cont_frame = Frame(
        margin_l, margin_b, usable_w, cont_frame_h,
        leftPadding=0, rightPadding=0, topPadding=6, bottomPadding=8,
        id="cont", showBoundary=0,
    )

    doc.addPageTemplates([
        PageTemplate(id="first", frames=[left_frame, right_frame],
                     onPage=_draw_first_page),
        PageTemplate(id="continuation", frames=[cont_frame],
                     onPage=_draw_cont_page),
    ])

    story: list = []
    story += _sidebar(resume, st)
    story.append(FrameBreak())                       # left → right on page 1
    # After page 1's right frame fills, any overflow goes to a fresh page
    # using the single-column continuation template.
    story.append(NextPageTemplate("continuation"))
    story += _main(resume, st)

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTML preview matching the PDF visually
# ---------------------------------------------------------------------------
HTML_CSS = """
body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt;
       color: #1a1a1a; line-height: 1.4; max-width: 800px;
       margin: 16px auto; padding: 0; background: white; }
.header {
    background: #003399; color: white; padding: 18px 22px;
    border-radius: 6px 6px 0 0;
}
.header h1 {color: white !important; margin: 0; font-size: 22pt; font-weight: 700;}
.header .role {color: white; opacity: 0.92; margin-top: 4px; font-size: 12pt;}
.layout { display: grid; grid-template-columns: 34% 66%; }
.sidebar { background: #F1F5FB; padding: 14px 14px 24px 14px; }
.main { padding: 14px 14px 24px 18px; }
.sb-section, .main-section {
    color: #003399; font-weight: 700; margin: 12pt 0 4pt 0;
    border-bottom: 1px solid #003399; padding-bottom: 2pt;
}
.sb-section {font-size: 10pt; text-transform: uppercase;}
.main-section {font-size: 12pt;}
.sb-label {color: #003399; font-weight: 700; font-size: 8.5pt; margin-top: 4pt;}
.sb-value {font-size: 9pt;}
.sb-bullets, .main-bullets {margin: 4pt 0 4pt 14pt; padding: 0;}
.sb-bullets li, .main-bullets li {margin-bottom: 2pt;}
.entry {margin-bottom: 8pt;}
.entry .date {color: #4d4d4d; font-weight: bold; font-size: 9pt;}
.entry .role {font-weight: bold; margin-top: 2pt;}
.entry .company {color: #4d4d4d; font-size: 9.5pt; margin-bottom: 3pt;}
.entry .sector {color: #4d4d4d; font-size: 8.5pt; font-style: italic; margin-top: 4pt;}
.skills-flow {font-size: 9pt; line-height: 1.7;}
.skills-flow .chip {white-space: nowrap; margin-right: 10px;}
.skills-flow .chip::before {content: '\\25CF'; color: #003399; margin-right: 5px; font-size: 8pt;}
"""


def render_html_classic(resume: dict) -> str:
    name = escape(resume.get("name", ""))
    title = escape(resume.get("title", ""))
    contact = resume.get("contact", {}) or {}

    # Sidebar HTML
    sb_parts: list[str] = ['<div class="sb-section">Personal information</div>']
    for label, value in [
        ("Email", contact.get("email", "")),
        ("Phone", contact.get("phone", "")),
        ("Address", contact.get("address", "") or contact.get("location", "")),
        ("LinkedIn", contact.get("linkedin", "")),
        ("Website", contact.get("website", "")),
        ("Nationality", contact.get("nationality", "")),
        ("Date of birth", contact.get("date_of_birth", "")),
    ]:
        if not value:
            continue
        sb_parts.append(
            f'<div class="sb-label">{escape(label)}</div>'
            f'<div class="sb-value">{escape(value)}</div>'
        )

    langs = resume.get("languages", []) or []
    if langs:
        sb_parts.append('<div class="sb-section">Languages</div>')
        mother = [l for l in langs if l.get("is_mother_tongue")]
        if mother:
            sb_parts.append('<div class="sb-label">Mother tongue</div>')
            sb_parts.append(
                f'<div class="sb-value">'
                f'{escape(", ".join(l.get("language","") for l in mother))}</div>'
            )
        other = [l for l in langs if not l.get("is_mother_tongue")]
        if other:
            sb_parts.append('<div class="sb-label">Other languages</div>')
            for l in other:
                sb_parts.append(
                    f'<div class="sb-value"><b>{escape(l.get("language",""))}</b> '
                    f'<span style="font-size:8.5pt;color:#4d4d4d">'
                    f'{escape(_cefr_pretty(l.get("level","")))}</span></div>'
                )

    all_skills = [s for s in (resume.get("skills") or []) if s and s.strip()]
    skills_sidebar = all_skills[:20]
    if skills_sidebar:
        sb_parts.append('<div class="sb-section">Digital skills</div>')
        chips = "".join(
            f'<span class="chip">{escape(s)}</span>' for s in skills_sidebar
        )
        if len(all_skills) > 20:
            chips += f'<span style="color:#4d4d4d;font-style:italic;font-size:8.5pt"> +{len(all_skills)-20} more</span>'
        sb_parts.append(f'<div class="skills-flow">{chips}</div>')

    # Main HTML
    main_parts: list[str] = []
    summary = escape(resume.get("summary", ""))
    if summary:
        main_parts.append(
            f'<div class="main-section">About me</div>'
            f'<div>{summary}</div>'
        )

    exp = resume.get("experience") or []
    if exp:
        main_parts.append('<div class="main-section">Work experience</div>')
        for e in exp:
            date = f"{escape(e.get('start',''))} – {escape(e.get('end',''))}".strip(" –")
            role = escape(e.get("role", ""))
            co = " — ".join(
                p for p in [escape(e.get("company", "")), escape(e.get("location", ""))] if p
            )
            bullets = "".join(f"<li>{escape(b)}</li>" for b in (e.get("bullets") or []) if b)
            sector = escape(e.get("sector", ""))
            main_parts.append(
                f'<div class="entry">'
                f'<div class="date">{date}</div>'
                f'<div class="role">{role}</div>'
                f'<div class="company">{co}</div>'
                + (f'<ul class="main-bullets">{bullets}</ul>' if bullets else "")
                + (f'<div class="sector">Business or sector: {sector}</div>' if sector else "")
                + '</div>'
            )

    edu = resume.get("education") or []
    if edu:
        main_parts.append('<div class="main-section">Education and training</div>')
        for ed in edu:
            year = escape(ed.get("year", ""))
            degree = escape(ed.get("degree", ""))
            inst = " — ".join(
                p for p in [escape(ed.get("institution", "")), escape(ed.get("location", ""))] if p
            )
            main_parts.append(
                f'<div class="entry">'
                f'<div class="date">{year}</div>'
                f'<div class="role">{degree}</div>'
                f'<div class="company">{inst}</div>'
                f'</div>'
            )

    certs = [c for c in (resume.get("certifications") or []) if c and c.strip()]
    if certs:
        main_parts.append('<div class="main-section">Certifications</div>')
        main_parts.append(
            '<ul class="main-bullets">'
            + "".join(f"<li>{escape(c)}</li>" for c in certs)
            + "</ul>"
        )

    if len(all_skills) > 20:
        main_parts.append('<div class="main-section">Additional skills</div>')
        chips = "".join(
            f'<span class="chip">{escape(s)}</span>' for s in all_skills[20:]
        )
        main_parts.append(f'<div class="skills-flow">{chips}</div>')

    return (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<title>{name} - Europass CV</title><style>{HTML_CSS}</style></head>'
        f'<body>'
        f'<div class="header"><h1>{name}</h1><div class="role">{title}</div></div>'
        f'<div class="layout">'
        f'<div class="sidebar">{"".join(sb_parts)}</div>'
        f'<div class="main">{"".join(main_parts)}</div>'
        f'</div></body></html>'
    )
