"""ATS-optimized renderer.

PDF is built directly with ReportLab (no HTML->PDF translation) so the text
extraction order is exactly what we want. HTML preview mirrors the same
single-column, standard-section-headers layout for browser viewing.
"""
from __future__ import annotations

import io
from html import escape

from reportlab.lib.colors import HexColor, black
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

# ---------------------------------------------------------------------------
# PDF (ATS-optimized via ReportLab)
# ---------------------------------------------------------------------------

_DARK = HexColor("#222222")
_GREY = HexColor("#555555")


def _styles():
    base = ParagraphStyle(
        name="base",
        fontName="Helvetica",
        fontSize=10,
        leading=12.5,
        textColor=_DARK,
        alignment=TA_LEFT,
    )
    name = ParagraphStyle(
        "name", parent=base, fontName="Helvetica-Bold", fontSize=18, leading=22,
        spaceAfter=2,
    )
    title = ParagraphStyle(
        "title", parent=base, fontSize=11, leading=13, textColor=_GREY,
        spaceAfter=2,
    )
    contact = ParagraphStyle(
        "contact", parent=base, fontSize=9.5, leading=12, textColor=_GREY,
        spaceAfter=10,
    )
    section = ParagraphStyle(
        "section", parent=base, fontName="Helvetica-Bold", fontSize=11,
        leading=14, textColor=black, spaceBefore=10, spaceAfter=4,
    )
    role = ParagraphStyle(
        "role", parent=base, fontName="Helvetica-Bold", fontSize=10.5,
        leading=13, spaceBefore=4,
    )
    company = ParagraphStyle(
        "company", parent=base, fontSize=10, leading=12.5, textColor=_GREY,
        spaceAfter=3,
    )
    body = ParagraphStyle(
        "body", parent=base, fontSize=10, leading=12.5, spaceAfter=3,
    )
    bullet = ParagraphStyle(
        "bullet", parent=base, fontSize=10, leading=12.5, leftIndent=10,
        bulletIndent=0, spaceAfter=1,
    )
    return {
        "name": name, "title": title, "contact": contact, "section": section,
        "role": role, "company": company, "body": body, "bullet": bullet,
    }


def _section_header(text: str, st) -> list:
    # Standard, unstyled section names that ATS parsers recognize verbatim.
    return [Paragraph(text.upper(), st["section"])]


def _build_story(resume: dict) -> list:
    st = _styles()
    story: list = []

    name = (resume.get("name") or "").strip()
    title = (resume.get("title") or "").strip()
    if name:
        story.append(Paragraph(escape(name), st["name"]))
    if title:
        story.append(Paragraph(escape(title), st["title"]))

    contact = resume.get("contact", {}) or {}
    contact_parts = []
    for key in ("email", "phone", "location", "linkedin", "website"):
        v = (contact.get(key) or "").strip()
        if v:
            contact_parts.append(escape(v))
    if contact_parts:
        story.append(Paragraph(" | ".join(contact_parts), st["contact"]))

    summary = (resume.get("summary") or "").strip()
    if summary:
        story += _section_header("Summary", st)
        story.append(Paragraph(escape(summary), st["body"]))

    skills = [s for s in (resume.get("skills") or []) if s and s.strip()]
    if skills:
        story += _section_header("Skills", st)
        # Comma-separated single paragraph — ATS-friendliest format.
        story.append(Paragraph(escape(", ".join(skills)), st["body"]))

    experience = resume.get("experience") or []
    if experience:
        story += _section_header("Professional Experience", st)
        for exp in experience:
            role = (exp.get("role") or "").strip()
            company = (exp.get("company") or "").strip()
            location = (exp.get("location") or "").strip()
            start = (exp.get("start") or "").strip()
            end = (exp.get("end") or "").strip()
            bullets = [b for b in (exp.get("bullets") or []) if b and b.strip()]

            if role:
                story.append(Paragraph(f"<b>{escape(role)}</b>", st["role"]))
            # Single line: Company | Location | Start - End  (all ASCII, no floats)
            line2_parts = []
            if company:
                line2_parts.append(escape(company))
            if location:
                line2_parts.append(escape(location))
            date_range = ""
            if start and end:
                date_range = f"{start} - {end}"
            elif start:
                date_range = start
            elif end:
                date_range = end
            if date_range:
                line2_parts.append(escape(date_range))
            if line2_parts:
                story.append(Paragraph(" | ".join(line2_parts), st["company"]))

            if bullets:
                items = [
                    ListItem(
                        Paragraph(escape(b), st["bullet"]),
                        leftIndent=10, bulletColor=_DARK,
                    )
                    for b in bullets
                ]
                story.append(
                    ListFlowable(
                        items,
                        bulletType="bullet",
                        start="-",  # plain ASCII hyphen — extractable verbatim
                        leftIndent=10,
                        bulletFontSize=10,
                        spaceBefore=2,
                        spaceAfter=4,
                    )
                )

    education = resume.get("education") or []
    if education:
        story += _section_header("Education", st)
        for ed in education:
            degree = (ed.get("degree") or "").strip()
            institution = (ed.get("institution") or "").strip()
            year = (ed.get("year") or "").strip()
            if degree:
                story.append(Paragraph(f"<b>{escape(degree)}</b>", st["role"]))
            sub_parts = []
            if institution:
                sub_parts.append(escape(institution))
            if year:
                sub_parts.append(escape(year))
            if sub_parts:
                story.append(Paragraph(" | ".join(sub_parts), st["company"]))

    certs = [c for c in (resume.get("certifications") or []) if c and c.strip()]
    if certs:
        story += _section_header("Certifications", st)
        items = [
            ListItem(Paragraph(escape(c), st["bullet"]), leftIndent=10)
            for c in certs
        ]
        story.append(
            ListFlowable(
                items, bulletType="bullet", start="-", leftIndent=10,
                bulletFontSize=10,
            )
        )

    return story


