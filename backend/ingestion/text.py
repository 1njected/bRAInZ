"""Plain text / note ingestion — simple pass-through."""

from __future__ import annotations


async def ingest_text(title: str, body: str) -> dict:
    """Accept a title + body and return the standard ingestion dict."""
    return {
        "title": title,
        "content_md": body,
    }
