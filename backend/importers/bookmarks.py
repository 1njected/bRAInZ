"""Chrome/Brave bookmark importer — HTML and JSON formats."""

from __future__ import annotations
import asyncio
import json
import re
from pathlib import Path
from html.parser import HTMLParser


# --- Parsers ---

class _BookmarkHTMLParser(HTMLParser):
    """Parse Chrome 'Export bookmarks' HTML (Netscape bookmark format)."""

    def __init__(self):
        super().__init__()
        self.bookmarks: list[dict] = []
        self._folder_stack: list[str] = []
        self._in_h3 = False
        self._pending_folder = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "h3":
            self._in_h3 = True
            self._pending_folder = ""
        elif tag == "a":
            href = attrs_dict.get("href", "")
            if href.startswith("http"):
                self.bookmarks.append({
                    "url": href,
                    "title": "",
                    "folder_path": "/".join(self._folder_stack),
                })
        elif tag == "dl":
            if self._pending_folder:
                self._folder_stack.append(self._pending_folder)
                self._pending_folder = ""

    def handle_endtag(self, tag):
        if tag == "h3":
            self._in_h3 = False
        elif tag == "dl" and self._folder_stack:
            self._folder_stack.pop()

    def handle_data(self, data):
        if self._in_h3:
            self._pending_folder = data.strip()
        elif self.bookmarks and not self.bookmarks[-1]["title"]:
            self.bookmarks[-1]["title"] = data.strip()


def parse_bookmarks_html(filepath: str) -> list[dict]:
    with open(filepath, encoding="utf-8") as f:
        content = f.read()
    parser = _BookmarkHTMLParser()
    parser.feed(content)
    return parser.bookmarks


def parse_bookmarks_json(filepath: str) -> list[dict]:
    """Parse a bookmarks JSON file.

    Supports two formats:
    - Chrome native: object with a "roots" key containing nested folders/urls
      (type: "folder"/"url", children: [...])
    - Directory-style: array of objects with type "DIRECTORY"/"FILE" and a "url" field
      (exported by tools like Raindrop, Obsidian web clipper, etc.)
    """
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    bookmarks: list[dict] = []

    if isinstance(data, list):
        # Directory-style format: [{type: "DIRECTORY", children: [...]}, {type: "FILE", url: ...}]
        def walk_dir(nodes, path=""):
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                node_type = node.get("type", "").upper()
                name = node.get("title") or node.get("name") or ""
                if node_type == "FILE":
                    url = node.get("url", "")
                    if url.startswith("http"):
                        bookmarks.append({"url": url, "title": name, "folder_path": path})
                elif node_type == "DIRECTORY":
                    child_path = f"{path}/{name}".lstrip("/")
                    walk_dir(node.get("children", []), child_path)

        walk_dir(data)

    else:
        # Chrome native format: {"roots": {"bookmark_bar": {...}, "other": {...}}}
        def walk_chrome(node, path=""):
            if isinstance(node, dict):
                node_type = node.get("type")
                name = node.get("name", "")
                if node_type == "url":
                    url = node.get("url", "")
                    if url.startswith("http"):
                        bookmarks.append({"url": url, "title": name, "folder_path": path})
                elif node_type == "folder":
                    child_path = f"{path}/{name}".lstrip("/")
                    for child in node.get("children", []):
                        walk_chrome(child, child_path)
            elif isinstance(node, list):
                for item in node:
                    walk_chrome(item, path)

        roots = data.get("roots", {})
        for root_name, root_node in roots.items():
            walk_chrome(root_node, root_name)

    return bookmarks


# --- Importer ---

async def import_bookmarks(
    filepath: str,
    fmt: str = "html",
    rate_limit: float | None = None,
    llm=None,
    index=None,
    data_dir=None,
    category_map: dict | None = None,
    progress=None,
) -> dict:
    """Import bookmarks from file. Returns {imported, skipped, failed}.

    progress: optional callable(n, url, status) called for each item.
    """
    from config import get_config
    if rate_limit is None:
        rate_limit = get_config().get("ingestion", {}).get("bulk_rate_limit", 1.0)

    if fmt == "html":
        items = parse_bookmarks_html(filepath)
    else:
        items = parse_bookmarks_json(filepath)

    from pipeline import ingest_url_pipeline

    imported, skipped, failed = 0, 0, 0

    for n, item in enumerate(items, 1):
        url = item["url"]
        folder = item.get("folder_path", "")

        # Skip if already in index by URL
        existing = _find_by_url(index, url)
        if existing:
            skipped += 1
            if progress:
                progress(n, url, "skip")
            continue

        # Map folder to category
        category = None
        if category_map:
            for folder_key, cat in category_map.items():
                if folder_key.lower() in folder.lower():
                    category = cat
                    break

        if progress:
            progress(n, url, "fetch")

        try:
            result = await ingest_url_pipeline(
                url=url,
                category=category,
                tags=None,
                llm=llm,
                index=index,
                data_dir=data_dir,
            )
            if result.get("duplicate"):
                skipped += 1
                if progress:
                    progress(n, url, "skip")
            else:
                imported += 1
                if progress:
                    progress(n, url, f"ok [{result['category']}] {result['title'][:50]}")
        except Exception as e:
            failed += 1
            if progress:
                progress(n, url, f"fail {type(e).__name__}: {str(e)[:60]}")
            from storage.failures import record_failure
            record_failure(data_dir, "url", url, e, category)

        await asyncio.sleep(rate_limit)

    return {"imported": imported, "skipped": skipped, "failed": failed}


def _find_by_url(index, url: str) -> str | None:
    for item_id, meta in index.all_items().items():
        if meta.get("url") == url:
            return item_id
    return None
