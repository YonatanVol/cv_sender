"""CV preflight: verify it is really a PDF (magic bytes), bound its size, count
pages, hash it. A .docx or 0-byte upload must never silently become the CV that
gets attached to every application (a v1 failure mode)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .config import CV_DIR

MAX_BYTES = 15 * 1024 * 1024


class CvError(ValueError):
    pass


def save_cv(raw: bytes, original_name: str) -> dict:
    if not raw:
        raise CvError("empty file")
    if len(raw) > MAX_BYTES:
        raise CvError(f"file too large ({len(raw)} bytes, max {MAX_BYTES})")
    if raw[:5] != b"%PDF-":
        raise CvError("not a PDF (missing %PDF- header) — export your CV as PDF")

    pages = _page_count(raw)
    sha = hashlib.sha256(raw).hexdigest()
    CV_DIR.mkdir(parents=True, exist_ok=True)
    dest = CV_DIR / "cv.pdf"
    dest.write_bytes(raw)
    return {
        "cv_path": str(dest),
        "cv_sha256": sha,
        "cv_name": original_name or "cv.pdf",
        "cv_size": len(raw),
        "cv_pages": pages,
    }


def _page_count(raw: bytes) -> int | None:
    try:
        import io
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(raw)).pages)
    except Exception:
        return None
