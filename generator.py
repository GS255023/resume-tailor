"""ATS-optimized resume generator.

Two modes:
  - Speed  : one Sonnet 4.6 call returning {keywords, resume} jointly. ~8-15s.
  - Quality: two Opus 4.7 calls (extract -> generate) + auto-refine. ~45-90s.

compute_coverage() measures verbatim hit rate so the UI can show an honest,
scanner-agnostic estimate; in Quality mode auto-refine fixes gaps.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import anthropic

MODEL_QUALITY = "claude-opus-4-7"
MODEL_SPEED = "claude-sonnet-4-6"
MODEL_FAST_EXTRACT = "claude-haiku-4-5"  # JD keyword extraction is simple enough for Haiku


# ===========================================================================
# Schemas
# ===========================================================================
KEYWORDS_SCHEMA = {
    "type": "object",
    "properties": {
        "job_title": {"type": "string"},
        "seniority": {"type": "string"},
        "years_required": {"type": "string"},
        "must_have_skills": {"type": "array", "items": {"type": "string"}},
        "nice_to_have_skills": {"type": "array", "items": {"type": "string"}},
        "tools_and_technologies": {"type": "array", "items": {"type": "string"}},
        "methodologies": {"type": "array", "items": {"type": "string"}},
        "soft_skills": {"type": "array", "items": {"type": "string"}},
        "certifications": {"type": "array", "items": {"type": "string"}},
        "domain_keywords": {"type": "array", "items": {"type": "string"}},
        "education_requirements": {"type": "array", "items": {"type": "string"}},
        "key_responsibilities": {"type": "array", "items": {"type": "string"}},
        "required_languages": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "job_title", "seniority", "years_required",
        "must_have_skills", "nice_to_have_skills", "tools_and_technologies",
        "methodologies", "soft_skills", "certifications", "domain_keywords",
        "education_requirements", "key_responsibilities", "required_languages",
    ],
    "additionalProperties": False,
}

RESUME_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "title": {"type": "string"},
        "contact": {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "location": {"type": "string"},
                "address": {"type": "string"},
                "linkedin": {"type": "string"},
                "website": {"type": "string"},
                "nationality": {"type": "string"},
                "date_of_birth": {"type": "string"},
                "gender": {"type": "string"},
            },
            "required": [
                "email", "phone", "location", "address",
                "linkedin", "website", "nationality", "date_of_birth", "gender",
            ],
            "additionalProperties": False,
        },
        "summary": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "role": {"type": "string"},
                    "location": {"type": "string"},
                    "sector": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["company", "role", "location", "sector", "start", "end", "bullets"],
                "additionalProperties": False,
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "degree": {"type": "string"},
                    "institution": {"type": "string"},
                    "location": {"type": "string"},
                    "year": {"type": "string"},
                },
                "required": ["degree", "institution", "location", "year"],
                "additionalProperties": False,
            },
        },
        "languages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "language": {"type": "string"},
                    "level": {"type": "string"},
                    "is_mother_tongue": {"type": "boolean"},
                },
                "required": ["language", "level", "is_mother_tongue"],
                "additionalProperties": False,
            },
        },
        "certifications": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "name", "title", "contact", "summary", "skills",
        "experience", "education", "languages", "certifications",
    ],
    "additionalProperties": False,
}


# ===========================================================================
# ASCII normalization (defensive — keeps PDF + ATS happy)
# ===========================================================================
_PUNCT_REPLACEMENTS = {
    "–": "-", "—": "-", "−": "-",  # dashes
    "‘": "'", "’": "'", "“": '"', "”": '"',  # smart quotes
    " ": " ",  # nbsp
    "…": "...",
    "→": "->",
}


def _ascii_clean(value):
    """Normalize typographic punctuation; PRESERVE accented Latin characters.

    Helvetica (WinAnsiEncoding) handles é, ä, ü, ñ, ç, ß etc. — keep them so
    Europass-style output reads naturally for European names and places.
    Only normalize dashes / smart quotes / nbsp which break ATS keyword matching.
    """
    if isinstance(value, str):
        for src, dst in _PUNCT_REPLACEMENTS.items():
            value = value.replace(src, dst)
        value = re.sub(r"[ \t]+", " ", value).strip()
        return value
    if isinstance(value, list):
        return [_ascii_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _ascii_clean(v) for k, v in value.items()}
    return value


# ===========================================================================
# Pass 1 — JD keyword extraction
# ===========================================================================
EXTRACT_SYSTEM = """You extract ATS keywords from job descriptions.

