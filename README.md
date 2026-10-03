# Resume Tailor

A local Streamlit app that takes your resume + a job description (text or LinkedIn URL) and produces a resume tailored 100% to the JD using Claude. Preview in the browser, download as PDF / HTML / JSON.

## Setup

```bash
cd /Users/farmanali/Documents/resume_creator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Run

```bash
streamlit run app.py
```

Opens at http://localhost:8501

## How it works

1. **Resume input** — upload PDF / DOCX / TXT, or paste text. PDFs are parsed with `pdfplumber`, DOCX with `python-docx`.
2. **JD input** — paste the description, or paste a public LinkedIn job URL (uses LinkedIn's `jobs-guest` endpoint; if blocked, paste the text instead).
3. **Generation** — Claude (`claude-opus-4-7`, adaptive thinking, high effort) takes both and returns structured JSON: name, contact, summary, all skills from the JD, rewritten experience bullets distributed across your real companies, education, certifications.
4. **Output** — preview in browser, download as PDF (via `xhtml2pdf`, pure Python — no system deps), HTML, or JSON.

## Files

- `app.py` — Streamlit UI
- `parsers.py` — PDF / DOCX / TXT resume parsing
- `jd_fetcher.py` — LinkedIn URL → JD text, or pass-through for pasted text
- `generator.py` — Claude API call with JSON schema
- `renderer.py` — JSON → HTML + PDF
- `requirements.txt`

## Notes

- LinkedIn aggressively blocks scrapers. The fetcher uses the public `jobs-guest` API which works for most public postings, but if it fails just open the posting, copy the description, and paste it.
- The model is instructed to spread JD-relevant content across multiple companies in your history rather than concentrating it in one role.
- API key precedence: env var `ANTHROPIC_API_KEY` first, then sidebar input.
