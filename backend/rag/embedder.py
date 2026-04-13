"""Embed documents and build/update the vector index."""

from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path

import numpy as np


async def embed_item(item_id: str, llm, index, data_dir: Path, vector_index=None) -> bool:
    """Embed content_llm.md (or content.md) for an item. Saves {item_id}.npz to embeddings/.

    Pass vector_index to reload the in-memory index after rebuilding so queries
    immediately see the new item.
    """
    entry = index.get(item_id)
    if not entry:
        return False

    item_dir = data_dir / entry["path"]

    llm_file = item_dir / "content_llm.md"
    content_file = item_dir / "content.md"
    target = llm_file if llm_file.exists() else content_file
    if not target.exists():
        return False

    text = target.read_text(encoding="utf-8").strip()
    if not text:
        return False

    embeddings = await llm.embed([text])

    embed_dir = data_dir / "embeddings"
    embed_dir.mkdir(parents=True, exist_ok=True)

    vectors = np.array(embeddings, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    vectors = vectors / norms

    np.savez_compressed(embed_dir / f"{item_id}.npz", embeddings=vectors)
    await index.set_embedded(item_id, True)

    await asyncio.to_thread(rebuild_vector_index, data_dir)
    if vector_index is not None:
        vector_index.load()
    return True


async def embed_all(data_dir: Path, llm, index, vector_index=None) -> int:
    """Embed all items that haven't been embedded yet."""
    count = 0
    for item_id, meta in index.all_items().items():
        if not meta.get("embedded"):
            # Don't reload after each item — do one reload at the end
            ok = await embed_item(item_id, llm, index, data_dir)
            if ok:
                count += 1
    await asyncio.to_thread(rebuild_vector_index, data_dir)
    if vector_index is not None:
        vector_index.load()
    return count


def rebuild_vector_index(data_dir: Path):
    """Combine all per-item .npz files into index.npz + item_map.json."""
    embed_dir = data_dir / "embeddings"
    if not embed_dir.exists():
        return

    all_vectors = []
    item_map = []  # row_number → item_id

    for npz_file in sorted(embed_dir.glob("*.npz")):
        if npz_file.stem in ("index", "index_tmp"):
            continue
        item_id = npz_file.stem
        data = np.load(npz_file)
        vectors = data["embeddings"]
        # One vector per item (first row if multiple exist from old chunk-based files)
        all_vectors.append(vectors[0:1])
        item_map.append(item_id)

    if not all_vectors:
        return

    combined = np.vstack(all_vectors).astype(np.float32)

    tmp_stem = embed_dir / "index_tmp"
    tmp_map = embed_dir / "item_map.json.tmp"

    np.savez_compressed(tmp_stem, embeddings=combined)
    with open(tmp_map, "w") as f:
        json.dump(item_map, f)

    os.replace(embed_dir / "index_tmp.npz", embed_dir / "index.npz")
    os.replace(tmp_map, embed_dir / "item_map.json")