Read the JD and produce a JSON object listing EVERY keyword an ATS would scan for.
Be exhaustive — include exact phrases as they appear in the JD.

Rules:
- `must_have_skills`: hard skills explicitly listed as required ("must have", "required", "minimum").
- `nice_to_have_skills`: explicitly listed as preferred / nice-to-have / bonus.
- `tools_and_technologies`: every named product, framework, language, library, platform, cloud service, database.
- `methodologies`: Agile, Scrum, TDD, DevOps, MLOps, etc.
- `soft_skills`: communication, leadership, collaboration, etc.
- `certifications`: any certification names mentioned.
- `domain_keywords`: industry / domain terms (e.g. "fintech", "healthcare", "supply chain", "real-time analytics").
- `key_responsibilities`: 5-10 short phrases capturing what the role actually does.
- `required_languages`: human languages required or strongly preferred by the JD
  (e.g. "German", "French", "English"). Empty array if the JD doesn't specify any.
- Use EXACT casing where it matters (BigQuery, CI/CD, .NET, Node.js).
- Do not invent keywords that are not in the JD.
- Do not include duplicates or near-duplicates. If the JD says both "Data Lake" and
  "Data Lakes" and "Data Lake architecture", pick the most specific form once.

Output JSON only."""


def extract_keywords(
    jd_text: str,
    client: anthropic.Anthropic,
    model: str = MODEL_QUALITY,
    use_thinking: bool = True,
    effort: str = "high",
) -> dict:
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": 4000,
        "system": EXTRACT_SYSTEM,
        "output_config": {
            "format": {"type": "json_schema", "schema": KEYWORDS_SCHEMA},
        },
        "messages": [
            {"role": "user",
             "content": f"<JOB_DESCRIPTION>\n{jd_text}\n</JOB_DESCRIPTION>"}
        ],
    }
    if use_thinking:
        kwargs["thinking"] = {"type": "adaptive"}
    # Haiku 4.5 does not accept `effort`; only Opus 4.6+/Sonnet 4.6 do.
    if model != MODEL_FAST_EXTRACT:
        kwargs["output_config"]["effort"] = effort

    response = client.messages.create(**kwargs)
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("Keyword extraction returned no text.")
    return json.loads(text)


# ===========================================================================
# Pass 2 — Resume generation against explicit keyword list
# ===========================================================================
GENERATE_SYSTEM = """You produce ATS-optimized resumes. Target: 90+ ATS keyword coverage.

You receive:
1. The candidate's ORIGINAL_RESUME.
2. The JOB_DESCRIPTION.
3. A pre-extracted KEYWORDS object listing every term an ATS will scan for.

Your job: produce a tailored resume (valid JSON, matching the resume schema) that:

A) COVERAGE — non-negotiable
   - EVERY string in `must_have_skills`, `tools_and_technologies`, `certifications`,
     `methodologies`, and `domain_keywords` MUST appear verbatim somewhere in the
     resume JSON (skills, summary, bullets, certifications, or title — any field).
   - Match casing exactly for technical terms (BigQuery, CI/CD, .NET, Node.js).
   - Include >=80% of `nice_to_have_skills` and `soft_skills` somewhere.
   - The `title` field MUST equal the JD's `job_title` (or the closest credible variant).

