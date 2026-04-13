"""Filesystem operations for saving/loading/deleting items."""

from __future__ import annotations
import base64
import hashlib
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

from utils import now_iso, slug, content_hash

# Base64 blobs larger than this (in encoded chars) are extracted to separate files.
_B64_EXTRACT_THRESHOLD = 100_000  # ~75 KB decoded

_MIME_TO_EXT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/svg+xml": "svg",
    "image/webp": "webp",
    "image/avif": "avif",
    "text/css": "css",
    "application/javascript": "js",
    "font/woff": "woff",
    "font/woff2": "woff2",
    "font/ttf": "ttf",
    "application/font-woff": "woff",
    "application/font-woff2": "woff2",
}


_TEXT_ASSET_EXTS = {"css", "js", "svg", "html"}
_B64_PATTERN = re.compile(r'data:([^;"\'\s]+);base64,([A-Za-z0-9+/=]+)')


def _extract_large_base64(snapshot_html: str, item_dir: Path) -> str:
    """Extract large base64 data URIs to files in assets/ and replace with relative paths.

    After extraction, text-based assets (CSS, JS, SVG) are also scanned for nested
    base64 blobs and processed the same way, recursively.
    """
    assets_dir = item_dir / "assets"
    counters: dict[str, int] = {}
    seen: dict[str, str] = {}  # b64 prefix key -> relative path (dedup)

    def _replace_in_text(text: str, ref_prefix: str) -> str:
        """Replace large base64 URIs in *text*, writing extracted files to assets/.

        ref_prefix: the path prefix to prepend in the replacement string
                    (e.g. "assets/" from HTML root, or "" from inside assets/).
        """
        def _replace(m: re.Match) -> str:
            mime = m.group(1)
            b64data = m.group(2)
            if len(b64data) < _B64_EXTRACT_THRESHOLD:
                return m.group(0)

            key = b64data[:128]
            if key in seen:
                rel = seen[key]
                # Adjust path relative to caller
                return ref_prefix + rel.removeprefix("assets/") if ref_prefix == "" else rel

            ext = _MIME_TO_EXT.get(mime, "bin")
            counters[ext] = counters.get(ext, 0) + 1
            digest = hashlib.md5(b64data[:256].encode()).hexdigest()[:8]
            filename = f"asset_{counters[ext]}_{digest}.{ext}"

            assets_dir.mkdir(exist_ok=True)
            filepath = assets_dir / filename
            raw = base64.b64decode(b64data)
            filepath.write_bytes(raw)

            # For text-based assets, recursively process nested base64
            if ext in _TEXT_ASSET_EXTS:
                nested = _replace_in_text(raw.decode("utf-8", errors="replace"), "")
                filepath.write_text(nested, encoding="utf-8")

            rel = f"assets/{filename}"
            seen[key] = rel
            return ref_prefix + filename if ref_prefix == "" else rel

        return _B64_PATTERN.sub(_replace, text)

    return _replace_in_text(snapshot_html, "assets/")

import asyncio
import yaml



