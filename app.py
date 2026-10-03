from __future__ import annotations

import concurrent.futures
import hmac
import json
import os
from datetime import datetime
from typing import Any

import anthropic
import streamlit as st

from europass_classic_renderer import build_pdf_classic, render_html_classic
from europass_official_renderer import build_pdf_official, render_html_official
from europass_renderer import build_pdf_europass, render_html_europass
from generator import answer_job_questions, compute_coverage, generate_cover_letter, parse_resume_to_json, refine_resume, tailor_resume
from jd_fetcher import (
    DATE_POSTED, EXPERIENCE_LEVEL, JOB_TYPE,
    fetch_jd, fetch_jd_by_id, search_linkedin_jobs,
)
from notion_client import NotionError, list_applications, publish_application
from parsers import parse_resume
from renderer import build_pdf, render_html
from storage import load_applied_local, save_applied_local, storage_path_display

st.set_page_config(
    page_title="Resume Tailor", layout="wide", initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Custom CSS theme
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header[data-testid="stHeader"] {background: transparent;}
.main .block-container {padding-top: 1rem; padding-bottom: 4rem; max-width: 1240px;}

/* Hero */
.hero {
    background: linear-gradient(135deg, #003399 0%, #1e5fcf 100%);
    color: white; padding: 26px 30px; border-radius: 14px;
    margin-bottom: 22px; box-shadow: 0 4px 24px rgba(0, 51, 153, 0.18);
}
.hero h1 {color: white !important; margin: 0; font-size: 28px; font-weight: 700; letter-spacing: -0.5px;}
.hero .tag {opacity: 0.92; margin-top: 6px; font-size: 14px; line-height: 1.5;}
.hero .badges {margin-top: 12px;}
.hero .badge {
    display: inline-block; background: rgba(255,255,255,0.18); color: white;
    padding: 4px 12px; border-radius: 20px; font-size: 12px; margin-right: 8px;
    backdrop-filter: blur(8px); border: 1px solid rgba(255,255,255,0.12);
}

/* Section heading */
.section-h {color: #003399; font-weight: 700; font-size: 17px; margin: 18px 0 10px 0;
            padding-bottom: 6px; border-bottom: 1.5px solid #E8EEF7;}

/* Job cards */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 12px !important; border-color: #E8EEF7 !important;
    transition: box-shadow 160ms ease, border-color 160ms ease;
}
[data-testid="stVerticalBlockBorderWrapper"]:hover {
    box-shadow: 0 4px 18px rgba(0, 51, 153, 0.08); border-color: #BFD2EE !important;
}

/* Score chip */
.score-chip {display: inline-block; padding: 3px 10px; border-radius: 20px;
             font-weight: 600; font-size: 12px; margin-right: 6px;}
.score-good {background: #DCFCE7; color: #14532D;}
.score-mid  {background: #FEF3C7; color: #78350F;}
.score-low  {background: #FEE2E2; color: #7F1D1D;}
.applied-badge {display: inline-block; background: #E0E7FF; color: #1E3A8A;
                padding: 3px 10px; border-radius: 20px; font-weight: 600; font-size: 12px;}
.synced-badge {display: inline-block; background: #DCFCE7; color: #14532D;
               padding: 3px 10px; border-radius: 20px; font-weight: 600; font-size: 12px;
               margin-left: 6px;}

/* Buttons */
.stButton button[kind="primary"] {
    background: #003399; border: 1px solid #003399; box-shadow: 0 2px 4px rgba(0,51,153,0.18);
}
.stButton button[kind="primary"]:hover {background: #1e5fcf; border-color: #1e5fcf;}
.stDownloadButton button[kind="primary"] {background: #003399; border-color: #003399;}
.stDownloadButton button[kind="primary"]:hover {background: #1e5fcf; border-color: #1e5fcf;}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {gap: 4px; border-bottom: 1px solid #E8EEF7;}
.stTabs [data-baseweb="tab"] {height: 42px; padding: 0 20px; background: transparent;
                              border-radius: 8px 8px 0 0; font-weight: 500;}
.stTabs [aria-selected="true"] {background: #F1F5FB; color: #003399;}

/* Metrics */
[data-testid="stMetric"] {background: #F8FAFD; padding: 14px 16px; border-radius: 10px;
                          border: 1px solid #E8EEF7;}
[data-testid="stMetricLabel"] {color: #4D4D4D; font-size: 12px; font-weight: 500;}
[data-testid="stMetricValue"] {color: #003399; font-size: 28px; font-weight: 700;}

/* Sidebar */
[data-testid="stSidebar"] {background: #FAFBFD; border-right: 1px solid #E8EEF7;}
[data-testid="stSidebar"] h3 {color: #003399; font-size: 14px; font-weight: 700;
                              text-transform: uppercase; letter-spacing: 0.5px;}

/* Login */
.login-shell {
    min-height: 70vh; display: flex; align-items: center; justify-content: center;
    background:
        radial-gradient(ellipse at top, rgba(30,95,207,0.10), transparent 60%),
        radial-gradient(ellipse at bottom right, rgba(0,51,153,0.08), transparent 60%);
    padding: 40px 16px; border-radius: 16px;
}
.login-card {
    max-width: 420px; width: 100%; margin: 0 auto;
    background: white; padding: 36px 32px 32px 32px;
    border-radius: 18px; border: 1px solid #E8EEF7;
    box-shadow: 0 16px 48px rgba(0, 51, 153, 0.12);
    text-align: center;
}
.login-icon {
    width: 64px; height: 64px; margin: 0 auto 14px auto;
    background: linear-gradient(135deg, #003399 0%, #1e5fcf 100%);
    border-radius: 16px; display: flex; align-items: center; justify-content: center;
    color: white; font-size: 30px; font-weight: 700;
    box-shadow: 0 8px 24px rgba(0,51,153,0.25);
}
.login-card h2 {color: #003399; margin: 0 0 4px 0; font-size: 24px; font-weight: 700;}
.login-card .sub {color: #4D4D4D; font-size: 13px; margin-bottom: 22px;}
.login-card .footer {color: #9CA3AF; font-size: 11.5px; margin-top: 18px;}

/* Empty state */
.empty-state {background: #F8FAFD; border: 1px dashed #BFD2EE;
              border-radius: 12px; padding: 28px; text-align: center; color: #4D4D4D;}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------
def _get_secret(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key, default)


APP_USERNAME = _get_secret("APP_USERNAME")
APP_PASSWORD = _get_secret("APP_PASSWORD")
ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY")
NOTION_TOKEN = _get_secret("NOTION_TOKEN")
NOTION_DATABASE_ID = _get_secret("NOTION_DATABASE_ID")
NOTION_ENABLED = bool(NOTION_TOKEN and NOTION_DATABASE_ID)


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------
def _check_auth() -> bool:
    if not APP_USERNAME and not APP_PASSWORD:
        return True
    if st.session_state.get("auth_ok"):
        return True

    st.markdown('<div class="login-shell">', unsafe_allow_html=True)
    col_a, col_b, col_c = st.columns([1, 1.4, 1])
    with col_b:
        st.markdown(
            """
            <div class="login-card">
                <div class="login-icon">RT</div>
                <h2>Resume Tailor</h2>
                <div class="sub">Sign in to tailor resumes against any job description</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("login_form", clear_on_submit=False):
            u = st.text_input("Username", key="login_user")
            p = st.text_input("Password", type="password", key="login_pw")
            submitted = st.form_submit_button(
                "Sign in", type="primary", use_container_width=True,
            )
        if submitted:
            ok_user = hmac.compare_digest(u, APP_USERNAME) if APP_USERNAME else True
            ok_pass = hmac.compare_digest(p, APP_PASSWORD) if APP_PASSWORD else True
            if ok_user and ok_pass:
                st.session_state["auth_ok"] = True
                st.rerun()
            else:
                st.error("Wrong username or password.")
        st.markdown(
            '<div class="login-card" style="margin-top:14px;padding:16px 24px;'
            'box-shadow:none;text-align:left;background:#F8FAFD;border-style:dashed;">'
            '<div style="font-size:12px;color:#4D4D4D;line-height:1.6;">'
            'Powered by Claude Opus 4.7 &middot; Two-pass ATS coverage &middot; '
            'Europass &amp; ATS-clean layouts'
            '</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()
    return False


_check_auth()


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------
st.markdown(
    """
    <div class="hero">
        <h1>Resume Tailor</h1>
        <div class="tag">
            Upload your base resume. Set your profile. Search LinkedIn or paste any JD &mdash;
            get a Europass-styled resume with verified ATS coverage in seconds.
        </div>
        <div class="badges">
            <span class="badge">Claude Opus 4.7 &amp; Sonnet 4.6</span>
            <span class="badge">Two-pass ATS coverage</span>
            <span class="badge">Europass &amp; ATS-clean</span>"""
    + ('<span class="badge">Notion synced</span>' if NOTION_ENABLED else '<span class="badge">Local applied log</span>')
    + """
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Fail fast if API key missing
# ---------------------------------------------------------------------------
if not ANTHROPIC_API_KEY:
    st.error(
        "ANTHROPIC_API_KEY is not configured. Add it to **Settings → Secrets** on "
        "Streamlit Cloud (or `.streamlit/secrets.toml` locally) as "
        "`ANTHROPIC_API_KEY = \"sk-ant-...\"` and restart."
    )
    st.stop()


# Session state init
st.session_state.setdefault("tailored", {})    # target_id -> result dict
st.session_state.setdefault("selected_jids", set())  # multi-select for batch tailoring
if "applied" not in st.session_state:
    # Hydrate applied jobs from local file on first load this session.
    # On Streamlit Cloud this file resets between deploys; Notion is the
    # authoritative cross-deploy store.
    st.session_state["applied"] = load_applied_local()
st.session_state.setdefault("profile", {
    "name": "Gohar Sharf",
    "email": "gohar_sharf@yahoo.com",
    "gender": "Male",
    "phone": "", "location": "", "address": "", "linkedin": "", "website": "",
    "nationality": "", "date_of_birth": "",
    "languages": [],   # list of {language, level, is_mother_tongue}
})
st.session_state.setdefault("qa_answers", "")
st.session_state.setdefault("li_at", "")

PHONE_BY_LOCATION: dict[str, str] = {
    "germany": "+31-683430620",
    "deutschland": "+31-683430620",
    "netherlands": "+31-683430620",
    "netherland": "+31-683430620",
    "the netherlands": "+31-683430620",
    "holland": "+31-683430620",
    "belgium": "+31-683430620",
    "belgique": "+31-683430620",
    "belgie": "+31-683430620",
    "sweden": "+46-734417702",
    "sverige": "+46-734417702",
    "poland": "+48-732143595",
    "polska": "+48-732143595",
}

def _auto_fill_phone(loc: str) -> None:
    phone = PHONE_BY_LOCATION.get(loc.strip().lower())
    if phone:
        st.session_state["profile"]["phone"] = phone

def _on_location_change():
    _auto_fill_phone(st.session_state.get("sidebar_location", ""))


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
CEFR_LEVELS = ["Native", "C2", "C1", "B2", "B1", "A2", "A1"]

with st.sidebar:
    st.markdown("### Base resume")
    upload_mode = st.radio(
        "Source", ["Upload file", "Paste text"], horizontal=True, key="upload_mode"
    )
    if upload_mode == "Upload file":
        uploaded = st.file_uploader(
            "PDF / DOCX / TXT", type=["pdf", "docx", "txt"], key="base_resume_file"
        )
        if uploaded is not None:
            try:
                st.session_state["base_resume"] = parse_resume(
                    uploaded.name, uploaded.getvalue()
                )
                st.success(f"Loaded {uploaded.name}")
            except Exception as e:
                st.error(f"Failed to parse: {e}")
    else:
        pasted = st.text_area("Paste your resume", height=220, key="base_resume_text_area")
        if pasted.strip():
            st.session_state["base_resume"] = pasted.strip()

    if st.session_state.get("base_resume"):
        with st.expander("Preview parsed resume", expanded=False):
            base = st.session_state["base_resume"]
            st.text(base[:1500] + ("..." if len(base) > 1500 else ""))

    st.markdown("---")
    st.markdown("### Your profile")
    st.caption(
        "Confirm these once — they're used verbatim in every generated resume."
    )
    profile = st.session_state["profile"]
    # Auto-fill phone on every load if location is already set and phone is empty
    if profile.get("location") and not profile.get("phone"):
        _auto_fill_phone(profile["location"])
    profile["name"] = st.text_input("Full name", value=profile["name"], placeholder="Gohar Sharf")
    profile["email"] = st.text_input("Email", value=profile["email"], placeholder="you@example.com")
    profile["location"] = st.text_input(
        "Location (city, country)", value=profile["location"],
        placeholder="Hamburg, Germany",
        key="sidebar_location", on_change=_on_location_change,
    )
    profile["phone"] = st.text_input("Phone", value=profile["phone"], placeholder="+49 151 ...")
    profile["linkedin"] = st.text_input("LinkedIn", value=profile["linkedin"],
                                        placeholder="linkedin.com/in/...")
    with st.expander("More profile fields", expanded=False):
        gender_options = ["Male", "Female", "Other"]
        gender_idx = gender_options.index(profile["gender"]) if profile.get("gender") in gender_options else 0
        profile["gender"] = st.selectbox("Gender", gender_options, index=gender_idx)
        profile["address"] = st.text_input("Address (optional)", value=profile["address"])
        profile["website"] = st.text_input("Website (optional)", value=profile["website"])
        profile["nationality"] = st.text_input("Nationality (optional)", value=profile["nationality"])
        profile["date_of_birth"] = st.text_input(
            "Date of birth (optional, DD/MM/YYYY)", value=profile["date_of_birth"]
        )

    st.markdown("**Languages**")
    if not profile["languages"]:
        # Sensible starter row so the user sees the shape
        profile["languages"] = [{"language": "English", "level": "C1", "is_mother_tongue": False}]
    new_langs: list[dict] = []
    for i, lang in enumerate(profile["languages"]):
        lc1, lc2, lc3 = st.columns([3, 2, 1])
        with lc1:
            name = st.text_input("Language", value=lang.get("language", ""),
                                 key=f"lang_name_{i}", label_visibility="collapsed")
        with lc2:
            current_level = lang.get("level", "C1")
            try:
                idx = CEFR_LEVELS.index(current_level)
            except ValueError:
                idx = 0
            level = st.selectbox("Level", CEFR_LEVELS, index=idx,
                                 key=f"lang_lvl_{i}", label_visibility="collapsed")
        with lc3:
            keep = st.checkbox("✓", value=True, key=f"lang_keep_{i}",
                               label_visibility="collapsed")
        if keep and name.strip():
            new_langs.append({
                "language": name.strip(),
                "level": level,
                "is_mother_tongue": (level == "Native"),
            })
    if st.button("+ Add language", use_container_width=True, key="add_lang"):
        new_langs.append({"language": "", "level": "B1", "is_mother_tongue": False})
        profile["languages"] = new_langs
        st.rerun()
    profile["languages"] = new_langs

    st.markdown("---")
    st.markdown("### Generation settings")
    mode = st.radio(
        "Mode",
        ["Speed (~8-15s, Haiku+Sonnet, no thinking)",
         "Quality (~45-90s, Opus 4.7 + auto-refine)"],
        index=0,
        key="gen_mode",
        help=(
            "Speed: Haiku 4.5 extracts keywords, Sonnet 4.6 generates resume, "
            "no thinking. Quality: Opus 4.7 with adaptive thinking, two-pass + "
            "auto-refine to plug missing keywords."
        ),
    )
    st.session_state["mode_value"] = "speed" if mode.startswith("Speed") else "quality"

    st.session_state["max_parallel"] = st.slider(
        "Max parallel resumes",
        min_value=1, max_value=10, value=5, step=1,
        key="max_parallel_slider",
        help=(
            "How many jobs to tailor in parallel when you use the batch button. "
            "Capped at 10 to stay under Anthropic rate limits."
        ),
    )

    output_style = st.radio(
        "Output format",
        [
            "Europass Official (matches europa.eu template)",
            "Europass Classic (two-column)",
            "Europass Modern (single-column)",
            "ATS-clean",
        ],
        index=0,
        key="output_style",
        help=(
            "Classic: full-page two-column EU layout. Modern: simple single column "
            "with EU blue accents. ATS-clean: plain single column for generic ATS."
        ),
    )

    st.markdown("---")
    st.markdown("### LinkedIn account")
    with st.expander("Connect LinkedIn (optional)", expanded=not st.session_state["li_at"]):
        st.caption(
            "Paste your `li_at` cookie to search as yourself — unlocks more jobs, "
            "better filters, and Easy Apply listings."
        )
        with st.expander("How to get your li_at cookie", expanded=False):
            st.markdown(
                "1. Open **linkedin.com** in Chrome and log in\n"
                "2. Press **F12** → Application tab → Cookies → linkedin.com\n"
                "3. Find `li_at` → copy its **Value**\n"
                "4. Paste it below"
            )
        li_at_input = st.text_input(
            "li_at cookie value", type="password",
            value=st.session_state["li_at"],
            placeholder="Paste li_at value here...",
            key="li_at_input",
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Save cookie", use_container_width=True, key="save_li_at"):
                st.session_state["li_at"] = li_at_input.strip()
                st.success("Saved — searches will now use your LinkedIn account.")
        with c2:
            if st.button("Clear", use_container_width=True, key="clear_li_at"):
                st.session_state["li_at"] = ""
                st.rerun()
        if st.session_state["li_at"]:
            st.markdown('<span class="synced-badge">LinkedIn connected</span>', unsafe_allow_html=True)

    st.markdown("---")
    if NOTION_ENABLED:
        st.markdown('<span class="synced-badge">Notion connected</span>',
                    unsafe_allow_html=True)
    else:
        st.caption(
            "Notion not configured — Applied jobs are session-only. "
            "Add `NOTION_TOKEN` + `NOTION_DATABASE_ID` to secrets to enable persistence."
        )

    if st.button("Sign out", use_container_width=True):
        st.session_state.clear()
        st.rerun()


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------
if not st.session_state.get("base_resume"):
    st.markdown(
        '<div class="empty-state"><strong>Step 1.</strong> Upload (or paste) your '
        'base resume in the sidebar to begin.</div>',
        unsafe_allow_html=True,
    )
    st.stop()

if not (st.session_state["profile"].get("phone") and st.session_state["profile"].get("location")):
    st.warning(
        "Add your **phone** and **location** in the sidebar Profile section "
        "before tailoring — they go into every generated resume."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _output_style() -> str:
    return st.session_state.get("output_style", "Europass Classic (two-column)")


def _build_pdf_and_html(resume: dict) -> tuple[bytes, str]:
    style = _output_style()
    if style.startswith("Europass Official"):
        return build_pdf_official(resume), render_html_official(resume)
    if style.startswith("Europass Classic"):
        return build_pdf_classic(resume), render_html_classic(resume)
    if style.startswith("Europass Modern"):
        return build_pdf_europass(resume), render_html_europass(resume)
    return build_pdf(resume), render_html(resume)


def _file_slug(text: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")


def _result_files(entry: dict) -> tuple[bytes, str, str, str]:
    resume = entry["resume"]
    name_slug = _file_slug(resume.get("name", "") or "Resume")
    job_title = (entry.get("job", {}).get("title") or "").strip()
    title_slug = _file_slug(job_title) if job_title else ""
    fname_base = f"{name_slug}_{title_slug}" if title_slug else name_slug
    pdf_bytes, html_str = _build_pdf_and_html(resume)
    json_str = json.dumps(resume, indent=2)
    return pdf_bytes, html_str, json_str, fname_base


def _score_chip(pct: int) -> str:
    cls = "score-good" if pct >= 80 else ("score-mid" if pct >= 60 else "score-low")
    return f'<span class="score-chip {cls}">{pct}%</span>'


def _profile_override() -> dict:
    p = st.session_state["profile"]
    override = {
        "contact": {
            "email": p.get("email", ""), "phone": p["phone"],
            "location": p["location"], "address": p["address"],
            "linkedin": p["linkedin"], "website": p["website"],
            "nationality": p["nationality"], "date_of_birth": p["date_of_birth"],
            "gender": p.get("gender", "Male"),
        },
        "languages": p["languages"],
    }
    if p.get("name", "").strip():
        override["name"] = p["name"].strip()
    return override


def _language_warning(required: list[str], profile_langs: list[dict]) -> str:
    """Return HTML warning if any required language has no profile entry."""
    if not required:
        return ""
    profile_names = {l.get("language", "").lower() for l in profile_langs}
    missing = [r for r in required if r.lower() not in profile_names]
    if not missing:
        return ""
    return (
        f"<div style='background:#FEF3C7;border-left:3px solid #F59E0B;"
        f"padding:10px 14px;border-radius:6px;margin:8px 0;font-size:13px;'>"
        f"<strong>JD requires {', '.join(missing)}.</strong> Add your level in the "
        f"sidebar Profile → Languages section so it appears on the resume."
        f"</div>"
    )


def _publish_to_notion(entry: dict, target_id: str) -> tuple[bool, str]:
    if not NOTION_ENABLED:
        return False, "Notion not configured."
    job = entry.get("job", {})
    # Generate the PDF in the user's currently-selected style for attachment
    try:
        pdf_bytes, _ = _build_pdf_and_html(entry["resume"])
    except Exception as e:
        pdf_bytes = None
        st.warning(f"PDF generation failed; publishing without attachment: {e}")
    try:
        page = publish_application(
            NOTION_TOKEN, NOTION_DATABASE_ID,
            role=job.get("title", "") or "Tailored resume",
            company=job.get("company", "") or "",
            location=job.get("location", "") or "",
            jd_text=entry.get("jd", ""),
            resume_json=entry["resume"],
            resume_pdf=pdf_bytes,
            jd_url=job.get("url", ""),
            coverage_pct=entry["coverage"]["composite_pct"],
        )
        return True, page.get("url", "")
    except NotionError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Unexpected error: {e}"


def _mark_applied(target_id: str):
    entry = st.session_state["tailored"].get(target_id)
    if not entry:
        return
    record = {
        "target_id": target_id,
        "applied_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "role": entry.get("job", {}).get("title", ""),
        "company": entry.get("job", {}).get("company", ""),
        "url": entry.get("job", {}).get("url", ""),
        "coverage_pct": entry["coverage"]["composite_pct"],
        "notion_url": "",
        "notion_error": "",
    }
    if NOTION_ENABLED:
        ok, msg = _publish_to_notion(entry, target_id)
        if ok:
            record["notion_url"] = msg
        else:
            record["notion_error"] = msg
    st.session_state["applied"][target_id] = record
    # Persist to local file so the entry survives sign-out and app restart
    save_applied_local(st.session_state["applied"])


def _render_download_and_apply(entry: dict, key_prefix: str, target_id: str):
    pdf_bytes, html_str, json_str, fname_base = _result_files(entry)
    is_applied = target_id in st.session_state["applied"]
    cover_letter = entry.get("cover_letter", "")

    # Row 1 — resume downloads
    d1, d2, d3, d4 = st.columns([2, 1.5, 1.5, 2])
    with d1:
        st.download_button(
            "Download PDF", data=pdf_bytes, file_name=f"{fname_base}.pdf",
            mime="application/pdf", key=f"{key_prefix}_pdf", type="primary",
            use_container_width=True,
        )
    with d2:
        st.download_button(
            "HTML", data=html_str, file_name=f"{fname_base}.html",
            mime="text/html", key=f"{key_prefix}_html", use_container_width=True,
        )
    with d3:
        st.download_button(
            "JSON", data=json_str, file_name=f"{fname_base}.json",
            mime="application/json", key=f"{key_prefix}_json", use_container_width=True,
        )
    with d4:
        if is_applied:
            rec = st.session_state["applied"][target_id]
            badge = '<span class="applied-badge">Applied</span>'
            if rec.get("notion_url"):
                badge += f' <a href="{rec["notion_url"]}" target="_blank" style="text-decoration:none;"><span class="synced-badge">Notion ✓</span></a>'
            st.markdown(badge, unsafe_allow_html=True)
            if rec.get("notion_error"):
                st.caption(f"Notion error: {rec['notion_error'][:80]}")
        else:
            if st.button("Mark as Applied", key=f"{key_prefix}_apply",
                         use_container_width=True):
                _mark_applied(target_id)
                st.rerun()

    # Row 2 — cover letter
    if cover_letter:
        cl1, cl2 = st.columns([3, 1])
        with cl1:
            with st.expander("Cover letter preview", expanded=False):
                st.text(cover_letter)
        with cl2:
            st.download_button(
                "Cover Letter (.txt)", data=cover_letter,
                file_name=f"{fname_base}__cover_letter.txt",
                mime="text/plain", key=f"{key_prefix}_cl", use_container_width=True,
            )


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_search, tab_linkedin, tab_direct, tab_qa, tab_applied = st.tabs(
    [
        " Search LinkedIn jobs ",
        " Tailor from LinkedIn URL ",
        " Tailor against any JD ",
        " Answer Job Questions ",
        f" Applied jobs ({len(st.session_state['applied'])}) ",
    ]
)


# ===========================================================================
# Mode 1 — Search LinkedIn
# ===========================================================================
with tab_search:
    from jd_fetcher import EUROPE_COUNTRIES

    sc1, sc2 = st.columns([3, 1])
    with sc1:
        kw = st.text_input("Job title / keywords", value="data engineer", key="search_kw",
                           placeholder="e.g. data engineer, python developer")
    with sc2:
        limit = st.number_input("Max results", min_value=5, max_value=100, value=25, step=5,
                                key="search_limit")

    country_labels = [c[0] for c in EUROPE_COUNTRIES]
    country_keys   = [c[1] for c in EUROPE_COUNTRIES]
    saved_country  = st.session_state.get("search_country_idx", 0)
    country_idx    = st.radio(
        "Region / country (remote jobs)",
        options=range(len(country_labels)),
        format_func=lambda i: country_labels[i],
        index=saved_country,
        horizontal=True,
        key="search_country_radio",
    )
    st.session_state["search_country_idx"] = country_idx
    selected_country_key = country_keys[country_idx]

    f1, f2, f3, f4 = st.columns(4)
    with f1:
        include_hybrid = st.checkbox("Include hybrid", value=False, key="search_hybrid")
        wp_types = ["remote", "hybrid"] if include_hybrid else ["remote"]
    with f2:
        date_posted_label = st.selectbox(
            "Date posted", list(DATE_POSTED.keys()), index=0, key="search_date"
        )
    with f3:
        exp_label = st.selectbox(
            "Experience level", list(EXPERIENCE_LEVEL.keys()), index=0, key="search_exp"
        )
    with f4:
        jt_label = st.selectbox(
            "Job type", list(JOB_TYPE.keys()), index=0, key="search_jt"
        )

    li_at = st.session_state.get("li_at", "")
    if li_at:
        st.caption("Searching as your LinkedIn account (authenticated).")
    else:
        st.caption("Searching as guest. Connect LinkedIn in the sidebar for better results.")

    if st.button("Search jobs", type="primary", use_container_width=True, key="search_btn"):
        try:
            with st.spinner(f"Searching LinkedIn — {country_labels[country_idx]}..."):
                st.session_state["jobs"] = search_linkedin_jobs(
                    keywords=kw,
                    location=selected_country_key,
                    workplace_types=wp_types,
                    date_posted=DATE_POSTED[date_posted_label],
                    experience_level=EXPERIENCE_LEVEL[exp_label],
                    job_type=JOB_TYPE[jt_label],
                    limit=int(limit),
                    li_at=li_at,
                )
                st.session_state.pop("active_target_id", None)
        except Exception as e:
            st.error(
                f"Search failed: {e}\n\n"
                "Try a simpler query, wait a minute, or paste the JD directly."
            )

    jobs = st.session_state.get("jobs", [])
    if jobs:
        tailored = st.session_state["tailored"]
        selected_jids = st.session_state["selected_jids"]
        untailored_ids = [j["id"] for j in jobs if j["id"] not in tailored]
        n_sel = sum(1 for jid in selected_jids if jid in untailored_ids)

        st.markdown(f'<div class="section-h">{len(jobs)} jobs found '
                    f'<span style="color:#4D4D4D;font-size:13px">'
                    f'({len(untailored_ids)} untailored, {n_sel} selected)</span>'
                    f'</div>', unsafe_allow_html=True)

        # Bulk action toolbar
        tb1, tb2, tb3 = st.columns([2, 2, 6])
        with tb1:
            if st.button("Select all untailored", key="select_all",
                         use_container_width=True, disabled=not untailored_ids):
                st.session_state["selected_jids"] = set(untailored_ids)
                st.rerun()
        with tb2:
            if st.button("Clear selection", key="clear_sel",
                         use_container_width=True, disabled=n_sel == 0):
                st.session_state["selected_jids"] = set()
                st.rerun()
        with tb3:
            max_p = st.session_state.get("max_parallel", 5)
            if n_sel > 0 and st.button(
                f"Tailor {n_sel} selected in parallel (up to {max_p} at a time)",
                key="tailor_batch", type="primary", use_container_width=True,
            ):
                st.session_state["pending_batch"] = [
                    jid for jid in selected_jids if jid in untailored_ids
                ]
                st.session_state["selected_jids"] = set()

        for job in jobs:
            jid = job["id"]
            is_done = jid in tailored
            with st.container(border=True):
                top_l, top_mid, top_r = st.columns([0.4, 5.6, 2])
                with top_l:
                    if not is_done:
                        checked = st.checkbox(
                            "select", value=jid in selected_jids,
                            key=f"sel_{jid}", label_visibility="collapsed",
                        )
                        if checked:
                            st.session_state["selected_jids"].add(jid)
                        else:
                            st.session_state["selected_jids"].discard(jid)
                    else:
                        st.markdown("✓")
                with top_mid:
                    title = job["title"] or "(untitled)"
                    company = job["company"] or "(unknown)"
                    st.markdown(f"#### {title}")
                    st.markdown(f"**{company}**")
                    meta_bits = [
                        job.get("location", ""),
                        f"Posted {job['posted']}" if job.get("posted") else "",
                        f"[View on LinkedIn]({job['url']})" if job.get("url") else "",
                    ]
                    st.caption(" · ".join(b for b in meta_bits if b))
                with top_r:
                    if not is_done:
                        if st.button("Tailor", key=f"tailor_{jid}", type="primary",
                                     use_container_width=True):
                            st.session_state["pending_job"] = job
                    else:
                        cov = tailored[jid]["coverage"]
                        st.markdown(
                            _score_chip(cov["composite_pct"])
                            + f' <span style="color:#4D4D4D;font-size:12px">required '
                              f'{cov["required_hits"]}/{cov["required_total"]}</span>',
                            unsafe_allow_html=True,
                        )

                if is_done:
                    entry = tailored[jid]
                    warn = _language_warning(
                        entry["keywords"].get("required_languages", []),
                        st.session_state["profile"]["languages"],
                    )
                    if warn:
                        st.markdown(warn, unsafe_allow_html=True)
                    _render_download_and_apply(entry, key_prefix=f"dl_{jid}", target_id=jid)
                    if st.button("View / refine details", key=f"view_{jid}",
                                 use_container_width=True):
                        st.session_state["active_target_id"] = jid

    pending = st.session_state.pop("pending_job", None)
    if pending:
        try:
            with st.status(
                f"Tailoring for '{pending['title']}'...", expanded=True
            ) as status:
                status.write("Fetching JD from LinkedIn...")
                jd_text = fetch_jd_by_id(pending["id"])
                result = tailor_resume(
                    st.session_state["base_resume"], jd_text,
                    api_key=ANTHROPIC_API_KEY,
                    mode=st.session_state.get("mode_value", "speed"),
                    profile_override=_profile_override(),
                    job_title=pending.get("title", ""),
                    company=pending.get("company", ""),
                    progress_cb=status.write,
                )
                status.update(label="Tailored", state="complete", expanded=False)
            st.session_state["tailored"][pending["id"]] = {
                **result, "jd": jd_text, "job": pending,
            }
            st.session_state["active_target_id"] = pending["id"]
            st.rerun()
        except Exception as e:
            st.error(f"Tailoring failed: {e}")

    # ---- Batch parallel processing ----
    pending_batch = st.session_state.pop("pending_batch", None)
    if pending_batch:
        max_p = st.session_state.get("max_parallel", 5)
        # Snapshot what we need so worker threads don't touch st.session_state
        base_resume = st.session_state["base_resume"]
        mode = st.session_state.get("mode_value", "speed")
        profile = _profile_override()
        jobs_by_id = {j["id"]: j for j in jobs}

        def _tailor_one(jid: str):
            job = jobs_by_id[jid]
            jd_text = fetch_jd_by_id(jid)
            result = tailor_resume(
                base_resume, jd_text,
                api_key=ANTHROPIC_API_KEY,
                mode=mode,
                profile_override=profile,
                job_title=job.get("title", ""),
                company=job.get("company", ""),
            )
            return jid, jd_text, job, result

        results_count = 0
        errors: list[tuple[str, str]] = []
        total = len(pending_batch)
        with st.status(
            f"Tailoring {total} jobs in parallel (max {max_p} at a time)...",
            expanded=True,
        ) as status:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_p) as ex:
                futures = {ex.submit(_tailor_one, jid): jid for jid in pending_batch}
                for fut in concurrent.futures.as_completed(futures):
                    jid = futures[fut]
                    try:
                        jid_done, jd, job, result = fut.result()
                        st.session_state["tailored"][jid_done] = {
                            **result, "jd": jd, "job": job,
                        }
                        results_count += 1
                        title = job.get("title", "?")
                        cov = result["coverage"]["composite_pct"]
                        status.write(
                            f"✓ ({results_count}/{total}) {title} — coverage {cov}%"
                        )
                    except Exception as e:
                        title = jobs_by_id.get(jid, {}).get("title", jid)
                        errors.append((title, str(e)))
                        status.write(f"✗ {title} — {e}")
            label = f"Done: {results_count}/{total}"
            if errors:
                label += f" ({len(errors)} failed)"
            status.update(label=label, state="complete",
                          expanded=bool(errors))
        if errors:
            for title, err in errors:
                st.error(f"{title}: {err}")
        st.rerun()


# ===========================================================================
# Mode 2 — Tailor from LinkedIn URL
# ===========================================================================
with tab_linkedin:
    st.markdown(
        '<div class="section-h">Paste a LinkedIn job URL and tailor your resume to it</div>',
        unsafe_allow_html=True,
    )
    st.caption("Copy the job URL from LinkedIn (e.g. https://www.linkedin.com/jobs/view/1234567890) and paste it below.")

    li_url = st.text_input(
        "LinkedIn job URL",
        key="li_url",
        placeholder="https://www.linkedin.com/jobs/view/...",
    )

    li_instructions = st.text_area(
        "Tailoring instructions (optional)",
        height=120,
        key="li_instructions",
        placeholder=(
            "Examples:\n"
            "• Emphasise my Python and AWS experience\n"
            "• I have no SAP experience — do not mention it\n"
            "• Keep the summary under 3 sentences"
        ),
    )

    if st.button("Fetch & Tailor", type="primary", use_container_width=True, key="li_go"):
        if not li_url.strip():
            st.error("Paste a LinkedIn job URL first.")
        else:
            try:
                with st.status("Working...", expanded=True) as status:
                    status.write("Fetching job description from LinkedIn...")
                    jd_text = fetch_jd(li_url.strip())
                    status.write("Job description fetched. Tailoring resume...")
                    result = tailor_resume(
                        st.session_state["base_resume"], jd_text,
                        api_key=ANTHROPIC_API_KEY,
                        mode=st.session_state.get("mode_value", "speed"),
                        profile_override=_profile_override(),
                        custom_instructions=li_instructions.strip() or None,
                        progress_cb=status.write,
                    )
                    status.update(label="Done — resume + cover letter ready!", state="complete", expanded=False)
                target_id = f"li_{abs(hash(li_url.strip())) % 10_000_000}"
                st.session_state["tailored"][target_id] = {
                    **result, "jd": jd_text,
                    "job": {
                        "id": target_id,
                        "title": result["keywords"].get("job_title", "(LinkedIn job)"),
                        "company": "",
                        "location": "", "posted": "",
                        "url": li_url.strip(),
                    },
                }
                st.session_state["active_target_id"] = target_id
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")

    li_entries = [
        (tid, e) for tid, e in st.session_state["tailored"].items()
        if tid.startswith("li_")
    ]
    if li_entries:
        for target_id, entry in reversed(li_entries):
            with st.container(border=True):
                st.markdown(f"#### {entry['job'].get('title') or '(LinkedIn job)'}")
                job_url = entry["job"].get("url", "")
                if job_url:
                    st.caption(f"[View original posting]({job_url})")
                cov = entry["coverage"]
                st.markdown(
                    _score_chip(cov["composite_pct"])
                    + f' <span style="color:#4D4D4D;font-size:12px">required '
                      f'{cov["required_hits"]}/{cov["required_total"]}</span>',
                    unsafe_allow_html=True,
                )
                _render_download_and_apply(entry, key_prefix=f"dl_{target_id}", target_id=target_id)
                if st.button("View / refine details", key=f"view_{target_id}", use_container_width=True):
                    st.session_state["active_target_id"] = target_id


# ===========================================================================
# Mode 3 — Tailor against any JD
# ===========================================================================
with tab_direct:

    # --- Box 1: Job description ---
    st.markdown(
        '<div class="section-h">1. Job description (copy from email or any source)</div>',
        unsafe_allow_html=True,
    )
    st.caption("Paste the full job description you received — email, PDF, company website, anywhere.")
    direct_text = st.text_area(
        "Job description",
        height=280,
        key="direct_text",
        label_visibility="collapsed",
        placeholder=(
            "Paste the full job description here...\n\n"
            "Include everything: title, required skills, responsibilities, nice-to-haves.\n"
            "The more detail you paste, the better the keyword coverage on your resume."
        ),
    )
    meta1, meta2 = st.columns(2)
    with meta1:
        role_hint = st.text_input(
            "Role / title (optional, used in filename)",
            key="direct_role", placeholder="e.g. Senior Data Engineer",
        )
    with meta2:
        company_hint = st.text_input(
            "Company (optional, used in filename)",
            key="direct_company", placeholder="e.g. Acme Corp",
        )

    st.markdown("---")

    # --- Box 2: Custom tailoring instructions ---
    st.markdown(
        '<div class="section-h">2. Tailoring instructions (optional)</div>',
        unsafe_allow_html=True,
    )
    st.caption("Tell Claude what to focus on, what to skip, or how to present your experience.")
    custom_instructions = st.text_area(
        "Tailoring instructions",
        height=160,
        key="direct_instructions",
        label_visibility="collapsed",
        placeholder=(
            "Examples:\n"
            "• Emphasise my Python and AWS experience, downplay the management roles\n"
            "• I have no SAP experience — do not mention or invent it\n"
            "• Keep the summary under 3 sentences and make it sound senior\n"
            "• Highlight my fintech domain work in every bullet point\n"
            "• This role is in the Netherlands so use the Dutch phone number"
        ),
    )

    st.markdown("---")

    if st.button("Tailor my resume", type="primary", use_container_width=True, key="direct_go"):
        jd = direct_text.strip()
        if not jd:
            st.error("Paste a job description above first.")
        else:
            try:
                with st.status("Tailoring...", expanded=True) as status:
                    result = tailor_resume(
                        st.session_state["base_resume"], jd,
                        api_key=ANTHROPIC_API_KEY,
                        mode=st.session_state.get("mode_value", "speed"),
                        profile_override=_profile_override(),
                        custom_instructions=custom_instructions.strip() or None,
                        job_title=role_hint.strip(),
                        company=company_hint.strip(),
                        progress_cb=status.write,
                    )
                    status.update(label="Done — resume + cover letter ready!", state="complete", expanded=False)
                target_id = f"direct_{abs(hash(jd)) % 10_000_000}"
                st.session_state["tailored"][target_id] = {
                    **result, "jd": jd,
                    "job": {
                        "id": target_id,
                        "title": role_hint or "(direct JD)",
                        "company": company_hint or "",
                        "location": "", "posted": "", "url": "",
                    },
                }
                st.session_state["active_target_id"] = target_id
            except Exception as e:
                st.error(f"Tailoring failed: {e}")

    direct_entries = [
        (tid, e) for tid, e in st.session_state["tailored"].items()
        if tid.startswith("direct_")
    ]
    if direct_entries:
        for target_id, entry in reversed(direct_entries):
            with st.container(border=True):
                st.markdown(f"#### {entry['job'].get('title') or '(direct JD)'}")
                if entry["job"].get("company"):
                    st.markdown(f"**{entry['job']['company']}**")
                cov = entry["coverage"]
                st.markdown(
                    _score_chip(cov["composite_pct"])
                    + f' <span style="color:#4D4D4D;font-size:12px">required '
                      f'{cov["required_hits"]}/{cov["required_total"]}</span>',
                    unsafe_allow_html=True,
                )
                warn = _language_warning(
                    entry["keywords"].get("required_languages", []),
                    st.session_state["profile"]["languages"],
                )
                if warn:
                    st.markdown(warn, unsafe_allow_html=True)
                _render_download_and_apply(entry, key_prefix=f"dl_{target_id}",
                                           target_id=target_id)
                if st.button("View / refine details", key=f"view_{target_id}",
                             use_container_width=True):
                    st.session_state["active_target_id"] = target_id


# ===========================================================================
# Mode — Answer Job Questions
# ===========================================================================
with tab_qa:
    st.markdown(
        '<div class="section-h">Answer job application questions using your resume</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Paste the questions from the job application or email. "
        "Claude will answer each one based on your resume."
    )

    qa_questions = st.text_area(
        "Questions",
        height=220,
        key="qa_questions",
        label_visibility="collapsed",
        placeholder=(
            "Paste all the questions here, one per line or numbered. Examples:\n\n"
            "1. How many years of experience do you have with Python?\n"
            "2. Have you worked in an Agile environment?\n"
            "3. Describe a time you improved a data pipeline.\n"
            "4. Are you open to relocation?"
        ),
    )

    qa_jd = st.text_area(
        "Job description for context (optional but recommended)",
        height=140,
        key="qa_jd",
        placeholder="Paste the job description here so answers are aligned to this specific role...",
    )

    if st.button("Generate answers", type="primary", use_container_width=True, key="qa_go"):
        if not qa_questions.strip():
            st.error("Paste at least one question first.")
        elif not st.session_state.get("base_resume"):
            st.error("Upload your resume in the sidebar first.")
        else:
            try:
                with st.spinner("Generating answers from your resume..."):
                    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                    answers = answer_job_questions(
                        resume=st.session_state["base_resume"],
                        questions=qa_questions.strip(),
                        client=client,
                        jd_text=qa_jd.strip(),
                        model="claude-sonnet-4-6",
                    )
                st.session_state["qa_answers"] = answers
            except Exception as e:
                st.error(f"Failed: {e}")

    if st.session_state.get("qa_answers"):
        answers = st.session_state["qa_answers"]
        st.markdown("---")
        st.markdown('<div class="section-h">Answers</div>', unsafe_allow_html=True)
        st.text_area("", value=answers, height=400, key="qa_output", label_visibility="collapsed")
        st.download_button(
            "Download answers (.txt)", data=answers,
            file_name="job_application_answers.txt",
            mime="text/plain", use_container_width=True, key="qa_download",
        )


# ===========================================================================
# Mode — Applied jobs
# ===========================================================================
with tab_applied:
    # Persistence status
    if NOTION_ENABLED:
        st.markdown(
            'Persistence: <span class="synced-badge">Notion (permanent)</span> '
            '+ <span class="applied-badge">local cache</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            'Persistence: <span class="applied-badge">local file</span> only. '
            f'<span style="color:#4D4D4D;font-size:12px">({storage_path_display()})</span>',
            unsafe_allow_html=True,
        )
        st.caption(
            "Local-file persistence works on your own machine. On Streamlit Cloud the "
            "filesystem resets on each deploy — for cloud-safe permanence, add "
            "NOTION_TOKEN + NOTION_DATABASE_ID to secrets."
        )

    qcol, rcol = st.columns([4, 1])
    with qcol:
        q = st.text_input("Search by role, company, or JD content",
                          key="applied_search",
                          placeholder="e.g. Snowflake, Berlin, Acme")
    with rcol:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        if NOTION_ENABLED and st.button("Refresh from Notion",
                                        use_container_width=True,
                                        key="refresh_notion"):
            st.rerun()

    # Local entries (session + file, since session is hydrated from file)
    local_entries = list(st.session_state["applied"].values())
    if q.strip():
        ql = q.lower()
        local_entries = [
            r for r in local_entries
            if ql in (
                (r.get("role") or "") + " "
                + (r.get("company") or "") + " "
                + (r.get("url") or "")
            ).lower()
        ]
    local_entries = sorted(local_entries, key=lambda r: r.get("applied_at", ""),
                            reverse=True)

    # Build set of (role, company, applied_date) keys so we can dedupe Notion
    # entries that came from this client.
    local_keys = set()
    for r in local_entries:
        local_keys.add((
            (r.get("role") or "").strip().lower(),
            (r.get("company") or "").strip().lower(),
        ))

    if local_entries:
        st.markdown(
            '<div class="section-h">Your applications</div>', unsafe_allow_html=True
        )
        for rec in local_entries:
            with st.container(border=True):
                c1, c2 = st.columns([5, 2])
                with c1:
                    st.markdown(f"#### {rec.get('role') or '(no role)'}")
                    st.markdown(f"**{rec.get('company') or '—'}**")
                    bits = [
                        f"Applied {rec.get('applied_at','')[:10]}" if rec.get("applied_at") else "",
                        f"Coverage {rec.get('coverage_pct', '?')}%",
                        f"[Original JD]({rec['url']})" if rec.get("url") else "",
                    ]
                    st.caption(" · ".join(b for b in bits if b))
                with c2:
                    if rec.get("notion_url"):
                        st.markdown(
                            f'<a href="{rec["notion_url"]}" target="_blank" '
                            f'style="text-decoration:none;">'
                            f'<span class="synced-badge">View in Notion ↗</span></a>',
                            unsafe_allow_html=True,
                        )
                    elif rec.get("notion_error"):
                        st.caption(f"Notion: {rec['notion_error'][:80]}")
                    if st.button("Remove", key=f"unapply_{rec.get('target_id')}",
                                 use_container_width=True):
                        st.session_state["applied"].pop(rec.get("target_id"), None)
                        save_applied_local(st.session_state["applied"])
                        st.rerun()

    # Notion-side entries that aren't already shown above
    if NOTION_ENABLED:
        st.markdown('<div class="section-h">From Notion (older sessions)</div>',
                    unsafe_allow_html=True)
        try:
            with st.spinner("Loading from Notion..."):
                notion_results = list_applications(NOTION_TOKEN, NOTION_DATABASE_ID,
                                                   query=q)
            # Dedupe: skip Notion entries whose title looks like a local one we
            # already showed (since publishing creates a title "Role @ Company").
            filtered_notion = []
            for r in notion_results:
                title = r.get("title", "").lower()
                is_dup = any(
                    (key[0] in title and key[1] in title)
                    for key in local_keys if key[0] and key[1]
                )
                if not is_dup:
                    filtered_notion.append(r)

            if not filtered_notion:
                st.caption("No additional Notion entries.")
            for r in filtered_notion:
                with st.container(border=True):
                    c1, c2 = st.columns([5, 2])
                    with c1:
                        st.markdown(f"**{r['title']}**")
                        when = r.get("applied_at_iso", "")
                        if when:
                            st.caption(f"Applied {when[:10]}")
                    with c2:
                        if r.get("url"):
                            st.markdown(
                                f'<a href="{r["url"]}" target="_blank" '
                                f'style="text-decoration:none;">'
                                f'<span class="synced-badge">Open in Notion ↗</span></a>',
                                unsafe_allow_html=True,
                            )
        except NotionError as e:
            st.error(f"Could not load from Notion: {e}")

    if not local_entries and not NOTION_ENABLED:
        st.markdown(
            '<div class="empty-state">No applications yet. Tailor a resume, then '
            'click <strong>Mark as Applied</strong> on the result.</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Active selection — preview / refine
# ---------------------------------------------------------------------------
active_id = st.session_state.get("active_target_id")
if active_id and active_id in st.session_state["tailored"]:
    entry = st.session_state["tailored"][active_id]
    job_meta = entry.get("job", {})
    coverage = entry["coverage"]

    st.markdown('<div class="section-h">Preview / refine active selection</div>',
                unsafe_allow_html=True)
    st.markdown(
        f"**Target:** {job_meta.get('title')} @ {job_meta.get('company') or '—'}  "
        + (f"· [JD]({job_meta.get('url')})" if job_meta.get("url") else "")
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Composite coverage", f"{coverage['composite_pct']}%")
    c2.metric("Required", f"{coverage['required_pct']}%",
              f"{coverage['required_hits']}/{coverage['required_total']}")
    c3.metric("Optional", f"{coverage['optional_pct']}%",
              f"{coverage['optional_hits']}/{coverage['optional_total']}")
    if entry.get("refined"):
        st.caption("Auto-refine pass ran to plug missing required keywords.")
    if entry.get("mode") == "speed":
        st.caption("Speed mode: single Sonnet 4.6 pass. Switch to Quality mode for two-pass + auto-refine.")

    if coverage["missing_required"]:
        with st.expander(
            f"Missing required keywords ({len(coverage['missing_required'])})",
            expanded=False,
        ):
            st.code("\n".join(coverage["missing_required"]))
            if st.button("Run refinement pass", key=f"refine_{active_id}"):
                try:
                    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                    new_resume = refine_resume(
                        entry["resume"], entry["jd"],
                        coverage["missing_required"], client,
                    )
                    new_coverage = compute_coverage(new_resume, entry["keywords"])
                    st.session_state["tailored"][active_id] = {
                        **entry, "resume": new_resume,
                        "coverage": new_coverage, "refined": True,
                    }
                    st.rerun()
                except Exception as e:
                    st.error(f"Refinement failed: {e}")
    if coverage["missing_optional"]:
        with st.expander(
            f"Missing optional keywords ({len(coverage['missing_optional'])})",
            expanded=False,
        ):
            st.code("\n".join(coverage["missing_optional"]))

    t_prev, t_kw, t_json = st.tabs(["Preview", "Extracted JD keywords", "Resume JSON"])
    with t_prev:
        _, html_preview = _build_pdf_and_html(entry["resume"])
        st.components.v1.html(html_preview, height=1100, scrolling=True)
    with t_kw:
        st.json(entry["keywords"])
    with t_json:
        st.json(entry["resume"])