B) PLACEMENT — keywords go where ATS expects them
   - `skills` array: include every must-have skill, tool/tech, certification, and methodology
     as separate entries, plus relevant items from nice-to-have.
   - `summary`: 4-5 sentences. Start with years of experience + the JD's job_title. Include
     the top 8-12 keywords by importance.
   - `experience` bullets: distribute remaining keywords across bullets so each major
     keyword appears at least twice across the whole document.

C) BULLET RULES — for ATS keyword density AND human readability
   - 5-7 bullets per role.
   - EVERY bullet starts with a strong past-tense action verb: Led, Built, Architected,
     Migrated, Designed, Reduced, Increased, Automated, Owned, Delivered, Implemented,
     Scaled, Engineered, Optimized, Launched, Streamlined.
   - NEVER start with "Responsible for", "Worked on", "Helped with", "Assisted in".
   - Each bullet contains at least ONE keyword from the KEYWORDS list.
   - Quantify wherever possible: numbers, %, $, TB/PB, team size, throughput, time saved.
     If the original resume has no metric for a bullet, add a plausible one.
   - Pattern: <Action verb> + <what> + <how / with what tech> + <measurable result>.
   - 1-2 lines per bullet.
   - Distribute JD-relevant content across MULTIPLE past companies, not just the latest role.

D) BACKBONE — keep candidate's real history
   - Use the candidate's real name, contact, companies, roles, education verbatim.
   - You may rewrite bullets, add bullets, and reorder companies' bullet emphasis — but
     do not invent companies or degrees.
   - You may add 1-2 plausible certifications from `certifications` if the candidate's
     seniority makes them credible (and add them to the `certifications` field).

E) EUROPASS FIELDS — extract from the original resume; if absent, use empty string ""
   - `contact.address`: street address if shown, else "".
   - `contact.nationality`: nationality / citizenship if shown, else "".
   - `contact.date_of_birth`: DOB if shown (format DD/MM/YYYY), else "".
   - `experience[].sector`: business / industry sector for each role (e.g. "Information Technology",
     "Banking and Finance", "Healthcare", "Consulting"). Infer if absent.
   - `education[].location`: city, country of institution if known, else "".
   - `languages`: list of {language, level, is_mother_tongue}. Extract languages from
     the original resume. `level` should be CEFR (A1, A2, B1, B2, C1, C2) for non-native
     languages, or "Native" for the mother tongue. For `is_mother_tongue`, set true for
     the candidate's first language only. If the original lists languages without CEFR
     levels, infer reasonable defaults (e.g. listed as "fluent" -> C1, "professional" ->
     B2, "basic" -> A2). If no languages are listed at all, output an empty array [].

F) FORMAT — readable both for ATS and for Europass-style layouts
   - Date format: "MM/YYYY" (e.g. "01/2020") for `experience` and `education` start/end.
     Use "Present" (capitalized) for ongoing roles.
   - LinkedIn as "linkedin.com/in/handle" (no "https://").
   - No first person ("I", "my").
   - You may use accented characters where culturally correct (e.g. "Türkiye", "Köln").
     The renderer will handle them.

