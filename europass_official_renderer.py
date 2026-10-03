"""Europass Official-template renderer.

Matches the layout of the official Europass online CV tool:
  - Single column, full width, generous margins
  - Big bold black name at top, thin grey rule below (no logo)
  - Personal information block: pipe-separated <b>Label:</b> Value pairs that
    wrap naturally across lines
  - Each section starts with a small grey dot bullet + BOLD UPPERCASE title +
    a grey horizontal rule extending to the right edge
  - Work experience entries: grey "DD/MM/YYYY – DD/MM/YYYY  Location" line,
    then bold ROLE plain Employer, then bulleted achievements
  - Digital skills as pipe-separated chips on a single line, wraps naturally
  - Language skills as a table with UNDERSTANDING / SPEAKING / WRITING column
    groups in the Europass standard layout
"""
from __future__ import annotations

import io
from html import escape

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

DARK = HexColor("#1A1A1A")
GREY = HexColor("#4D4D4D")
GREY_RULE = HexColor("#D1D5DB")
GREY_DOT = HexColor("#9CA3AF")
ACCENT = HexColor("#374151")  # near-black for section text (template uses black)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def _styles():
    base = ParagraphStyle(
        name="base", fontName="Helvetica", fontSize=10, leading=13.5,
        textColor=DARK, alignment=TA_LEFT,
    )
    return {
        "name": ParagraphStyle(
            "name", parent=base, fontName="Helvetica-Bold", fontSize=22,
            leading=26, spaceAfter=4,
        ),
        "personal": ParagraphStyle(
            "personal", parent=base, fontSize=10, leading=15,
            spaceAfter=2,
        ),
        "section": ParagraphStyle(
            "section", parent=base, fontName="Helvetica-Bold", fontSize=11,
            leading=14, textColor=ACCENT, spaceBefore=14, spaceAfter=0,
        ),
        "subhead": ParagraphStyle(
            "subhead", parent=base, fontSize=9.5, leading=12, textColor=GREY,
            spaceBefore=8, spaceAfter=2,
        ),
        "role": ParagraphStyle(
            "role", parent=base, fontName="Helvetica-Bold", fontSize=10.5,
            leading=13, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", parent=base, fontSize=10, leading=14,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base, fontSize=10, leading=13.5,
            leftIndent=12, firstLineIndent=-12, spaceAfter=2,
        ),
        "skills": ParagraphStyle(
            "skills", parent=base, fontSize=10, leading=16,
        ),
        "lang_h": ParagraphStyle(
            "lang_h", parent=base, fontName="Helvetica-Bold", fontSize=9,
            leading=11, textColor=ACCENT, alignment=TA_CENTER,
        ),
        "lang_sub": ParagraphStyle(
            "lang_sub", parent=base, fontSize=8.5, leading=10, textColor=GREY,
            alignment=TA_CENTER,
        ),
        "lang_lang": ParagraphStyle(
            "lang_lang", parent=base, fontName="Helvetica-Bold", fontSize=10,
            leading=13,
        ),
        "lang_cell": ParagraphStyle(
            "lang_cell", parent=base, fontSize=10, leading=13,
            alignment=TA_CENTER,
        ),
        "footnote": ParagraphStyle(
            "footnote", parent=base, fontSize=8, leading=10, textColor=GREY,
            fontName="Helvetica-Oblique", spaceBefore=4,
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
# Section header: small dot + BOLD UPPERCASE + grey rule extending right
# ---------------------------------------------------------------------------
def _section_header(title: str, st, total_width: float) -> Table:
    """Returns a Table containing [dot+title, horizontal rule] side by side."""
    title_upper = title.upper()
    # Width = (small dot ~6pt) + (gap 6pt) + bold uppercase title + breathing room
    title_render_w = stringWidth(title_upper, "Helvetica-Bold", 11) + 28
    rule_w = max(total_width - title_render_w, 50)

    # ZapfDingbats char "l" (0x6C) is the heavy black circle ● — built into
    # ReportLab and maps to U+25CF for clean text extraction.
    title_para = Paragraph(
        f'<font name="ZapfDingbats" size="10" color="#9CA3AF">l</font>'
        f'&nbsp;&nbsp;<b>{escape(title_upper)}</b>',
        st["section"],
    )
    t = Table(
        [[title_para, ""]],
        colWidths=[title_render_w, rule_w],
        rowHeights=[18],
    )
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        # Grey line under the second (empty) cell, aligned to the title baseline
        ("LINEBELOW", (1, 0), (1, 0), 0.6, GREY_RULE),
    ]))
    return t


