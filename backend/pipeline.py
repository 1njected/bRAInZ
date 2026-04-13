"""Orchestrates the full ingest flow: fetch → extract → classify → chunk → embed → store → index."""

from __future__ import annotations
from pathlib import Path

from utils import content_hash


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _dedup_check(content_md: str, index, fallback_title: str) -> dict | None:
    """Return a duplicate response dict if content_md already exists, else None."""
    existing = index.find_by_hash(content_hash(content_md))
    if existing:
        meta = index.get(existing)
        return {
            "item_id": existing,
            "title": meta.get("title", fallback_title),
            "category": meta.get("category", "misc"),
            "tags": meta.get("tags", []),
            "duplicate": True,
        }
    return None


async def _classify_or_manual(
    title: str,
    content_md: str,
    llm,
    category: str | None,
    tags: list[str] | None,
    description: str = "",
    data_dir: Path | None = None,
    index=None,
) -> tuple[str, list[str], str, str]:
    """Return (category, tags, summary, classified_by), classifying via LLM if needed."""
    from classifier.classify import classify_content
    if not category or not tags:
        result = await classify_content(
            title, content_md, llm, description=description, data_dir=data_dir, index=index
        )
        return (
            category or result["category"],
            tags or result["tags"],
            result["summary"],
            result["classified_by"],
        )
    return category, tags, "", "manual"


# ---------------------------------------------------------------------------
# Pipeline functions
# ---------------------------------------------------------------------------

async def ingest_url_pipeline(
    url: str,
    category: str | None,
    tags: list[str] | None,
    llm,
    index,
    data_dir: Path,
    vector_index=None,
) -> dict:
    from ingestion.url import ingest_url
    from rag.embedder import embed_item
    from storage.filesystem import save_item

    extracted = await ingest_url(url)
    content_md = extracted["content_md"]
    content_llm_md = extracted.get("content_llm_md")
    title = extracted["title"]

    dup = _dedup_check(content_md, index, title)
    if dup:
        return dup

    category, tags, summary, classified_by = await _classify_or_manual(
        title, content_md, llm, category, tags,
        description=extracted.get("description", ""), data_dir=data_dir, index=index,
    )

    item_data = {
        "title": title,
        "url": url,
        "category": category,
        "tags": tags,
        "source": "api",
        "content_type": extracted.get("content_type", "url"),
        "summary": summary,
        "classified_by": classified_by,
    }

    tmp_pdf = extracted.get("tmp_pdf_path")
    try:
        item_id = await save_item(
            item_data, content_md, index, data_dir,
            snapshot_html=extracted.get("snapshot_html"),
            pub_date=extracted.get("pub_date"),
            original_file=tmp_pdf,
            original_ext=".pdf" if tmp_pdf else ".bin",
            content_llm_md=content_llm_md,
        )
    finally:
        if tmp_pdf:
            import os as _os
            _os.unlink(tmp_pdf)

    await embed_item(item_id, llm, index, data_dir, vector_index=vector_index)

    return {"item_id": item_id, "title": title, "category": category, "tags": tags, "duplicate": False}


async def ingest_pdf_pipeline(
    file_path: str,
    original_filename: str | None,
    category: str | None,
    tags: list[str] | None,
    llm,
    index,
    data_dir: Path,
    vector_index=None,
) -> dict:
    from ingestion.pdf import ingest_pdf
    from rag.embedder import embed_item
    from storage.filesystem import save_item

    extracted = await ingest_pdf(file_path, original_filename)
    content_md = extracted["content_md"]
    title = extracted["title"]

    dup = _dedup_check(content_md, index, title)
    if dup:
        return dup

    category, tags, summary, classified_by = await _classify_or_manual(
        title, content_md, llm, category, tags,
        description=extracted.get("description", ""), data_dir=data_dir, index=index,
    )

    item_data = {
        "title": title,
        "category": category,
        "tags": tags,
        "source": "api",
        "content_type": "pdf",
        "summary": summary,
        "classified_by": classified_by,
    }

    item_id = await save_item(
        item_data, content_md, index, data_dir,
        original_file=file_path, original_ext=".pdf",
        pub_date=extracted.get("pub_date"),
    )

    await embed_item(item_id, llm, index, data_dir, vector_index=vector_index)

    return {"item_id": item_id, "title": title, "category": category, "tags": tags, "duplicate": False}