Output the resume JSON only — no prose, no markdown."""


def generate_resume_impl(
    resume_text: str,
    jd_text: str,
    keywords: dict,
    client: anthropic.Anthropic,
    profile_override: dict | None = None,
    custom_instructions: str | None = None,
    model: str = MODEL_QUALITY,
    effort: str = "high",
    use_thinking: bool = True,
) -> dict:
    profile_block = ""
    if profile_override:
        profile_block = (
            f"\n<PROFILE_OVERRIDE>\n{json.dumps(profile_override, indent=2)}\n"
            "</PROFILE_OVERRIDE>\n"
            "Use these values verbatim for contact and languages — they reflect the candidate's "
            "confirmed current details and override anything in the original resume. "
            "If 'name' is present in PROFILE_OVERRIDE, use it exactly as the resume 'name' field. "
            "If 'contact.email' is present, use it exactly — do NOT change, guess, or infer "
            "the candidate's name or email from anywhere else.\n"
        )
    instructions_block = ""
    if custom_instructions:
        instructions_block = (
            f"\n<CANDIDATE_INSTRUCTIONS>\n{custom_instructions}\n</CANDIDATE_INSTRUCTIONS>\n"
            "Follow the CANDIDATE_INSTRUCTIONS above. They take priority over default style "
            "guidance but must not violate the keyword coverage or backbone rules.\n"
        )
    user = (
        f"<ORIGINAL_RESUME>\n{resume_text}\n</ORIGINAL_RESUME>\n\n"
        f"<JOB_DESCRIPTION>\n{jd_text}\n</JOB_DESCRIPTION>\n\n"
        f"<KEYWORDS>\n{json.dumps(keywords, indent=2)}\n</KEYWORDS>\n"
        f"{profile_block}"
        f"{instructions_block}\n"
        "Produce the resume JSON. Cover every required keyword verbatim."
    )
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": 16000,
        "system": GENERATE_SYSTEM,
        "output_config": {
            "format": {"type": "json_schema", "schema": RESUME_SCHEMA},
            "effort": effort,
        },
        "messages": [{"role": "user", "content": user}],
    }
    if use_thinking:
        kwargs["thinking"] = {"type": "adaptive"}

    response = client.messages.create(**kwargs)
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("Resume generation returned no text.")
    return _normalize_resume(_dedupe_skills(_ascii_clean(json.loads(text))))


# ---------------------------------------------------------------------------
# Speed mode — two separate Sonnet calls (combined schema is too big for
# Sonnet's structured-output grammar compiler; splitting keeps it under the limit)
# ---------------------------------------------------------------------------
def generate_speed(
    resume_text: str,
    jd_text: str,
    client: anthropic.Anthropic,
    profile_override: dict | None = None,
    custom_instructions: str | None = None,
    progress_cb=None,
) -> dict:
    """Fast two-call flow:
        1. Haiku 4.5 extracts keywords (~2-4s, no thinking)
        2. Sonnet 4.6 generates resume (~5-12s, no thinking, medium effort)
    """
    def _emit(msg: str):
        if progress_cb:
            progress_cb(msg)

    _emit("Extracting JD keywords (Haiku 4.5)...")
    keywords = extract_keywords(
        jd_text, client,
        model=MODEL_FAST_EXTRACT, use_thinking=False,
    )
    _emit("Writing tailored resume (Sonnet 4.6)...")
    resume = generate_resume_impl(
        resume_text, jd_text, keywords, client,
        profile_override=profile_override,
        custom_instructions=custom_instructions,
        model=MODEL_SPEED, effort="medium", use_thinking=False,
    )
    return {"keywords": keywords, "resume": resume}


# ---------------------------------------------------------------------------
# Skill dedupe — kills "Data Lake / Data Lakes / Data Lake architecture" noise
# ---------------------------------------------------------------------------
def _dedupe_skills(resume: dict) -> dict:
    """Remove near-duplicate skill entries (case-insensitive, plural-insensitive).

    Heuristic: collapse entries whose normalized form (lowercased, trailing-s
    stripped, punctuation stripped) is already present. Keeps the LONGEST form
    when duplicates collide (so 'Data Lake architecture' beats 'Data Lake').
    """
    raw = resume.get("skills") or []
    if not raw:
        return resume

    def _norm(s: str) -> str:
        s = s.lower().strip()
        s = re.sub(r"[^a-z0-9+# ]+", "", s)
        s = re.sub(r"\s+", " ", s).strip()
        # Strip trailing 's' for simple plural collapse (lakes -> lake, systems -> system).
        # Don't touch "-ss" (e.g. "ross") and don't try to handle "-es"/"-ies" — that
        # turns "lakes" into "lak". Single-s coverage is what matters for tech skills.
        if s.endswith("s") and not s.endswith("ss"):
            s = s[:-1]
        return s

    best: dict[str, str] = {}  # norm -> longest original form
    order: list[str] = []      # normalized form, insertion order
    for item in raw:
        if not item or not item.strip():
            continue
        key = _norm(item)
        if not key:
            continue
        if key in best:
            # keep the longer one (more specific phrase)
            if len(item) > len(best[key]):
                best[key] = item.strip()
        else:
            best[key] = item.strip()
            order.append(key)

    resume["skills"] = [best[k] for k in order]
    return resume


# ===========================================================================
# Coverage scorer
# ===========================================================================
def _resume_haystack(resume: dict) -> str:
    """Flatten the resume to one lowercase searchable string."""
    parts: list[str] = [
        resume.get("title", ""),
        resume.get("summary", ""),
        " ".join(resume.get("skills", []) or []),
        " ".join(resume.get("certifications", []) or []),
    ]
    for exp in resume.get("experience", []) or []:
        parts.append(exp.get("role", ""))
        parts.append(exp.get("company", ""))
        parts.extend(exp.get("bullets", []) or [])
    return " || ".join(parts).lower()


def _kw_present(keyword: str, haystack: str) -> bool:
    kw = keyword.lower().strip()
    if not kw:
        return False
    # Word-boundary match where possible. For terms with special chars (CI/CD, .NET,
    # Node.js) we fall back to substring match.
    if re.search(r"^[a-z0-9 +#\-]+$", kw):
        pattern = r"\b" + re.escape(kw) + r"\b"
        return bool(re.search(pattern, haystack))
    return kw in haystack


def compute_coverage(resume: dict, keywords: dict) -> dict:
    haystack = _resume_haystack(resume)

    required_buckets = {
        "must_have_skills": keywords.get("must_have_skills", []) or [],
        "tools_and_technologies": keywords.get("tools_and_technologies", []) or [],
        "methodologies": keywords.get("methodologies", []) or [],
        "certifications": keywords.get("certifications", []) or [],
        "domain_keywords": keywords.get("domain_keywords", []) or [],
    }
    optional_buckets = {
        "nice_to_have_skills": keywords.get("nice_to_have_skills", []) or [],
        "soft_skills": keywords.get("soft_skills", []) or [],
    }

    def _score(bucket: dict) -> tuple[int, int, list[str]]:
        total = 0
        hits = 0
        missing: list[str] = []
        for items in bucket.values():
            for kw in items:
                total += 1
                if _kw_present(kw, haystack):
                    hits += 1
                else:
                    missing.append(kw)
        return hits, total, missing

    req_hits, req_total, req_missing = _score(required_buckets)
    opt_hits, opt_total, opt_missing = _score(optional_buckets)

    req_pct = round(100 * req_hits / req_total) if req_total else 100
    opt_pct = round(100 * opt_hits / opt_total) if opt_total else 100

    # Composite score: 80% weight on required, 20% on optional
    composite = round(0.8 * req_pct + 0.2 * opt_pct)

    return {
        "composite_pct": composite,
        "required_pct": req_pct,
        "optional_pct": opt_pct,
        "required_hits": req_hits,
        "required_total": req_total,
        "optional_hits": opt_hits,
        "optional_total": opt_total,
        "missing_required": req_missing,
        "missing_optional": opt_missing,
    }


# ===========================================================================
# Optional pass 3 — refine to plug missing keywords
# ===========================================================================
REFINE_SYSTEM = """You are revising an already-tailored resume to cover MISSING keywords.