# ---------------------------------------------------------------------------
# Personal information block — pipe-separated bold-label / plain value
# ---------------------------------------------------------------------------
def _personal_info_block(resume: dict, st) -> list:
    contact = resume.get("contact", {}) or {}
    items: list[tuple[str, str]] = []
    for label, key in [
        ("Date of birth", "date_of_birth"),
        ("Nationality", "nationality"),
        ("Phone", "phone"),
        ("Email", "email"),
        ("LinkedIn", "linkedin"),
        ("Website", "website"),
        ("Address", "address"),
        ("Location", "location"),
    ]:
        v = (contact.get(key) or "").strip()
        if v:
            items.append((label, v))
    if not items:
        return []
    sep = "&nbsp;&nbsp;|&nbsp;&nbsp;"
    text = sep.join(f"<b>{escape(l)}:</b> {escape(v)}" for l, v in items)
    return [Paragraph(text, st["personal"])]


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
def _section(title: str, st, total_width: float, body: list) -> list:
    if not body:
        return []
    return [_section_header(title, st, total_width), Spacer(0, 4)] + body


def _about_me(resume: dict, st) -> list:
    s = (resume.get("summary") or "").strip()
    if not s:
        return []
    return [Paragraph(escape(s), st["body"])]


def _format_date_range(start: str, end: str) -> str:
    start = (start or "").strip()
    end = (end or "").strip()
    if start and end:
        return f"{start} – {end}"
    return start or end or ""


def _work_experience(resume: dict, st) -> list:
    items = resume.get("experience", []) or []
    if not items:
        return []
    blocks: list = []
    for i, exp in enumerate(items):
        block: list = []
        date_str = _format_date_range(exp.get("start"), exp.get("end"))
        location = (exp.get("location") or "").strip()
        # Grey "date  location" line
        if date_str or location:
            line = date_str
            if location:
                if line:
                    line += f"&nbsp;&nbsp;&nbsp;&nbsp;{escape(location)}"
                else:
                    line = escape(location)
            block.append(Paragraph(line, st["subhead"]))
        # Bold ROLE + plain Employer
        role = (exp.get("role") or "").strip()
        company = (exp.get("company") or "").strip()
        if role or company:
            line = ""
            if role:
                line += f"<b>{escape(role)}</b>"
            if company:
                if line:
                    line += f"&nbsp;&nbsp;&middot;&nbsp;&nbsp;{escape(company)}"
                else:
                    line = escape(company)
            block.append(Paragraph(line, st["role"]))
        # Bullets — use • inline at start of paragraph (extracts cleanly from
        # WinAnsi, unlike ListFlowable's start="•" which trips a CID fallback)
        for bullet in (exp.get("bullets") or []):
            if bullet and bullet.strip():
                block.append(Paragraph(
                    f'<font size="11" color="#374151">&#183;</font>&nbsp;&nbsp;{escape(bullet.strip())}',
                    st["bullet"],
                ))
        # Sector footnote
        sector = (exp.get("sector") or "").strip()
        if sector:
            block.append(Paragraph(
                f"<i>Business or sector: {escape(sector)}</i>",
                st["footnote"],
            ))
        # Separator between entries (except after the last one)
        if i < len(items) - 1:
            block.append(Spacer(0, 4))
            block.append(HRFlowable(width="100%", color=GREY_RULE,
                                    thickness=0.3, spaceBefore=0, spaceAfter=4))
        else:
            block.append(Spacer(0, 4))
        blocks.append(KeepTogether(block))
    return blocks


