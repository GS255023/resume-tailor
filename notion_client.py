"""Notion client: publish tailored resumes with separate properties + PDF attachment.

Configuration (Streamlit secrets or env vars):
  NOTION_TOKEN        — integration token starting with 'secret_...' or 'ntn_...'
  NOTION_DATABASE_ID  — UUID of the database to publish into

Auto-detected database columns (case-insensitive, optional — populated only if
present in your DB):
  Title            -> required (the title column, any name)
  Company          -> rich_text or title
  Location         -> rich_text
  Role             -> rich_text
  Status           -> select        (set to "Applied")
  Date applied     -> date          (today, ISO date)
  Coverage         -> number        (e.g. 92)
  JD URL           -> url
  Resume PDF       -> files         (attached PDF)
  PDF / Attachment -> files         (alias names also accepted)

PDF attachment: uses Notion file_uploads API (v2026-03-11). Free workspaces are
limited to 5 MiB per file; a typical resume is well under 200 KB.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import requests

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"  # required for file_uploads endpoint


class NotionError(RuntimeError):
    pass


def _headers(token: str, *, json_content: bool = True) -> dict:
    h = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }
    if json_content:
        h["Content-Type"] = "application/json"
    return h


def _chunks(text: str, size: int = 1900) -> list[str]:
    if not text:
        return []
    return [text[i:i + size] for i in range(0, len(text), size)]


def _text_block(text: str) -> dict:
    return {
        "object": "block", "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _h2(text: str) -> dict:
    return {
        "object": "block", "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _code(text: str, language: str = "json") -> dict:
    return {
        "object": "block", "type": "code",
        "code": {
            "rich_text": [{"type": "text", "text": {"content": text[:1900]}}],
            "language": language,
        },
    }


def _file_block(file_upload_id: str, name: str) -> dict:
    """A PDF embedded in the page body using a Notion file_upload id."""
    return {
        "object": "block", "type": "file",
        "file": {
            "type": "file_upload",
            "file_upload": {"id": file_upload_id},
            "name": name,
        },
    }


# ---------------------------------------------------------------------------
# Database schema introspection
#
# Notion API v2025-09-03+ moved per-column properties off the database object
# onto a "data source" inside it. The new flow:
#   GET /v1/databases/{id}     -> {data_sources: [{id, name}, ...]}
#   GET /v1/data_sources/{id}  -> {properties: {...}}
# Older versions returned properties directly on the database response.
# We try data_sources first; fall back to the legacy shape for older versions.
# ---------------------------------------------------------------------------
_DATA_SOURCE_CACHE: dict[str, str] = {}  # database_id -> data_source_id


def _http_get(url: str, token: str) -> requests.Response:
    return requests.get(url, headers=_headers(token), timeout=15)


def _check_db_error(resp: requests.Response, what: str = "database") -> None:
    if resp.status_code == 404:
        raise NotionError(
            f"Notion returned 404 for {what}. The {what} is NOT shared with your "
            "integration. Fix: open the database in notion.so (not the public "
            "notion.site URL) -> click the ... menu (top right) -> 'Connections' "
            "-> 'Add connections' -> select your integration. Then click Mark "
            "as Applied again."
        )
    if resp.status_code == 401:
        raise NotionError(
            "Notion returned 401. The NOTION_TOKEN is invalid or expired. Create "
            "a new token at notion.so/profile/integrations and update Streamlit secrets."
        )
    if resp.status_code != 200:
        raise NotionError(
            f"Failed to read {what}: HTTP {resp.status_code} {resp.text[:300]}"
        )


def _resolve_data_source_id(database_id: str, token: str) -> str | None:
    """Look up the primary data source ID for a database. None if the API
    response doesn't include data_sources (older API contract)."""
    if database_id in _DATA_SOURCE_CACHE:
        return _DATA_SOURCE_CACHE[database_id]
    resp = _http_get(f"{NOTION_API_BASE}/databases/{database_id}", token)
    _check_db_error(resp, "database")
    body = resp.json()
    sources = body.get("data_sources") or []
    if sources:
        ds_id = sources[0].get("id")
        if ds_id:
            _DATA_SOURCE_CACHE[database_id] = ds_id
            return ds_id
    return None  # older API; properties are on the database object itself


def _read_db_schema(database_id: str, token: str) -> dict[str, str]:
    """Returns {property_name: property_type}."""
    # New API model: properties live on the data source.
    ds_id = _resolve_data_source_id(database_id, token)
    if ds_id:
        resp = _http_get(f"{NOTION_API_BASE}/data_sources/{ds_id}", token)
        _check_db_error(resp, "data source")
        props = resp.json().get("properties", {})
        return {name: (spec.get("type") or "") for name, spec in props.items()}

    # Fallback: older API where properties live on the database object.
    resp = _http_get(f"{NOTION_API_BASE}/databases/{database_id}", token)
    _check_db_error(resp, "database")
    props = resp.json().get("properties", {})
    return {name: (spec.get("type") or "") for name, spec in props.items()}


