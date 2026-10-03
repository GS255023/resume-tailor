"""Modern Europass-style renderer.

Single-column layout (the post-2020 Europass redesign), dates-left date-band
on each entry, EU-blue section headers, CEFR language table.

Built directly with ReportLab so the text-extraction order is correct for
European ATS scanners (which understand Europass conventions) while looking
visually like the official Europass CV.
"""
from __future__ import annotations

import io
from html import escape

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

EUROPASS_BLUE = HexColor("#003399")   # EU flag blue
EUROPASS_DARK = HexColor("#1A1A1A")
EUROPASS_GREY = HexColor("#4D4D4D")
EUROPASS_LIGHT = HexColor("#E8EEF7")


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def _styles():
    base = ParagraphStyle(
        name="base", fontName="Helvetica", fontSize=10, leading=12.5,
        textColor=EUROPASS_DARK, alignment=TA_LEFT,
    )
    return {
        "name": ParagraphStyle(
            "name", parent=base, fontName="Helvetica-Bold", fontSize=22,
            leading=26, textColor=EUROPASS_BLUE, spaceAfter=2,
        ),
        "title": ParagraphStyle(
            "title", parent=base, fontSize=12, leading=14, textColor=EUROPASS_GREY,
            spaceAfter=10,
        ),
        "section": ParagraphStyle(
            "section", parent=base, fontName="Helvetica-Bold", fontSize=11,
            leading=14, textColor=EUROPASS_BLUE, spaceBefore=14, spaceAfter=4,
        ),
        "date": ParagraphStyle(
            "date", parent=base, fontSize=9.5, leading=12, textColor=EUROPASS_GREY,
        ),
        "role": ParagraphStyle(
            "role", parent=base, fontName="Helvetica-Bold", fontSize=10.5,
            leading=13,
        ),
        "company": ParagraphStyle(
            "company", parent=base, fontSize=10, leading=12.5, textColor=EUROPASS_GREY,
            spaceAfter=3,
        ),
        "sector": ParagraphStyle(
            "sector", parent=base, fontSize=9, leading=11,
            textColor=EUROPASS_GREY, fontName="Helvetica-Oblique",
        ),
        "body": ParagraphStyle("body", parent=base, fontSize=10, leading=12.5),
        "small": ParagraphStyle("small", parent=base, fontSize=9, leading=11,
                                textColor=EUROPASS_GREY),
        "bullet": ParagraphStyle(
            "bullet", parent=base, fontSize=10, leading=12.5,
            leftIndent=8, bulletIndent=0, spaceAfter=1,
        ),
        "contact_label": ParagraphStyle(
            "contact_label", parent=base, fontSize=9, leading=11,
            textColor=EUROPASS_BLUE, fontName="Helvetica-Bold",
        ),
        "contact_value": ParagraphStyle(
            "contact_value", parent=base, fontSize=10, leading=12.5,
        ),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _section(title: str, st) -> list:
    """A blue section header followed by a thin blue rule."""
    return [
        Paragraph(title, st["section"]),
        HRFlowable(
            width="100%", thickness=0.5, color=EUROPASS_BLUE,
            spaceBefore=0, spaceAfter=4,
        ),
    ]


def _two_col(date_str: str, content_flowables, st, date_col=3.5 * cm):
    """Date on the left, content on the right — Europass entry shape."""
    rows = [[Paragraph(escape(date_str), st["date"]), content_flowables]]
    t = Table(rows, colWidths=[date_col, None])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


# CEFR self-assessment levels (Europass standard)
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
# Sections
# ---------------------------------------------------------------------------
def _personal_information(resume: dict, st) -> list:
    out: list = []
    out.append(Paragraph(escape(resume.get("name", "")), st["name"]))
    title = resume.get("title", "")
    if title:
        out.append(Paragraph(escape(title), st["title"]))

    contact = resume.get("contact", {}) or {}

    # Two-column contact grid: label | value
    rows = []
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
        rows.append([
            Paragraph(escape(label), st["contact_label"]),
            Paragraph(escape(value), st["contact_value"]),
        ])
    if rows:
        t = Table(rows, colWidths=[3.5 * cm, None])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        out.append(t)
    return out


def _about_me(resume: dict, st) -> list:
    summary = resume.get("summary", "").strip()
    if not summary:
        return []
    return _section("About me", st) + [Paragraph(escape(summary), st["body"])]


def _work_experience(resume: dict, st) -> list:
    items = resume.get("experience", []) or []
    if not items:
        return []
    out = _section("Work experience", st)
    for exp in items:
        start = (exp.get("start") or "").strip()
        end = (exp.get("end") or "").strip()
        date_str = (
            f"{start} – {end}" if start and end else (start or end or "")
        )
        role = (exp.get("role") or "").strip()
        company = (exp.get("company") or "").strip()
        location = (exp.get("location") or "").strip()
        sector = (exp.get("sector") or "").strip()
        bullets = [b for b in (exp.get("bullets") or []) if b and b.strip()]

        content: list = []
        if role:
            content.append(Paragraph(f"<b>{escape(role)}</b>", st["role"]))
        co_line_parts = [p for p in [company, location] if p]
        if co_line_parts:
            content.append(
                Paragraph(escape(" — ".join(co_line_parts)), st["company"])
            )
        if bullets:
            content.append(ListFlowable(
                [
                    ListItem(Paragraph(escape(b), st["bullet"]), leftIndent=8)
                    for b in bullets
                ],
                bulletType="bullet", start="-", leftIndent=8,
                bulletFontSize=10, spaceBefore=2, spaceAfter=2,
            ))
        if sector:
            content.append(Paragraph(
                f"Business or sector: {escape(sector)}", st["sector"]
            ))

        out.append(KeepTogether(_two_col(date_str, content, st)))
    return out


def _education_and_training(resume: dict, st) -> list:
    items = resume.get("education", []) or []
    if not items:
        return []
    out = _section("Education and training", st)
    for ed in items:
        year = (ed.get("year") or "").strip()
        degree = (ed.get("degree") or "").strip()
        institution = (ed.get("institution") or "").strip()
        location = (ed.get("location") or "").strip()

        content: list = []
        if degree:
            content.append(Paragraph(f"<b>{escape(degree)}</b>", st["role"]))
        inst_line_parts = [p for p in [institution, location] if p]
        if inst_line_parts:
            content.append(
                Paragraph(escape(" — ".join(inst_line_parts)), st["company"])
            )
        out.append(_two_col(year, content, st))
    return out


def _personal_skills(resume: dict, st) -> list:
    """Includes language skills (Europass-required) + technical skills list."""
    out: list = []
    langs = resume.get("languages", []) or []
    skills = [s for s in (resume.get("skills") or []) if s and s.strip()]
    if not langs and not skills:
        return out

    out += _section("Personal skills", st)

    # Mother tongue
    mother = [l for l in langs if l.get("is_mother_tongue")]
    if mother:
        rows = [[
            Paragraph("Mother tongue(s)", st["contact_label"]),
            Paragraph(
                escape(", ".join(l.get("language", "") for l in mother)),
                st["body"],
            ),
        ]]
        t = Table(rows, colWidths=[3.5 * cm, None])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        out.append(t)

    # Other languages with CEFR
    other = [l for l in langs if not l.get("is_mother_tongue")]
    if other:
        rows = [[
            Paragraph("Other language(s)", st["contact_label"]),
            Paragraph(
                "<br/>".join(
                    f"<b>{escape(l.get('language',''))}</b> &nbsp; "
                    f"{escape(_cefr_pretty(l.get('level','')))}"
                    for l in other
                ),
                st["body"],
            ),
        ]]
        t = Table(rows, colWidths=[3.5 * cm, None])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        out.append(t)

    # Digital skills — flowing chips with circle bullets (single paragraph,
    # wraps naturally). Uses U+00B7 (middle dot) which extracts cleanly from
    # Helvetica/WinAnsi unlike U+2022.
    if skills:
        rows = [[
            Paragraph("Digital skills", st["contact_label"]),
            Paragraph(
                '   '.join(
                    f'<font color="#003399"><b>&#183;</b></font>'
                    f'&nbsp;{escape(s).replace(" ", "&nbsp;")}'
                    for s in skills
                ),
                st["body"],
            ),
        ]]
        t = Table(rows, colWidths=[3.5 * cm, None])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        out.append(t)

    return out


def _additional_information(resume: dict, st) -> list:
    certs = [c for c in (resume.get("certifications") or []) if c and c.strip()]
    if not certs:
        return []
    out = _section("Additional information", st)
    out.append(Paragraph("<b>Certifications</b>", st["role"]))
    out.append(ListFlowable(
        [ListItem(Paragraph(escape(c), st["bullet"]), leftIndent=8) for c in certs],
        bulletType="bullet", start="-", leftIndent=8, bulletFontSize=10,
        spaceBefore=2,
    ))
    return out


# ---------------------------------------------------------------------------
# Build the document
# ---------------------------------------------------------------------------
def _build_story(resume: dict) -> list:
    st = _styles()
    story: list = []
    story += _personal_information(resume, st)
    story += _about_me(resume, st)
    story += _work_experience(resume, st)
    story += _education_and_training(resume, st)
    story += _personal_skills(resume, st)
    story += _additional_information(resume, st)
    return story


def build_pdf_europass(resume: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.4 * cm, bottomMargin=1.4 * cm,
        title=f"{resume.get('name', 'Resume')} — Europass CV",
        author=resume.get("name", ""),
    )
    doc.build(_build_story(resume))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTML preview (mirrors the PDF visually)
# ---------------------------------------------------------------------------
HTML_CSS = """
body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt;
       color: #1a1a1a; line-height: 1.4; max-width: 760px;
       margin: 24px auto; padding: 0 16px; }
h1 { font-size: 22pt; margin: 0 0 2pt 0; color: #003399; }
.title { font-size: 12pt; color: #4d4d4d; margin: 0 0 12pt 0; }
h2 { font-size: 11pt; margin: 16pt 0 4pt 0; padding-bottom: 2pt;
     color: #003399; border-bottom: 1px solid #003399;
     text-transform: none; letter-spacing: 0; }
.entry { display: grid; grid-template-columns: 130px 1fr; gap: 12px;
         margin-bottom: 10pt; }
.entry .date { color: #4d4d4d; font-size: 9.5pt; }
.entry .role { font-weight: bold; }
.entry .company { color: #4d4d4d; font-size: 10pt; margin-bottom: 4pt; }
.entry .sector { color: #4d4d4d; font-size: 9pt; font-style: italic; margin-top: 4pt; }
.entry ul { margin: 4pt 0 0 16pt; padding: 0; }
.entry li { margin-bottom: 2pt; }
.contact-grid { display: grid; grid-template-columns: 130px 1fr; gap: 4px 12px;
                margin-bottom: 6pt; }
.contact-grid .label { color: #003399; font-weight: bold; font-size: 9pt; }
.skills-grid { display: grid; grid-template-columns: 130px 1fr; gap: 4px 12px; }
.skills-grid .label { color: #003399; font-weight: bold; font-size: 9pt; }
"""


def render_html_europass(resume: dict) -> str:
    name = escape(resume.get("name", ""))
    title = escape(resume.get("title", ""))
    contact = resume.get("contact", {}) or {}

    contact_fields = [
        ("Email", contact.get("email", "")),
        ("Phone", contact.get("phone", "")),
        ("Address", contact.get("address", "") or contact.get("location", "")),
        ("LinkedIn", contact.get("linkedin", "")),
        ("Website", contact.get("website", "")),
        ("Nationality", contact.get("nationality", "")),
        ("Date of birth", contact.get("date_of_birth", "")),
    ]
    contact_html = "".join(
        f'<div class="label">{escape(l)}</div><div>{escape(v)}</div>'
        for l, v in contact_fields if v
    )

    parts: list[str] = []
    parts.append(f'<h1>{name}</h1><div class="title">{title}</div>')
    if contact_html:
        parts.append(f'<div class="contact-grid">{contact_html}</div>')

    summary = escape(resume.get("summary", ""))
    if summary:
        parts.append(f'<h2>About me</h2><div>{summary}</div>')

    exp_html: list[str] = []
    for exp in resume.get("experience", []) or []:
        date = f"{escape(exp.get('start',''))} – {escape(exp.get('end',''))}".strip(" –")
        role = escape(exp.get("role", ""))
        company_loc = " — ".join(
            p for p in [escape(exp.get("company", "")), escape(exp.get("location", ""))] if p
        )
        bullets = "".join(f"<li>{escape(b)}</li>" for b in (exp.get("bullets") or []) if b)
        sector = escape(exp.get("sector", ""))
        exp_html.append(
            f'<div class="entry"><div class="date">{date}</div><div>'
            f'<div class="role">{role}</div>'
            f'<div class="company">{company_loc}</div>'
            + (f'<ul>{bullets}</ul>' if bullets else '')
            + (f'<div class="sector">Business or sector: {sector}</div>' if sector else '')
            + '</div></div>'
        )
    if exp_html:
        parts.append('<h2>Work experience</h2>' + "".join(exp_html))

    edu_html: list[str] = []
    for ed in resume.get("education", []) or []:
        year = escape(ed.get("year", ""))
        degree = escape(ed.get("degree", ""))
        inst_loc = " — ".join(
            p for p in [escape(ed.get("institution", "")), escape(ed.get("location", ""))] if p
        )
        edu_html.append(
            f'<div class="entry"><div class="date">{year}</div><div>'
            f'<div class="role">{degree}</div>'
            f'<div class="company">{inst_loc}</div>'
            f'</div></div>'
        )
    if edu_html:
        parts.append('<h2>Education and training</h2>' + "".join(edu_html))

    langs = resume.get("languages", []) or []
    skills = resume.get("skills", []) or []
    if langs or skills:
        rows: list[str] = []
        mother = [l for l in langs if l.get("is_mother_tongue")]
        if mother:
            rows.append(
                '<div class="label">Mother tongue(s)</div>'
                f'<div>{escape(", ".join(l.get("language","") for l in mother))}</div>'
            )
        other = [l for l in langs if not l.get("is_mother_tongue")]
        if other:
            other_html = "<br/>".join(
                f'<b>{escape(l.get("language",""))}</b> &nbsp; {escape(_cefr_pretty(l.get("level","")))}'
                for l in other
            )
            rows.append(
                f'<div class="label">Other language(s)</div><div>{other_html}</div>'
            )
        if skills:
            chips_html = (
                '<div style="line-height:1.7;font-size:10pt;">'
                + "".join(
                    f'<span style="white-space:nowrap;margin-right:10px;">'
                    f'<span style="color:#003399;font-size:8pt;">&#9679;</span>&nbsp;{escape(s)}'
                    f'</span>'
                    for s in skills
                )
                + '</div>'
            )
            rows.append(
                '<div class="label">Digital skills</div>'
                f'<div>{chips_html}</div>'
            )
        parts.append(
            '<h2>Personal skills</h2>'
            f'<div class="skills-grid">{"".join(rows)}</div>'
        )

    certs = [c for c in (resume.get("certifications") or []) if c]
    if certs:
        certs_html = "".join(f"<li>{escape(c)}</li>" for c in certs)
        parts.append(
            '<h2>Additional information</h2>'
            '<div class="role">Certifications</div>'
            f'<ul>{certs_html}</ul>'
        )

    return (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<title>{name} - Europass CV</title><style>{HTML_CSS}</style>'
        f'</head><body>{"".join(parts)}</body></html>'
    )
