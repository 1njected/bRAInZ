"""In-memory item index backed by /data/index.json."""

from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from typing import Optional

import yaml


class ItemIndex:
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir  # exposed for rag/search.py chunk text lookup
        self._index_path = data_dir / "index.json"
        self._items: dict[str, dict] = {}  # item_id -> {path, ...metadata}
        self._lock = asyncio.Lock()

    async def load(self):
        """Load index.json into memory. Safe to call on startup."""
        if self._index_path.exists():
            with open(self._index_path) as f:
                self._items = json.load(f)
        else:
            self._items = {}

    def get(self, item_id: str) -> dict | None:
        return self._items.get(item_id)

    def all_items(self) -> dict[str, dict]:
        return dict(self._items)

    def find_by_hash(self, content_hash: str) -> str | None:
        for item_id, meta in self._items.items():
            if meta.get("content_hash") == content_hash:
                return item_id
        return None

    def search(
        self,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        text_query: Optional[str] = None,
    ) -> list[dict]:
        results = []
        q = text_query.lower() if text_query else None
        for item_id, meta in self._items.items():
            if category and meta.get("category") != category:
                continue
            if tag and tag not in meta.get("tags", []):
                continue
            if q:
                searchable = (
                    meta.get("title", "") + " " +
                    meta.get("summary", "") + " " +
                    " ".join(meta.get("tags", []))
                ).lower()
                if q not in searchable:
                    continue
            results.append({**meta, "id": item_id})
        return sorted(results, key=lambda x: x.get("added", ""), reverse=True)

    async def add(self, item_id: str, metadata: dict, path: str):
        entry = {
            "path": path,
            "title": metadata.get("title", ""),
            "url": metadata.get("url"),
            "category": metadata.get("category", "misc"),
            "tags": metadata.get("tags", []),
            "added": metadata.get("added", ""),
            "updated": metadata.get("updated", ""),
            "source": metadata.get("source", "manual"),
            "content_type": metadata.get("content_type", "text"),
            "content_hash": metadata.get("content_hash", ""),
            "word_count": metadata.get("word_count", 0),
            "summary": metadata.get("summary", ""),
            "classified_by": metadata.get("classified_by", ""),
            "embedded": metadata.get("embedded") or False,
            "pub_date": metadata.get("pub_date"),
            "has_snapshot": metadata.get("has_snapshot") or False,
            "has_original": metadata.get("has_original") or False,
            "verified": metadata.get("verified") or False,
        }
        async with self._lock:
            self._items[item_id] = entry
            await self._save()

    async def remove(self, item_id: str):
        async with self._lock:
            self._items.pop(item_id, None)
            await self._save()

    async def update_path(self, item_id: str, new_path: str, new_category: str):
        async with self._lock:
            if item_id in self._items:
                self._items[item_id]["path"] = new_path
                self._items[item_id]["category"] = new_category
                await self._save()

    async def update_metadata(self, item_id: str, metadata: dict):
        async with self._lock:
            if item_id in self._items:
                for k in ("title", "url", "category", "tags", "updated", "summary", "classified_by", "embedded", "word_count", "content_hash", "pub_date", "has_snapshot", "has_original", "verified"):
                    if k in metadata:
                        self._items[item_id][k] = metadata[k]
                await self._save()

    async def set_embedded(self, item_id: str, embedded: bool = True):
        async with self._lock:
            if item_id in self._items:
                self._items[item_id]["embedded"] = embedded
                await self._save()
                # Also persist to metadata.yaml so flag survives restarts
                item_path = self._data_dir / self._items[item_id]["path"] / "metadata.yaml"
                if item_path.exists():
                    try:
                        meta = yaml.safe_load(item_path.read_text(encoding="utf-8")) or {}
                        meta["embedded"] = embedded
                        item_path.write_text(yaml.dump(meta, allow_unicode=True), encoding="utf-8")
                    except Exception:
                        pass

    async def rebuild(self) -> int:
        """Walk /data/library and rebuild index from metadata.yaml files."""
        async with self._lock:
            self._items = {}
            library = self._data_dir / "library"
            count = 0
            if library.exists():
                for meta_file in library.rglob("metadata.yaml"):
                    try:
                        with open(meta_file) as f:
                            metadata = yaml.safe_load(f)
                        item_id = metadata.get("id")
                        if item_id:
                            path = str(meta_file.parent.relative_to(self._data_dir))
                            self._items[item_id] = {
                                "path": path,
                                **{k: metadata.get(k) for k in (
                                    "title", "url", "category", "tags", "added", "updated",
                                    "source", "content_type", "content_hash", "word_count",
                                    "summary", "classified_by", "pub_date",
                                )},
                                "embedded": metadata.get("embedded") or False,
                                "has_snapshot": metadata.get("has_snapshot") or False,
                                "has_original": metadata.get("has_original") or False,
                                "verified": metadata.get("verified") or False,
                            }
                            count += 1
                    except Exception:
                        pass
            await self._save()
            return count

    async def _save(self):
        """Atomically write index.json without blocking the event loop."""
        snapshot = json.dumps(self._items, indent=2, default=str)
        path = self._index_path
        tmp = self._index_path.with_suffix(".json.tmp")
        path.parent.mkdir(parents=True, exist_ok=True)

        def _write():
            with open(tmp, "w") as f:
                f.write(snapshot)
            os.replace(tmp, path)

        await asyncio.to_thread(_write)