async def ingest_image_pipeline(
    file_path: str,
    original_filename: str | None,
    category: str | None,
    tags: list[str] | None,
    llm,
    index,
    data_dir: Path,
    vector_index=None,
) -> dict:
    from ingestion.image import ingest_image
    from rag.embedder import embed_item
    from storage.filesystem import save_item

    extracted = await ingest_image(file_path, original_filename, llm)
    content_md = extracted["content_md"]
    title = extracted["title"]

    dup = _dedup_check(content_md, index, title)
    if dup:
        return dup

    category, tags, summary, classified_by = await _classify_or_manual(
        title, content_md, llm, category, tags, data_dir=data_dir, index=index,
    )

    item_data = {
        "title": title,
        "category": category,
        "tags": tags,
        "source": "api",
        "content_type": "image",
        "summary": summary,
        "classified_by": classified_by,
    }

    item_id = await save_item(
        item_data, content_md, index, data_dir,
        original_file=file_path, original_ext=Path(file_path).suffix or ".png",
    )

    await embed_item(item_id, llm, index, data_dir, vector_index=vector_index)

    return {"item_id": item_id, "title": title, "category": category, "tags": tags, "duplicate": False}


async def ingest_snapshot_pipeline(
    url: str,
    title: str,
    html: str,
    category: str | None,
    tags: list[str] | None,
    llm,
    index,
    data_dir: Path,
    vector_index=None,
) -> dict:
    """Ingest a pre-captured HTML snapshot sent from the browser extension."""
    import asyncio
    import concurrent.futures
    from ingestion.url import _extract_content_in_process, _extract_title, _extract_meta_in_process
    from rag.embedder import embed_item
    from storage.filesystem import save_item

    loop = asyncio.get_event_loop()
    _process_pool = concurrent.futures.ProcessPoolExecutor(max_workers=1)

    try:
        # Extract content from the provided HTML
        content_md, content_llm_md = await loop.run_in_executor(
            _process_pool, _extract_content_in_process, html
        )

        # Fall back to URL as title if extraction yields nothing and no title provided
        if not title:
            title, _, _ = await loop.run_in_executor(
                _process_pool, _extract_meta_in_process, html[:50_000], url, url
            )
    finally:
        _process_pool.shutdown(wait=False)

    if not content_md:
        content_md = f"[Snapshot of {url}]"

    if not title:
        title = url

    dup = _dedup_check(content_md, index, title)
    if dup:
        return dup

    from ingestion.dates import extract_year_from_html
    pub_date = extract_year_from_html(html[:50_000], url)

    category, tags, summary, classified_by = await _classify_or_manual(
        title, content_md, llm, category, tags,
        data_dir=data_dir, index=index,
    )

    item_data = {
        "title": title,
        "url": url,
        "category": category,
        "tags": tags,
        "source": "extension",
        "content_type": "url",
        "summary": summary,
        "classified_by": classified_by,
    }

    item_id = await save_item(
        item_data, content_md, index, data_dir,
        snapshot_html=html,
        pub_date=pub_date,
        content_llm_md=content_llm_md,
    )

    await embed_item(item_id, llm, index, data_dir, vector_index=vector_index)

    return {"item_id": item_id, "title": title, "category": category, "tags": tags, "duplicate": False}


async def ingest_text_pipeline(
    title: str,
    body: str,
    category: str | None,
    tags: list[str] | None,
    llm,
    index,
    data_dir: Path,
    vector_index=None,
    url: str | None = None,
    content_type: str = "text",
) -> dict:
    from ingestion.text import ingest_text
    from ingestion.dates import extract_year_from_text
    from rag.embedder import embed_item
    from storage.filesystem import save_item

    extracted = await ingest_text(title, body)
    content_md = extracted["content_md"]
    pub_date = extract_year_from_text(content_md)

    dup = _dedup_check(content_md, index, title)
    if dup:
        return dup

    category, tags, summary, classified_by = await _classify_or_manual(
        title, content_md, llm, category, tags, data_dir=data_dir, index=index,
    )

    item_data = {
        "title": title,
        "url": url,
        "category": category,
        "tags": tags,
        "source": "api",
        "content_type": content_type,
        "summary": summary,
        "classified_by": classified_by,
    }

    item_id = await save_item(item_data, content_md, index, data_dir, pub_date=pub_date)

    await embed_item(item_id, llm, index, data_dir, vector_index=vector_index)

    return {"item_id": item_id, "title": title, "category": category, "tags": tags, "duplicate": False}