async def save_item(
    item_data: dict,
    content_md: str,
    index,
    data_dir: Path,
    original_file: str | None = None,
    original_ext: str = ".bin",
    snapshot_html: str | None = None,
    pub_date: str | None = None,
    content_llm_md: str | None = None,
) -> str:
    """Save a new item to the filesystem. Returns item_id."""
    item_id = item_data.get("id") or secrets.token_hex(4)
    category = item_data.get("category", "misc")
    title = item_data.get("title", "untitled")

    # Use publication year if available, else current year
    if pub_date and re.match(r"^\d{4}$", pub_date):
        year_prefix = pub_date
    else:
        year_prefix = datetime.now(timezone.utc).strftime("%Y")

    dir_name = f"{year_prefix}_{slug(title)}"
    item_dir = data_dir / "library" / category / dir_name

    metadata = {
        "id": item_id,
        "title": title,
        "url": item_data.get("url"),
        "category": category,
        "tags": item_data.get("tags", []),
        "added": item_data.get("added", now_iso()),
        "updated": now_iso(),
        "source": item_data.get("source", "manual"),
        "content_type": item_data.get("content_type", "text"),
        "content_hash": content_hash(content_md),
        "word_count": len(content_md.split()),
        "summary": item_data.get("summary", ""),
        "classified_by": item_data.get("classified_by", ""),
        "pub_date": pub_date,
        "has_snapshot": snapshot_html is not None,
        "has_original": original_file is not None,
        "embedded": False,
        "verified": False,
    }

    # Run all blocking file I/O in a thread pool
    def _write_files():
        item_dir.mkdir(parents=True, exist_ok=True)
        (item_dir / "content.md").write_text(content_md, encoding="utf-8")
        if content_llm_md is not None and content_llm_md != content_md:
            (item_dir / "content_llm.md").write_text(content_llm_md, encoding="utf-8")
        snap = snapshot_html
        if snap:
            snap = _extract_large_base64(snap, item_dir)
            (item_dir / "snapshot.html").write_text(snap, encoding="utf-8")
        if original_file:
            shutil.copy2(original_file, item_dir / f"original{original_ext}")
        (item_dir / "metadata.yaml").write_text(yaml.dump(metadata, allow_unicode=True), encoding="utf-8")

    await asyncio.to_thread(_write_files)

    rel_path = str(item_dir.relative_to(data_dir))
    await index.add(item_id, metadata, rel_path)

    return item_id


def load_item(item_id: str, index, data_dir: Path) -> dict | None:
    """Load item metadata + content from filesystem."""
    entry = index.get(item_id)
    if not entry:
        return None

    item_dir = data_dir / entry["path"]
    meta_file = item_dir / "metadata.yaml"
    if not meta_file.exists():
        return None

    with open(meta_file) as f:
        metadata = yaml.safe_load(f)

    llm_file = item_dir / "content_llm.md"
    content_file = item_dir / "content.md"
    preferred = llm_file if llm_file.exists() else content_file
    content = preferred.read_text(encoding="utf-8") if preferred.exists() else ""

    return {**metadata, "content": content}


async def update_item(item_id: str, updates: dict, index, data_dir: Path) -> dict | None:
    """Update item metadata. Handles category change (directory move)."""
    entry = index.get(item_id)
    if not entry:
        return None

    item_dir = data_dir / entry["path"]
    meta_file = item_dir / "metadata.yaml"
    if not meta_file.exists():
        return None

    with open(meta_file) as f:
        metadata = yaml.safe_load(f)

    new_category = updates.get("category")
    if new_category and new_category != metadata["category"]:
        # Move directory
        new_parent = data_dir / "library" / new_category
        new_parent.mkdir(parents=True, exist_ok=True)
        new_dir = new_parent / item_dir.name
        shutil.move(str(item_dir), str(new_dir))
        item_dir = new_dir
        meta_file = item_dir / "metadata.yaml"
        new_path = str(new_dir.relative_to(data_dir))
        await index.update_path(item_id, new_path, new_category)

    metadata.update({k: v for k, v in updates.items() if k not in ("id", "added")})
    metadata["updated"] = now_iso()

    meta_file.write_text(yaml.dump(metadata, allow_unicode=True), encoding="utf-8")
    await index.update_metadata(item_id, metadata)

    return metadata


async def delete_item(item_id: str, index, data_dir: Path) -> bool:
    """Delete item directory and remove from index."""
    entry = index.get(item_id)
    if not entry:
        return False

    item_dir = data_dir / entry["path"]
    if item_dir.exists():
        shutil.rmtree(item_dir)

    # Clean up embeddings
    embed_file = data_dir / "embeddings" / f"{item_id}.npz"
    if embed_file.exists():
        embed_file.unlink()

    await index.remove(item_id)
    return True