You receive:
1. The current RESUME JSON.
2. The original JOB_DESCRIPTION.
3. A list of MISSING_KEYWORDS that must now appear in the resume.

Modify the resume to incorporate every missing keyword:
- Add them to `skills` if they belong there.
- Weave them into existing bullets, or add new bullets, naturally — preserve the
  bullet rules (action verb start, quantified, JD-aligned, 1-2 lines).
- Do NOT remove existing keywords.
- Do NOT change name, contact, education, or company history.
- Keep ASCII-only, same date format.

Output the full updated resume JSON only."""


def refine_resume(
    resume: dict,
    jd_text: str,
    missing: list[str],
    client: anthropic.Anthropic,
) -> dict:
    if not missing:
        return resume
    user = (
        f"<RESUME>\n{json.dumps(resume, indent=2)}\n</RESUME>\n\n"
        f"<JOB_DESCRIPTION>\n{jd_text}\n</JOB_DESCRIPTION>\n\n"
        f"<MISSING_KEYWORDS>\n{json.dumps(missing)}\n</MISSING_KEYWORDS>\n\n"
        "Return the updated resume JSON. Every missing keyword must now appear."
    )
    response = client.messages.create(
        model=MODEL_QUALITY,
        max_tokens=16000,
        system=REFINE_SYSTEM,
        thinking={"type": "adaptive"},
        output_config={
            "format": {"type": "json_schema", "schema": RESUME_SCHEMA},
            "effort": "high",
        },
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("Refinement returned no text.")
    return _normalize_resume(_ascii_clean(json.loads(text)))


# ===========================================================================
# Resume parser — plain text -> structured JSON (no tailoring)
# ===========================================================================
PARSE_SYSTEM = """You convert a plain-text resume into structured JSON.

