"""Generate and manage Digest pages from library item content."""

from __future__ import annotations
import json
import re
from pathlib import Path

from utils import slug, now_iso

SYSTEM_PROMPT = """You are a technical knowledge base editor. Convert the provided source article into a concise, self-contained digest reference page in GitHub Markdown format.

Guidelines:
- Write a clear # Title heading (first line, always)
- Use ## sections for: Overview, Key Concepts, Commands & Tools, Notes
- Preserve ALL important code blocks, commands, and tool invocations verbatim in fenced code blocks with language tags
- Keep it concise — this is a reference page, not a full article reproduction
- Include a ## References section at the end with the source title
- After the References section, on the very last line, add a suggested path comment

The last line of your response must be exactly this format (no trailing whitespace):
<!-- suggested_path: {category}/{slug} -->

Where {category} is one of the security knowledge domains (appsec, redteam, blueteam, forensics, malware, netsec, cloud, osint, reversing, misc, etc.) and {slug} is a short kebab-case topic identifier.

Respond with ONLY the markdown content. No preamble, no explanation."""


def _parse_suggested_path(content: str) -> tuple[str, str]:
    """Extract suggested_path from the last comment line. Returns (category, slug)."""
    match = re.search(r'<!--\s*suggested_path:\s*([^/\s]+)/([^\s>]+)\s*-->', content)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return "misc", "untitled"


def _extract_title(content: str) -> str:
    """Extract title from first # heading."""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return "Untitled"


def _load_sidecar(sidecar_path: Path) -> dict:
    if sidecar_path.exists():
        return json.loads(sidecar_path.read_text(encoding="utf-8"))
    return {}


def _save_page(data_dir: Path, category: str, page_slug: str, content: str, meta: dict) -> None:
    page_dir = data_dir / "digest" / category
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / f"{page_slug}.md").write_text(content, encoding="utf-8")
    (page_dir / f"{page_slug}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def generate_digest_page(
    item_id: str,
    item_title: str,
    item_content: str,
    item_category: str,
    item_url: str | None,
    llm,
    data_dir: Path,
    initial_tags: list[str] | None = None,
) -> dict:
    """Generate a digest page from item content. Returns DigestPageDetail-compatible dict."""
    if not item_content.strip():
        raise ValueError("Item has no content to generate a digest page from")

    # Truncate content to avoid exceeding context — keep most important parts
    max_chars = 12000
    content_for_prompt = item_content[:max_chars]
    if len(item_content) > max_chars:
        content_for_prompt += f"\n\n[... content truncated at {max_chars} chars ...]"

    prompt = (
        f"Source article title: {item_title}\n"
        f"Source category: {item_category}\n\n"
        f"Article content:\n\n{content_for_prompt}"
    )

    generated = await llm.complete(SYSTEM_PROMPT, prompt, max_tokens=4096)
    generated = generated.strip()

    # Parse LLM output
    category, page_slug = _parse_suggested_path(generated)
    title = _extract_title(generated)

    # If title wasn't extracted, use item title slugified
    if title == "Untitled":
        title = item_title
        page_slug = slug(item_title, max_len=50)

    # Ensure slug is filesystem-safe
    page_slug = re.sub(r"[^\w\-]", "-", page_slug).strip("-")[:60] or slug(item_title, max_len=50)

    now = now_iso()
    page_id = f"{category}/{page_slug}"

    # Check for existing page (update it instead of duplicating)
    sidecar_path = data_dir / "digest" / category / f"{page_slug}.json"
    existing = _load_sidecar(sidecar_path)
    created = existing.get("created", now)

    # Merge initial_tags (from request) with any tags on the existing page
    existing_tags = existing.get("tags", [])
    if initial_tags:
        merged_tags = list(dict.fromkeys(
            [t.strip().lower() for t in initial_tags if t.strip()] + existing_tags
        ))
    else:
        merged_tags = existing_tags

    meta = {
        "page_id": page_id,
        "title": title,
        "category": category,
        "tags": merged_tags,
        "suggested_path": page_id,
        "source_item_id": item_id,
        "source_url": item_url,
        "created": created,
        "updated": now,
    }

    _save_page(data_dir, category, page_slug, generated, meta)

    word_count = len(generated.split())
    return {
        **meta,
        "content": generated,
        "word_count": word_count,
    }


