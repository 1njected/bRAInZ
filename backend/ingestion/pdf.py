"""PDF text extraction using pymupdf (fitz)."""

from __future__ import annotations
import asyncio
import os
from pathlib import Path


async def ingest_pdf(file_path: str, original_filename: str | None = None) -> dict:
    """Extract text from a PDF. Returns {title, content_md, page_count}."""
    path = Path(file_path)

    def _extract() -> dict:
        try:
            import fitz  # pymupdf
        except ImportError:
            raise ImportError("PDF ingestion requires pymupdf: pip install pymupdf")

        doc = fitz.open(str(path))
        page_count = doc.page_count
        pages = []
        for page in doc:
            text = page.get_text("text")
            if text.strip():
                pages.append(text.strip())
        doc.close()
        return {"content_md": "\n\n".join(pages), "page_count": page_count}

    extracted = await asyncio.to_thread(_extract)
    content_md = extracted["content_md"]
    page_count = extracted["page_count"]

    # Title + description: try PDF metadata, then filename
    title, description = await asyncio.to_thread(_extract_pdf_title_and_description, file_path)
    if not title:
        title = _title_from_filename(original_filename or path.name)

    # Date: PDF metadata first, then content text fallback
    from ingestion.dates import extract_year_from_pdf_metadata, extract_year_from_text
    pub_date = (await asyncio.to_thread(extract_year_from_pdf_metadata, file_path)
                or extract_year_from_text(content_md))

    return {
        "title": title,
        "description": description,
        "content_md": content_md,
        "page_count": page_count,
        "pub_date": pub_date,
    }


def _extract_pdf_title_and_description(file_path: str) -> tuple[str | None, str]:
    """Return (title, description) from PDF metadata. Description from subject field."""
    try:
        import fitz
        doc = fitz.open(file_path)
        meta = doc.metadata
        doc.close()
        title = (meta.get("title") or "").strip() or None
        description = (meta.get("subject") or "").strip()[:300]
        return title, description
    except Exception:
        return None, ""


def _title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    # Replace underscores/hyphens with spaces, title-case
    return stem.replace("_", " ").replace("-", " ").title()
