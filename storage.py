"""Local-file persistence for applied jobs.

Writes to `data/applied.json` (gitignored). Persists across app restarts when
the filesystem is durable (local dev). On Streamlit Cloud the FS resets between
deploys, so for true cross-session persistence on Cloud use Notion (see
notion_client.py).

Override the directory via env var `RESUME_TAILOR_DATA_DIR` if you want it
somewhere else (e.g. a mounted volume).
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _storage_dir() -> Path:
    return Path(os.environ.get("RESUME_TAILOR_DATA_DIR", "data"))


def _storage_file() -> Path:
    return _storage_dir() / "applied.json"


def load_applied_local() -> dict[str, dict]:
    """Return a dict[target_id] -> applied record. Empty if no file."""
    p = _storage_file()
    if not p.exists():
        return {}
    try:
        content = p.read_text()
        data = json.loads(content) if content.strip() else {}
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def save_applied_local(applied: dict[str, dict]) -> bool:
    """Persist the applied dict to disk. Silent failure on read-only FS (Cloud).

    Returns True if the write succeeded.
    """
    try:
        d = _storage_dir()
        d.mkdir(parents=True, exist_ok=True)
        _storage_file().write_text(json.dumps(applied, indent=2, default=str))
        return True
    except Exception:
        return False


def storage_path_display() -> str:
    """Return a short display string of where local storage lives."""
    try:
        return str(_storage_file().resolve())
    except Exception:
        return str(_storage_file())