def _find_title_column(schema: dict[str, str]) -> str:
    for name, ptype in schema.items():
        if ptype == "title":
            return name
    # Diagnostic: show what we actually got so the user can see the shape
    props_summary = ", ".join(f"{n}({t})" for n, t in schema.items())
    raise NotionError(
        f"No title column found. The DB has these columns: "
        f"{props_summary or '(none returned by the API)'}. "
        "Every Notion database has exactly one title column by definition, so "
        "this usually means the URL points to a PAGE that contains a database "
        "(not the database itself) — use the inline database's own URL."
    )


def _build_properties(
    schema: dict[str, str],
    *,
    title: str,
    fields: dict[str, Any],
) -> dict:
    """Build a Notion properties payload using whatever columns exist in the DB.

    `fields` is a dict of {column_name: value}; column names are matched
    case-insensitively against the DB schema. Values are coerced to the
    column's Notion type.
    """
    out: dict[str, Any] = {}

    title_col = _find_title_column(schema)
    out[title_col] = {
        "title": [{"type": "text", "text": {"content": (title or "")[:2000]}}]
    }

    # Case-insensitive lookup so "Company" / "company" / "COMPANY" all match
    schema_ci = {n.lower(): (n, t) for n, t in schema.items()}

    for desired_name, value in fields.items():
        match = schema_ci.get(desired_name.lower())
        if not match:
            continue
        real_name, ptype = match
        if real_name == title_col:
            continue  # already set
        if value is None or (isinstance(value, str) and not value.strip()):
            continue

        if ptype == "rich_text":
            out[real_name] = {
                "rich_text": [{"type": "text", "text": {"content": str(value)[:2000]}}]
            }
        elif ptype == "url":
            url = str(value).strip()
            if url:
                out[real_name] = {"url": url}
        elif ptype == "select":
            out[real_name] = {"select": {"name": str(value)[:100]}}
        elif ptype == "multi_select":
            opts = value if isinstance(value, list) else [value]
            out[real_name] = {
                "multi_select": [{"name": str(o)[:100]} for o in opts if o]
            }
        elif ptype == "number":
            try:
                out[real_name] = {"number": float(value)}
            except (TypeError, ValueError):
                pass
        elif ptype == "date":
            out[real_name] = {"date": {"start": str(value)}}
        elif ptype == "files":
            # value must be a file_upload id (string)
            if isinstance(value, str) and value:
                out[real_name] = {
                    "files": [{
                        "type": "file_upload",
                        "file_upload": {"id": value},
                        "name": "resume.pdf",
                    }]
                }
        elif ptype == "email":
            out[real_name] = {"email": str(value)}
        elif ptype == "phone_number":
            out[real_name] = {"phone_number": str(value)}
    return out


# ---------------------------------------------------------------------------
# File upload (PDF attachment)
# ---------------------------------------------------------------------------
def upload_file(
    token: str, filename: str, content: bytes,
    content_type: str = "application/pdf",
) -> str:
    """Two-step Notion file upload. Returns the file_upload id."""
    # Step 1: create file_upload object
    r1 = requests.post(
        f"{NOTION_API_BASE}/file_uploads",
        headers=_headers(token),
        json={
            "mode": "single_part",
            "filename": filename,
            "content_type": content_type,
        },
        timeout=20,
    )
    if r1.status_code >= 300:
        raise NotionError(
            f"File upload step 1 (/v1/file_uploads) failed: "
            f"HTTP {r1.status_code} {r1.text[:300]}"
        )
    body = r1.json()
    upload_id = body.get("id")
    if not upload_id:
        raise NotionError(f"file_upload created but no id returned: {body}")

    # Step 2: send file content via multipart/form-data
    r2 = requests.post(
        f"{NOTION_API_BASE}/file_uploads/{upload_id}/send",
        headers=_headers(token, json_content=False),
        files={"file": (filename, content, content_type)},
        timeout=120,
    )
    if r2.status_code >= 300:
        raise NotionError(
            f"File upload step 2 (send) failed: "
            f"HTTP {r2.status_code} {r2.text[:300]}"
        )
    return upload_id