def _digital_skills(resume: dict, st) -> list:
    skills = [s for s in (resume.get("skills") or []) if s and s.strip()]
    if not skills:
        return []
    # Pipe-separated, with nbsp around the | so each chip stays glued to its
    # separator AND the line can break between chips.
    # Within a multi-word skill, replace spaces with &nbsp; so "AWS Glue" stays atomic.
    chips = [escape(s).replace(" ", "&nbsp;") for s in skills]
    text = '&nbsp;&nbsp;|&nbsp;&nbsp;'.join(chips)
    return [Paragraph(text, st["skills"])]


def _education(resume: dict, st) -> list:
    items = resume.get("education", []) or []
    if not items:
        return []
    out: list = []
    for i, ed in enumerate(items):
        year = (ed.get("year") or "").strip()
        location = (ed.get("location") or "").strip()
        degree = (ed.get("degree") or "").strip()
        institution = (ed.get("institution") or "").strip()
        if year or location:
            line = year
            if location:
                line += f"&nbsp;&nbsp;&nbsp;&nbsp;{escape(location)}"
            out.append(Paragraph(line, st["subhead"]))
        if degree or institution:
            line = ""
            if degree:
                line += f"<b>{escape(degree)}</b>"
            if institution:
                if line:
                    line += f"&nbsp;&nbsp;&middot;&nbsp;&nbsp;{escape(institution)}"
                else:
                    line = escape(institution)
            out.append(Paragraph(line, st["role"]))
        if i < len(items) - 1:
            out.append(Spacer(0, 4))
            out.append(HRFlowable(width="100%", color=GREY_RULE,
                                  thickness=0.3, spaceBefore=0, spaceAfter=4))
    return out


def _languages(resume: dict, st, total_width: float) -> list:
    langs = resume.get("languages", []) or []
    if not langs:
        return []

    out: list = []
    mother = [l for l in langs if l.get("is_mother_tongue")]
    if mother:
        m_text = ", ".join(escape(l.get("language", "")) for l in mother)
        out.append(Paragraph(
            f"<b>Mother tongue(s):</b> {m_text}", st["body"],
        ))
        out.append(Spacer(0, 6))

    other = [l for l in langs if not l.get("is_mother_tongue")]
    if not other:
        return out

    # 6 columns: Language | Listening | Reading | Spoken production | Spoken interaction | Writing
    header1 = [
        Paragraph("", st["lang_h"]),
        Paragraph("UNDERSTANDING", st["lang_h"]),
        "",
        Paragraph("SPEAKING", st["lang_h"]),
        "",
        Paragraph("WRITING", st["lang_h"]),
    ]
    header2 = [
        Paragraph("", st["lang_sub"]),
        Paragraph("Listening", st["lang_sub"]),
        Paragraph("Reading", st["lang_sub"]),
        Paragraph("Spoken<br/>production", st["lang_sub"]),
        Paragraph("Spoken<br/>interaction", st["lang_sub"]),
        Paragraph("", st["lang_sub"]),
    ]

    data = [header1, header2]
    for l in other:
        lang_name = escape((l.get("language") or "").upper())
        level = _cefr_pretty(l.get("level", "")).split(" ")[0]  # just "C1"
        data.append([
            Paragraph(f"<b>{lang_name}</b>", st["lang_lang"]),
            Paragraph(level, st["lang_cell"]),
            Paragraph(level, st["lang_cell"]),
            Paragraph(level, st["lang_cell"]),
            Paragraph(level, st["lang_cell"]),
            Paragraph(level, st["lang_cell"]),
        ])

    col_w = total_width / 6.5
    t = Table(
        data,
        colWidths=[col_w * 1.4, col_w * 0.9, col_w * 0.9, col_w * 1.1,
                   col_w * 1.1, col_w * 1.1],
    )
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        # Group header spans
        ("SPAN", (1, 0), (2, 0)),  # UNDERSTANDING covers Listening + Reading
        ("SPAN", (3, 0), (4, 0)),  # SPEAKING covers Spoken production + interaction
        # Header row backgrounds
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#F3F4F6")),
        ("BACKGROUND", (0, 1), (-1, 1), HexColor("#F9FAFB")),
        # Thin grey row separators
        ("LINEBELOW", (0, 0), (-1, 0), 0.3, GREY_RULE),
        ("LINEBELOW", (0, 1), (-1, 1), 0.3, GREY_RULE),
        ("LINEBELOW", (0, 2), (-1, -1), 0.3, GREY_RULE),
    ]))
    out.append(t)
    out.append(Spacer(0, 4))
    out.append(Paragraph(
        "<i>Levels: A1 / A2 — Basic user; B1 / B2 — Independent user; "
        "C1 / C2 — Proficient user.</i>",
        st["footnote"],
    ))
    return out