CLASSIFY_SYSTEM_PROMPT = """You are a technical knowledge base classifier. Analyze the provided markdown page and return a single JSON object with:
- "category": one of (appsec, redteam, blueteam, forensics, malware, netsec, cloud, osint, reversing, misc)
- "slug": a short kebab-case identifier for this page (max 50 chars)
- "tags": array of 2-5 relevant lowercase tags

Respond with ONLY valid JSON. No markdown, no explanation."""


async def import_digest_page(
    title: str,
    content: str,
    source_url: str | None,
    llm,
    data_dir: Path,
) -> dict:
    """Import a markdown page as-is, using LLM only to classify/tag it."""
    if not content.strip():
        raise ValueError("Page has no content")

    max_chars = 6000
    content_preview = content[:max_chars]

    prompt = f"Title: {title}\n\nContent:\n{content_preview}"

    try:
        raw = await llm.complete(CLASSIFY_SYSTEM_PROMPT, prompt, max_tokens=256)
        raw = raw.strip()
        # Strip markdown code fences if present
        raw = re.sub(r'^```[a-z]*\n?', '', raw).rstrip('`').strip()
        import json as _json
        meta_llm = _json.loads(raw)
        category = re.sub(r"[^\w\-]", "-", str(meta_llm.get("category", "misc")).lower().strip())[:30] or "misc"
        page_slug = re.sub(r"[^\w\-]", "-", str(meta_llm.get("slug", "")).lower().strip())[:60]
        tags = [t.strip().lower() for t in (meta_llm.get("tags") or []) if t.strip()]
    except Exception:
        category = "misc"
        page_slug = ""
        tags = []

    if not page_slug:
        page_slug = slug(title, max_len=50)
    page_slug = page_slug.strip("-") or slug(title, max_len=50)

    # Ensure the stored content has the original title as # heading if missing
    stored_content = content
    if not any(line.strip().startswith("# ") for line in content.splitlines()[:5]):
        stored_content = f"# {title}\n\n{content}"

    # Append reference to source
    if source_url and source_url not in stored_content:
        stored_content = stored_content.rstrip() + f"\n\n## Reference\n\nSource: {source_url}\n"

    now = now_iso()
    page_id = f"{category}/{page_slug}"

    sidecar_path = data_dir / "digest" / category / f"{page_slug}.json"
    existing = _load_sidecar(sidecar_path)
    created = existing.get("created", now)

    meta = {
        "page_id": page_id,
        "title": title,
        "category": category,
        "tags": tags,
        "suggested_path": page_id,
        "source_item_id": None,
        "source_url": source_url,
        "created": created,
        "updated": now,
    }

    _save_page(data_dir, category, page_slug, stored_content, meta)

    return {**meta, "content": stored_content, "word_count": len(stored_content.split())}


def save_digest_page_from_item(
    item_id: str,
    item_title: str,
    item_content: str,
    item_category: str,
    item_url: str | None,
    data_dir: Path,
) -> dict:
    """Save item's raw markdown content directly as a digest page, no LLM involved."""
    category = re.sub(r"[^\w\-]", "-", item_category.lower().strip())[:30] or "misc"
    page_slug = slug(item_title, max_len=50)
    page_id = f"{category}/{page_slug}"

    stored_content = item_content
    if not any(line.strip().startswith("# ") for line in item_content.splitlines()[:5]):
        stored_content = f"# {item_title}\n\n{item_content}"
    if item_url and item_url not in stored_content:
        stored_content = stored_content.rstrip() + f"\n\n## Reference\n\nSource: {item_url}\n"

    now = now_iso()
    sidecar_path = data_dir / "digest" / category / f"{page_slug}.json"
    existing = _load_sidecar(sidecar_path)
    created = existing.get("created", now)

    meta = {
        "page_id": page_id,
        "title": item_title,
        "category": category,
        "tags": [],
        "suggested_path": page_id,
        "source_item_id": item_id,
        "source_url": item_url,
        "created": created,
        "updated": now,
    }
    _save_page(data_dir, category, page_slug, stored_content, meta)
    return {**meta, "content": stored_content, "word_count": len(stored_content.split())}