Extract all information exactly as it appears — do NOT rewrite, improve, or add anything.
Preserve the candidate's real companies, dates, roles, bullets, education, and contact details verbatim.

Rules:
- `name`: full name from the resume.
- `title`: current or most recent job title.
- `contact`: extract email, phone, location, linkedin, website, address, nationality, date_of_birth.
  Use "" for any field not present.
- `summary`: professional summary / objective if present, else "".
- `skills`: list every skill exactly as written.
- `experience`: each role as {company, role, location, sector, start, end, bullets}.
  Dates as "MM/YYYY" or "Present". Infer sector from context.
- `education`: {degree, institution, location, year}.
- `languages`: {language, level, is_mother_tongue}. Use CEFR levels where inferrable.
- `certifications`: list of certification strings.
- `contact.gender`: "" unless stated.

Output the JSON only — no prose, no markdown."""


def _normalize_resume(resume: dict) -> dict:
    """Ensure every field is a clean string — guards renderers against None / bad types."""
    def _s(v) -> str:
        return str(v).strip() if v is not None else ""

    contact = resume.get("contact") or {}
    for k in ["email", "phone", "location", "address", "linkedin",
               "website", "nationality", "date_of_birth", "gender"]:
        contact[k] = _s(contact.get(k))
    resume["contact"] = contact

    resume["name"]    = _s(resume.get("name"))
    resume["title"]   = _s(resume.get("title"))
    resume["summary"] = _s(resume.get("summary"))
    resume["skills"]  = [_s(s) for s in (resume.get("skills") or []) if s]
    resume["certifications"] = [_s(c) for c in (resume.get("certifications") or []) if c]
    resume["languages"] = [
        {
            "language":       _s(l.get("language")),
            "level":          _s(l.get("level")),
            "is_mother_tongue": bool(l.get("is_mother_tongue")),
        }
        for l in (resume.get("languages") or [])
    ]

    clean_exp = []
    for exp in resume.get("experience") or []:
        clean_exp.append({
            "company":  _s(exp.get("company")),
            "role":     _s(exp.get("role")),
            "location": _s(exp.get("location")),
            "sector":   _s(exp.get("sector")),
            "start":    _s(exp.get("start")),
            "end":      _s(exp.get("end")),
            "bullets":  [_s(b) for b in (exp.get("bullets") or []) if b],
        })
    resume["experience"] = clean_exp

    clean_edu = []
    for ed in resume.get("education") or []:
        clean_edu.append({
            "degree":      _s(ed.get("degree")),
            "institution": _s(ed.get("institution")),
            "location":    _s(ed.get("location")),
            "year":        _s(ed.get("year")),
        })
    resume["education"] = clean_edu

    return resume


def parse_resume_to_json(
    resume_text: str,
    client: anthropic.Anthropic,
    profile_override: dict | None = None,
) -> dict:
    """Convert plain-text resume to structured JSON without any tailoring."""
    profile_block = ""
    if profile_override:
        profile_block = (
            f"\n<PROFILE_OVERRIDE>\n{json.dumps(profile_override, indent=2)}\n"
            "</PROFILE_OVERRIDE>\n"
            "Use these values verbatim for contact fields — they override anything in the resume.\n"
        )
    user = (
        f"<RESUME>\n{resume_text}\n</RESUME>\n"
        f"{profile_block}\n"
        "Convert this resume to structured JSON now."
    )
    response = client.messages.create(
        model=MODEL_SPEED,
        max_tokens=8000,
        system=PARSE_SYSTEM,
        output_config={
            "format": {"type": "json_schema", "schema": RESUME_SCHEMA},
            "effort": "medium",
        },
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("Resume parsing returned no text.")
    return _normalize_resume(_ascii_clean(json.loads(text)))


# ===========================================================================
# Job application Q&A
# ===========================================================================
QA_SYSTEM = """You answer job application screening questions on behalf of a candidate.