def _additional(resume: dict, st) -> list:
    certs = [c for c in (resume.get("certifications") or []) if c and c.strip()]
    if not certs:
        return []
    out: list = []
    out.append(Paragraph("<b>Certifications</b>", st["role"]))
    for c in certs:
        out.append(Paragraph(
            f'<font size="11" color="#374151">&#183;</font>&nbsp;&nbsp;{escape(c)}',
            st["bullet"],
        ))
    return out


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------
def build_pdf_official(resume: dict) -> bytes:
    st = _styles()
    buf = io.BytesIO()

    page_w, page_h = A4
    margin_l = 1.8 * cm
    margin_r = 1.8 * cm
    margin_t = 1.6 * cm
    margin_b = 1.6 * cm
    usable_w = page_w - margin_l - margin_r

    name = resume.get("name", "First Name Last Name")
    title = resume.get("title", "")

    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=margin_l, rightMargin=margin_r,
        topMargin=margin_t, bottomMargin=margin_b,
        title=f"{name} — Europass CV",
        author=name,
    )
    frame = Frame(
        margin_l, margin_b, usable_w, page_h - margin_t - margin_b,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
        id="main", showBoundary=0,
    )
    doc.addPageTemplates([PageTemplate(id="official", frames=[frame])])

    story: list = []
    # Name header (no logo)
    story.append(Paragraph(escape(name), st["name"]))
    if title:
        story.append(Paragraph(
            f'<font color="#4D4D4D" size="12">{escape(title)}</font>',
            st["body"],
        ))
    story.append(HRFlowable(width="100%", color=GREY_RULE, thickness=0.5,
                            spaceBefore=6, spaceAfter=10))

    # Personal info block (no section header — sits between name rule and first section)
    story += _personal_info_block(resume, st)

    # Sections
    story += _section("About me", st, usable_w, _about_me(resume, st))
    story += _section("Work experience", st, usable_w, _work_experience(resume, st))
    story += _section("Digital skills", st, usable_w, _digital_skills(resume, st))
    story += _section("Education and training", st, usable_w, _education(resume, st))
    story += _section("Language skills", st, usable_w, _languages(resume, st, usable_w))
    story += _section("Additional information", st, usable_w, _additional(resume, st))

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTML preview that mirrors the PDF visually
# ---------------------------------------------------------------------------
HTML_CSS = """
body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt;
       color: #1a1a1a; line-height: 1.45; max-width: 760px;
       margin: 24px auto; padding: 0 16px; background: white; }
h1 { font-size: 26pt; margin: 0 0 4pt 0; color: #1a1a1a; font-weight: 800; letter-spacing: -0.5px; }
.role { font-size: 13pt; color: #4d4d4d; margin: 0 0 10pt 0; }
.name-rule { border-top: 1px solid #D1D5DB; margin: 6pt 0 14pt 0; }
.personal { font-size: 10pt; line-height: 1.6; margin-bottom: 4pt; }
.section { display: flex; align-items: baseline; gap: 10px; margin-top: 18pt; margin-bottom: 6pt; }
.section .dot { color: #9CA3AF; font-size: 14px; }
.section .name { font-weight: 800; font-size: 11pt; text-transform: uppercase; letter-spacing: 1px; color: #374151; }
.section .rule { flex: 1; border-bottom: 0.6px solid #D1D5DB; }
.entry { margin-bottom: 10pt; }
.entry .head { color: #4d4d4d; font-size: 9.5pt; margin-bottom: 2pt; }
.entry .role-line { font-weight: bold; font-size: 10.5pt; margin-bottom: 4pt; }
.entry .role-line .sep { color: #9CA3AF; }
.entry ul { margin: 4pt 0 4pt 18pt; padding: 0; }
.entry li { margin-bottom: 2pt; }
.entry .sector { color: #4d4d4d; font-size: 8.5pt; font-style: italic; margin-top: 4pt; }
.entry-sep { border-top: 0.5px solid #E5E7EB; margin: 8pt 0; }
.skills-line { font-size: 10pt; line-height: 1.7; }
table.langs { width: 100%; border-collapse: collapse; margin-top: 6pt; }
table.langs th { background: #F3F4F6; font-size: 9pt; font-weight: bold; padding: 6px 4px; text-align: center; color: #374151; text-transform: uppercase; letter-spacing: 0.6px; }
table.langs th.sub { background: #F9FAFB; font-weight: normal; color: #4d4d4d; text-transform: none; letter-spacing: 0; font-size: 8.5pt; }
table.langs td { padding: 6px 4px; text-align: center; border-bottom: 0.5px solid #E5E7EB; font-size: 10pt; }
table.langs td.lang { text-align: left; font-weight: bold; }
.footnote { color: #4d4d4d; font-size: 8.5pt; font-style: italic; margin-top: 4pt; }
"""