def list_digest_pages(data_dir: Path) -> list[dict]:
    """Scan digest directory and return list of page metadata dicts."""
    digest_dir = data_dir / "digest"
    if not digest_dir.exists():
        return []
    pages = []
    for sidecar in sorted(digest_dir.rglob("*.json")):
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            md_file = sidecar.with_suffix(".md")
            if md_file.exists():
                content = md_file.read_text(encoding="utf-8")
                meta["word_count"] = len(content.split())
                meta.setdefault("tags", [])
                pages.append(meta)
        except Exception:
            continue
    return pages


def get_digest_page(data_dir: Path, page_id: str) -> dict | None:
    """Load a single digest page by page_id ({category}/{slug})."""
    parts = page_id.split("/", 1)
    if len(parts) != 2:
        return None
    category, page_slug = parts
    md_path = data_dir / "digest" / category / f"{page_slug}.md"
    sidecar_path = data_dir / "digest" / category / f"{page_slug}.json"
    if not md_path.exists():
        return None
    content = md_path.read_text(encoding="utf-8")
    meta = _load_sidecar(sidecar_path)
    meta.setdefault("tags", [])
    return {
        **meta,
        "page_id": page_id,
        "content": content,
        "word_count": len(content.split()),
    }


def update_digest_page(
    data_dir: Path,
    page_id: str,
    title: str | None,
    content: str | None,
    tags: list[str] | None = None,
    category: str | None = None,
) -> dict | None:
    """Update title, content, tags, and/or category of an existing digest page.
    If category changes the files are moved to the new directory."""
    parts = page_id.split("/", 1)
    if len(parts) != 2:
        return None
    old_category, page_slug = parts
    md_path = data_dir / "digest" / old_category / f"{page_slug}.md"
    sidecar_path = data_dir / "digest" / old_category / f"{page_slug}.json"
    if not md_path.exists():
        return None

    current_content = md_path.read_text(encoding="utf-8")
    meta = _load_sidecar(sidecar_path)

    if content is not None:
        current_content = content
        meta["updated"] = now_iso()
        if title is None:
            title = _extract_title(content) or meta.get("title", "Untitled")

    if title is not None:
        meta["title"] = title
        meta["updated"] = now_iso()

    if tags is not None:
        meta["tags"] = [t.strip().lower() for t in tags if t.strip()]
        meta["updated"] = now_iso()

    meta.setdefault("tags", [])

    # Handle category change — move files
    new_category = category.strip().lower() if category and category.strip() else old_category
    if new_category != old_category:
        new_dir = data_dir / "digest" / new_category
        new_dir.mkdir(parents=True, exist_ok=True)
        new_md = new_dir / f"{page_slug}.md"
        new_sidecar = new_dir / f"{page_slug}.json"
        md_path.rename(new_md)
        sidecar_path.rename(new_sidecar)
        # Clean up empty old category dir
        try:
            (data_dir / "digest" / old_category).rmdir()
        except OSError:
            pass
        md_path = new_md
        sidecar_path = new_sidecar
        meta["category"] = new_category
        meta["page_id"] = f"{new_category}/{page_slug}"
        meta["suggested_path"] = meta["page_id"]
        meta["updated"] = now_iso()

    md_path.write_text(current_content, encoding="utf-8")
    sidecar_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        **meta,
        "content": current_content,
        "word_count": len(current_content.split()),
    }


def delete_digest_page(data_dir: Path, page_id: str) -> bool:
    """Delete a digest page and its sidecar. Returns True if deleted."""
    parts = page_id.split("/", 1)
    if len(parts) != 2:
        return False
    category, page_slug = parts
    md_path = data_dir / "digest" / category / f"{page_slug}.md"
    sidecar_path = data_dir / "digest" / category / f"{page_slug}.json"
    deleted = False
    if md_path.exists():
        md_path.unlink()
        deleted = True
    if sidecar_path.exists():
        sidecar_path.unlink()
    # Remove empty category dir
    cat_dir = data_dir / "digest" / category
    try:
        cat_dir.rmdir()  # only succeeds if empty
    except OSError:
        pass
    return deleted