def build_pdf(resume: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
        title=f"{resume.get('name', 'Resume')} - Resume",
        author=resume.get("name", ""),
    )
    doc.build(_build_story(resume))
    return buf.getvalue()


# Backwards-compatible name used by app.py
def html_to_pdf(html: str) -> bytes:  # noqa: ARG001
    raise NotImplementedError("Use build_pdf(resume_dict) — HTML->PDF deprecated for ATS.")


# ---------------------------------------------------------------------------
# HTML preview — same single-column ATS layout for browser viewing
# ---------------------------------------------------------------------------

HTML_CSS = """
body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; color: #222;
       line-height: 1.4; max-width: 720px; margin: 24px auto; padding: 0 16px; }
h1 { font-size: 20pt; margin: 0 0 2pt 0; }
.title { font-size: 12pt; color: #555; margin: 0 0 4pt 0; }
.contact { font-size: 9.5pt; color: #555; margin-bottom: 12pt; }
h2 { font-size: 11pt; margin: 14pt 0 4pt 0; padding-bottom: 2pt;
     border-bottom: 1px solid #888; text-transform: uppercase;
     letter-spacing: 0.5pt; }
.role-line { font-weight: bold; margin-top: 8pt; }
.company-line { color: #555; margin-bottom: 3pt; font-size: 10pt; }
ul { margin: 3pt 0 6pt 18pt; padding: 0; }
li { margin-bottom: 2pt; }
.skills { line-height: 1.5; }
"""


def render_html(resume: dict) -> str:
    name = escape(resume.get("name", ""))
    title = escape(resume.get("title", ""))
    contact = resume.get("contact", {}) or {}
    contact_parts = [
        escape(contact.get(k, "")) for k in ("email", "phone", "location", "linkedin", "website")
        if contact.get(k)
    ]
    contact_html = " | ".join(contact_parts)

    summary = escape(resume.get("summary", ""))
    skills = resume.get("skills", []) or []
    skills_html = ", ".join(escape(s) for s in skills)

    exp_parts = []
    for exp in resume.get("experience", []) or []:
        role = escape(exp.get("role", ""))
        company = escape(exp.get("company", ""))
        location = escape(exp.get("location", ""))
        start = escape(exp.get("start", ""))
        end = escape(exp.get("end", ""))
        bullets = exp.get("bullets", []) or []
        line2 = " | ".join(p for p in [company, location, f"{start} - {end}" if start and end else (start or end)] if p)
        bullets_html = "".join(f"<li>{escape(b)}</li>" for b in bullets)
        exp_parts.append(
            f'<div><div class="role-line">{role}</div>'
            f'<div class="company-line">{line2}</div>'
            f'<ul>{bullets_html}</ul></div>'
        )
    exp_html = "".join(exp_parts)

    edu_parts = []
    for ed in resume.get("education", []) or []:
        degree = escape(ed.get("degree", ""))
        institution = escape(ed.get("institution", ""))
        year = escape(ed.get("year", ""))
        line2 = " | ".join(p for p in [institution, year] if p)
        edu_parts.append(
            f'<div><div class="role-line">{degree}</div>'
            f'<div class="company-line">{line2}</div></div>'
        )
    edu_html = "".join(edu_parts)

    certs = resume.get("certifications", []) or []
    certs_html = ""
    if certs:
        certs_items = "".join(f"<li>{escape(c)}</li>" for c in certs)
        certs_html = f"<h2>Certifications</h2><ul>{certs_items}</ul>"

    summary_section = f"<h2>Summary</h2><div>{summary}</div>" if summary else ""
    skills_section = f'<h2>Skills</h2><div class="skills">{skills_html}</div>' if skills else ""
    exp_section = f"<h2>Professional Experience</h2>{exp_html}" if exp_html else ""
    edu_section = f"<h2>Education</h2>{edu_html}" if edu_html else ""

    return (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{name} - Resume</title><style>{HTML_CSS}</style></head><body>"
        f"<h1>{name}</h1>"
        f"<div class='title'>{title}</div>"
        f"<div class='contact'>{contact_html}</div>"
        f"{summary_section}{skills_section}{exp_section}{edu_section}{certs_html}"
        f"</body></html>"
    )