def _personal_info_html(resume):
    contact = resume.get("contact", {}) or {}
    items = []
    for label, key in [
        ("Date of birth", "date_of_birth"),
        ("Nationality", "nationality"),
        ("Phone", "phone"),
        ("Email", "email"),
        ("LinkedIn", "linkedin"),
        ("Website", "website"),
        ("Address", "address"),
        ("Location", "location"),
    ]:
        v = (contact.get(key) or "").strip()
        if v:
            items.append(f'<b>{escape(label)}:</b> {escape(v)}')
    return '<div class="personal">' + ' &nbsp;|&nbsp; '.join(items) + '</div>' if items else ''


def _section_html(title):
    return (
        f'<div class="section">'
        f'<span class="dot">&#9679;</span>'
        f'<span class="name">{escape(title.upper())}</span>'
        f'<span class="rule"></span>'
        f'</div>'
    )


def render_html_official(resume: dict) -> str:
    name = escape(resume.get("name", ""))
    title = escape(resume.get("title", ""))

    parts: list[str] = [f'<h1>{name}</h1>']
    if title:
        parts.append(f'<div class="role">{title}</div>')
    parts.append('<div class="name-rule"></div>')
    parts.append(_personal_info_html(resume))

    # About me
    summary = escape(resume.get("summary", ""))
    if summary:
        parts.append(_section_html("About me"))
        parts.append(f'<div>{summary}</div>')

    # Work experience
    exp = resume.get("experience") or []
    if exp:
        parts.append(_section_html("Work experience"))
        for i, e in enumerate(exp):
            date = _format_date_range(e.get("start"), e.get("end"))
            location = escape(e.get("location", ""))
            head = " &nbsp;&nbsp; ".join(p for p in [date, location] if p)
            role = escape(e.get("role", ""))
            company = escape(e.get("company", ""))
            role_line = f'<b>{role}</b>'
            if company:
                role_line += f' <span class="sep">&middot;</span> {company}'
            bullets = "".join(
                f"<li>{escape(b)}</li>" for b in (e.get("bullets") or []) if b
            )
            sector = escape(e.get("sector", ""))
            entry = (
                f'<div class="entry">'
                f'<div class="head">{head}</div>'
                f'<div class="role-line">{role_line}</div>'
                + (f'<ul>{bullets}</ul>' if bullets else '')
                + (f'<div class="sector">Business or sector: {sector}</div>'
                   if sector else '')
                + '</div>'
            )
            parts.append(entry)
            if i < len(exp) - 1:
                parts.append('<div class="entry-sep"></div>')

    # Digital skills
    skills = [s for s in (resume.get("skills") or []) if s and s.strip()]
    if skills:
        parts.append(_section_html("Digital skills"))
        chips = ' &nbsp;|&nbsp; '.join(
            f'<span style="white-space:nowrap">{escape(s)}</span>' for s in skills
        )
        parts.append(f'<div class="skills-line">{chips}</div>')

    # Education
    edu = resume.get("education") or []
    if edu:
        parts.append(_section_html("Education and training"))
        for i, ed in enumerate(edu):
            year = escape(ed.get("year", ""))
            location = escape(ed.get("location", ""))
            degree = escape(ed.get("degree", ""))
            institution = escape(ed.get("institution", ""))
            head = " &nbsp;&nbsp; ".join(p for p in [year, location] if p)
            line = f'<b>{degree}</b>'
            if institution:
                line += f' <span class="sep">&middot;</span> {institution}'
            entry = (
                f'<div class="entry">'
                f'<div class="head">{head}</div>'
                f'<div class="role-line">{line}</div>'
                f'</div>'
            )
            parts.append(entry)
            if i < len(edu) - 1:
                parts.append('<div class="entry-sep"></div>')

    # Languages
    langs = resume.get("languages") or []
    if langs:
        parts.append(_section_html("Language skills"))
        mother = [l for l in langs if l.get("is_mother_tongue")]
        if mother:
            m = ", ".join(escape(l.get("language", "")) for l in mother)
            parts.append(f'<div><b>Mother tongue(s):</b> {m}</div>')
        other = [l for l in langs if not l.get("is_mother_tongue")]
        if other:
            rows = ""
            for l in other:
                lang_u = escape((l.get("language") or "").upper())
                level = _cefr_pretty(l.get("level", "")).split(" ")[0]
                rows += (
                    f'<tr>'
                    f'<td class="lang">{lang_u}</td>'
                    f'<td>{level}</td><td>{level}</td>'
                    f'<td>{level}</td><td>{level}</td><td>{level}</td>'
                    f'</tr>'
                )
            parts.append(
                '<table class="langs">'
                '<thead>'
                '<tr><th></th><th colspan="2">UNDERSTANDING</th>'
                '<th colspan="2">SPEAKING</th><th>WRITING</th></tr>'
                '<tr><th class="sub"></th>'
                '<th class="sub">Listening</th><th class="sub">Reading</th>'
                '<th class="sub">Spoken production</th>'
                '<th class="sub">Spoken interaction</th><th class="sub"></th></tr>'
                '</thead>'
                f'<tbody>{rows}</tbody>'
                '</table>'
                '<div class="footnote">Levels: A1 / A2 — Basic user; '
                'B1 / B2 — Independent user; C1 / C2 — Proficient user.</div>'
            )

    # Additional
    certs = [c for c in (resume.get("certifications") or []) if c and c.strip()]
    if certs:
        parts.append(_section_html("Additional information"))
        parts.append('<div><b>Certifications</b></div>')
        parts.append(
            '<ul>' + "".join(f"<li>{escape(c)}</li>" for c in certs) + '</ul>'
        )

    return (
        f'<!doctype html><html><head><meta charset="utf-8">'
        f'<title>{name} - Europass CV</title><style>{HTML_CSS}</style></head>'
        f'<body>{"".join(parts)}</body></html>'
    )