You receive:
1. The candidate's RESUME (plain text or JSON).
2. An optional JOB_DESCRIPTION for context.
3. A list of QUESTIONS from the job application.

Rules:
- Answer every question individually. Label each answer clearly: "Q1:", "Q2:", etc.
- Base every answer strictly on the candidate's real experience in the resume.
  Do NOT invent facts, roles, companies, or achievements that are not in the resume.
- Be specific and concise. Use numbers and outcomes from the resume where relevant.
- Write in first person ("I led...", "I have X years of...").
- Keep each answer to 2-5 sentences unless the question clearly requires more.
- If the resume genuinely has no evidence for a question, say so honestly and pivot
  to the closest relevant experience ("While I haven't worked with X specifically,
  I have extensive experience with Y which covers similar ground...").
- Tone: professional, direct, confident.
- Output plain text only."""


def answer_job_questions(
    resume: str | dict,
    questions: str,
    client: anthropic.Anthropic,
    jd_text: str = "",
    model: str = MODEL_SPEED,
) -> str:
    resume_block = json.dumps(resume, indent=2) if isinstance(resume, dict) else resume
    jd_block = f"<JOB_DESCRIPTION>\n{jd_text}\n</JOB_DESCRIPTION>\n\n" if jd_text else ""
    user = (
        f"<RESUME>\n{resume_block}\n</RESUME>\n\n"
        f"{jd_block}"
        f"<QUESTIONS>\n{questions}\n</QUESTIONS>\n\n"
        "Answer every question now."
    )
    response = client.messages.create(
        model=model,
        max_tokens=3000,
        system=QA_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("Q&A generation returned no text.")
    return text


# ===========================================================================
# Cover letter generator
# ===========================================================================
COVER_LETTER_SYSTEM = """You write concise, professional cover letters that complement an ATS-optimised resume.

You receive:
1. The candidate's tailored RESUME (JSON).
2. The JOB_DESCRIPTION they are applying for.
3. Optional JOB_META (role title and company name).

Write a cover letter following these rules:
- 3 paragraphs, max 250 words total. No filler phrases.
- Paragraph 1: State the role and company, and your strongest matching credential (years of experience + domain).
- Paragraph 2: Pick 2-3 specific achievements or skills from the resume that directly address the JD's top requirements. Be concrete — use numbers where available.
- Paragraph 3: One sentence on why this company/role specifically, then a clear call to action.
- Address: "Dear Hiring Team," (unless company is known).
- Sign off: "Kind regards," followed by the candidate's full name.
- Do NOT use "I am writing to express my interest" or any cliché opener.
- Do NOT repeat the entire resume. Reference only what is most relevant.
- Output plain text only — no markdown, no bullet points."""


def generate_cover_letter(
    resume: dict,
    jd_text: str,
    client: anthropic.Anthropic,
    job_title: str = "",
    company: str = "",
    model: str = MODEL_SPEED,
) -> str:
    job_meta = ""
    if job_title or company:
        job_meta = f"<JOB_META>\nRole: {job_title}\nCompany: {company}\n</JOB_META>\n\n"

    user = (
        f"<RESUME>\n{json.dumps(resume, indent=2)}\n</RESUME>\n\n"
        f"<JOB_DESCRIPTION>\n{jd_text}\n</JOB_DESCRIPTION>\n\n"
        f"{job_meta}"
        "Write the cover letter now."
    )
    response = client.messages.create(
        model=model,
        max_tokens=1000,
        system=COVER_LETTER_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("Cover letter generation returned no text.")
    return _ascii_clean(text)


# ===========================================================================
# Public entrypoint
# ===========================================================================
def tailor_resume(
    resume_text: str,
    jd_text: str,
    api_key: str | None = None,
    mode: str = "speed",
    profile_override: dict | None = None,
    custom_instructions: str | None = None,
    auto_refine: bool = True,
    min_required_pct: int = 95,
    job_title: str = "",
    company: str = "",
    progress_cb=None,
) -> dict:
    """Tailor a resume.

    Args:
        mode: "speed"   -> Haiku extract + Sonnet generate, no thinking (~8-15s)
              "quality" -> two-pass Opus 4.7 with adaptive thinking + auto-refine (~45-90s)
        profile_override: optional dict applied verbatim to contact + languages
        progress_cb: optional callable(str) for step-by-step UI updates

    Returns:
        {keywords, resume, coverage, refined, mode}
    """
    def _emit(msg: str):
        if progress_cb:
            progress_cb(msg)

    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    refined = False

    if mode == "speed":
        out = generate_speed(
            resume_text, jd_text, client,
            profile_override=profile_override,
            custom_instructions=custom_instructions,
            progress_cb=progress_cb,
        )
        keywords = out["keywords"]
        resume = out["resume"]
        _emit("Verifying ATS coverage...")
        coverage = compute_coverage(resume, keywords)
    else:
        _emit("Extracting JD keywords (Opus 4.7, adaptive thinking)...")
        keywords = extract_keywords(jd_text, client, model=MODEL_QUALITY)
        _emit("Writing tailored resume (Opus 4.7, adaptive thinking, high effort)...")
        resume = generate_resume_impl(
            resume_text, jd_text, keywords, client,
            profile_override=profile_override,
            custom_instructions=custom_instructions,
            model=MODEL_QUALITY, effort="high",
        )
        _emit("Verifying ATS coverage...")
        coverage = compute_coverage(resume, keywords)
        if (auto_refine
                and coverage["required_pct"] < min_required_pct
                and coverage["missing_required"]):
            _emit(f"Refining ({len(coverage['missing_required'])} required keywords still missing)...")
            resume = refine_resume(resume, jd_text, coverage["missing_required"], client)
            resume = _dedupe_skills(resume)
            coverage = compute_coverage(resume, keywords)
            refined = True

    _emit("Writing cover letter...")
    cover_letter = generate_cover_letter(
        resume, jd_text, client,
        job_title=job_title, company=company,
        model=MODEL_QUALITY if mode == "quality" else MODEL_SPEED,
    )

    return {
        "keywords": keywords,
        "resume": resume,
        "coverage": coverage,
        "refined": refined,
        "mode": mode,
        "cover_letter": cover_letter,
    }


# Backwards-compatible name used by older callers
def generate_resume(resume_text: str, jd_text: str, api_key: str | None = None) -> dict:
    return tailor_resume(resume_text, jd_text, api_key=api_key)["resume"]