# ---------------------------------------------------------------------------
# Publish + List
# ---------------------------------------------------------------------------
def publish_application(
    token: str,
    database_id: str,
    *,
    role: str,
    company: str,
    location: str = "",
    jd_text: str = "",
    resume_json: dict | None = None,
    resume_pdf: bytes | None = None,
    jd_url: str = "",
    coverage_pct: int | None = None,
) -> dict:
    """Create a Notion page with separate properties + JD + JSON + attached PDF.

    Returns the Notion page object (includes `url`).
    """
    schema = _read_db_schema(database_id, token)

    # Upload the PDF first (so we can reference it both in properties and body).
    file_upload_id: str | None = None
    upload_error: str = ""
    if resume_pdf:
        safe_company = (company or "company").replace(" ", "_").replace("/", "-")
        safe_role = (role or "resume").replace(" ", "_").replace("/", "-")
        filename = f"{safe_role}__{safe_company}.pdf"
        try:
            file_upload_id = upload_file(token, filename, resume_pdf)
        except NotionError as e:
            upload_error = str(e)

    title = f"{role} @ {company}".strip(" @").strip() or "Tailored resume"

    properties = _build_properties(
        schema,
        title=title,
        fields={
            "Company": company,
            "Role": role,
            "Position": role,                # alias
            "Job title": role,               # alias
            "Location": location,
            "City": location,                # alias
            "Status": "Applied",
            "Date applied": datetime.utcnow().date().isoformat(),
            "Date Applied": datetime.utcnow().date().isoformat(),
            "Applied at": datetime.utcnow().date().isoformat(),
            "Date": datetime.utcnow().date().isoformat(),
            "Coverage": coverage_pct,
            "Coverage %": coverage_pct,
            "ATS score": coverage_pct,
            "JD URL": jd_url,
            "JD": jd_url,                    # alias
            "URL": jd_url,
            "Link": jd_url,
            "Resume PDF": file_upload_id,
            "PDF": file_upload_id,
            "Resume": file_upload_id,
            "Attachment": file_upload_id,
            "Files": file_upload_id,
        },
    )

    # Build the page body
    children: list[dict] = []
    children.append(_text_block(
        f"Applied at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    ))
    meta_bits = []
    if company:
        meta_bits.append(f"Company: {company}")
    if location:
        meta_bits.append(f"Location: {location}")
    if coverage_pct is not None:
        meta_bits.append(f"Coverage at submission: {coverage_pct}%")
    if jd_url:
        meta_bits.append(f"JD URL: {jd_url}")
    if meta_bits:
        children.append(_text_block(" | ".join(meta_bits)))

    if file_upload_id:
        children.append(_h2("Tailored resume (PDF)"))
        children.append(_file_block(file_upload_id, "resume.pdf"))
    elif upload_error:
        children.append(_text_block(f"PDF upload failed: {upload_error}"))

    if jd_text:
        children.append(_h2("Job description"))
        for chunk in _chunks(jd_text):
            children.append(_text_block(chunk))

    if resume_json is not None:
        children.append(_h2("Tailored resume (JSON — regenerate PDF anytime)"))
        children.append(_code(json.dumps(resume_json, indent=2), language="json"))

    body = {
        "parent": {"database_id": database_id},
        "properties": properties,
        "children": children,
    }

    resp = requests.post(
        f"{NOTION_API_BASE}/pages",
        headers=_headers(token), json=body, timeout=30,
    )
    if resp.status_code >= 300:
        raise NotionError(
            f"Failed to create page: HTTP {resp.status_code} {resp.text[:400]}"
        )
    return resp.json()


def list_applications(token: str, database_id: str, query: str = "") -> list[dict]:
    """Return [{id, url, title, applied_at_iso}] from the DB, newest first."""
    payload: dict[str, Any] = {
        "page_size": 100,
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    }
    if query.strip():
        schema = _read_db_schema(database_id, token)
        title_col = _find_title_column(schema)
        payload["filter"] = {
            "property": title_col,
            "title": {"contains": query.strip()},
        }

    # New API: query the data source. Fall back to legacy database query.
    ds_id = _resolve_data_source_id(database_id, token)
    if ds_id:
        url = f"{NOTION_API_BASE}/data_sources/{ds_id}/query"
    else:
        url = f"{NOTION_API_BASE}/databases/{database_id}/query"
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=20)
    if resp.status_code != 200:
        raise NotionError(
            f"Failed to query database: HTTP {resp.status_code} {resp.text[:300]}"
        )

    results: list[dict] = []
    for page in resp.json().get("results", []):
        title = ""
        for prop in page.get("properties", {}).values():
            if prop.get("type") == "title":
                texts = prop.get("title", []) or []
                title = "".join(t.get("plain_text", "") for t in texts)
                break
        results.append({
            "id": page.get("id", ""),
            "url": page.get("url", ""),
            "title": title or "(untitled)",
            "applied_at_iso": page.get("created_time", ""),
        })
    return results
