"""Vector similarity search using numpy."""

from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

# Lazy-loaded reranker singleton (loaded once, reused across requests)
_reranker = None
_reranker_model: str | None = None


def _get_reranker(model: str = "ms-marco-MiniLM-L-12-v2"):
    """Return a cached FlashRank Ranker, loading it on first call."""
    global _reranker, _reranker_model
    if _reranker is None or _reranker_model != model:
        try:
            from flashrank import Ranker
            _reranker = Ranker(model_name=model, cache_dir="/tmp/flashrank")
            _reranker_model = model
            log.info("FlashRank reranker loaded: %s", model)
        except ImportError:
            log.warning("flashrank not installed — reranking disabled. Run: pip install flashrank")
            _reranker = None
    return _reranker


class VectorIndex:
    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._vectors: np.ndarray | None = None   # shape (N, D), normalized
        self._item_map: list[str] = []             # row index → item_id

    def load(self):
        embed_dir = self._data_dir / "embeddings"
        index_file = embed_dir / "index.npz"

        # Support both new item_map.json and legacy chunk_map.json
        map_file = embed_dir / "item_map.json"
        legacy_map = embed_dir / "chunk_map.json"

        if not index_file.exists():
            self._vectors = None
            self._item_map = []
            return

        data = np.load(index_file)
        self._vectors = data["embeddings"].astype(np.float32)

        if map_file.exists():
            with open(map_file) as f:
                self._item_map = json.load(f)  # list of item_id strings
        elif legacy_map.exists():
            # Migrate from chunk_map: take first entry per item_id
            with open(legacy_map) as f:
                chunk_map = json.load(f)
            seen: dict[str, int] = {}
            for i, entry in enumerate(chunk_map):
                iid = entry["item_id"]
                if iid not in seen:
                    seen[iid] = i
            # item_map is a list of item_ids, one per row in the index
            # For legacy, just build a per-row list (chunk_map length matches rows)
            self._item_map = [entry["item_id"] for entry in chunk_map]
        else:
            self._item_map = []

    def is_loaded(self) -> bool:
        return self._vectors is not None and len(self._vectors) > 0

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        allowed_item_ids: set[str] | None = None,
    ) -> list[dict]:
        """Return top_k results as [{item_id, score}, ...]."""
        if not self.is_loaded():
            return []

        q = np.array(query_embedding, dtype=np.float32)
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm

        scores = self._vectors @ q

        if allowed_item_ids is not None:
            for i, item_id in enumerate(self._item_map):
                if item_id not in allowed_item_ids:
                    scores[i] = -1.0

        top_indices = np.argsort(scores)[::-1][:top_k]
        seen: set[str] = set()
        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score < 0.25:
                continue
            item_id = self._item_map[idx]
            if item_id in seen:
                continue
            seen.add(item_id)
            results.append({"item_id": item_id, "score": score})

        return results


async def semantic_search(
    query: str,
    llm,
    vector_index: VectorIndex,
    index,
    data_dir: Path | None = None,
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
    top_k: int = 10,
    content_types: Optional[list[str]] = None,
    query_embedding: Optional[list[float]] = None,
    reranker: str | None = "auto",
    reranker_top_k: int | None = None,
) -> list[dict]:
    """Embed query, filter, search, optionally rerank, and return enriched results."""
    if query_embedding is None:
        embeddings = await llm.embed([query])
        query_embedding = embeddings[0]

    allowed = None
    if category or tags or content_types:
        allowed = set()
        for item_id, meta in index.all_items().items():
            if category and meta.get("category") != category:
                continue
            if tags:
                item_tags = meta.get("tags", [])
                if not any(t in item_tags for t in tags):
                    continue
            if content_types and meta.get("content_type") not in content_types:
                continue
            allowed.add(item_id)

    # Fetch more candidates when reranking so the reranker has enough to work with
    fetch_k = top_k if reranker == "none" else max(top_k * 2, 20)
    raw_results = vector_index.search(query_embedding, top_k=fetch_k, allowed_item_ids=allowed)

    if data_dir is None and hasattr(index, "_data_dir"):
        data_dir = index._data_dir

    enriched = []
    for r in raw_results:
        item_id = r["item_id"]
        meta = index.get(item_id)
        if not meta:
            continue
        content = _get_content(meta, data_dir)
        enriched.append({
            "item_id": item_id,
            "content": content,
            "score": r["score"],
            "title": meta.get("title", ""),
            "url": meta.get("url"),
            "category": meta.get("category", "misc"),
            "content_type": meta.get("content_type", "text"),
        })

    # Reranking pass
    from config import get_config
    cfg = get_config().get("rag", {})
    effective_reranker = reranker if reranker != "auto" else cfg.get("reranker", "none")
    effective_top_k = reranker_top_k or cfg.get("reranker_top_k", top_k)

    if effective_reranker == "flashrank" and len(enriched) > 1:
        ranker = _get_reranker()
        if ranker is not None:
            try:
                from flashrank import RerankRequest
                passages = [{"id": i, "text": r["content"][:2000]} for i, r in enumerate(enriched)]
                req = RerankRequest(query=query, passages=passages)
                reranked = ranker.rerank(req)
                # Map back by original index, sort by new score descending
                score_map = {p["id"]: p["score"] for p in reranked}
                for i, r in enumerate(enriched):
                    r["score"] = score_map.get(i, r["score"])
                enriched.sort(key=lambda r: r["score"], reverse=True)
            except Exception as e:
                log.warning("Reranking failed, using vector scores: %s", e)

    return enriched[:effective_top_k]


def _get_content(meta: dict, data_dir: Path | None) -> str:
    if data_dir is None:
        return ""
    item_dir = data_dir / meta["path"]
    for name in ("content_llm.md", "content.md"):
        f = item_dir / name
        if f.exists():
            return f.read_text(encoding="utf-8")
    return ""
