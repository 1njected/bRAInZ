"""Tests for RAG components: chunker, embedder, and vector search."""

import json
import math
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------

class TestChunkText:
    def test_short_text_single_chunk(self):
        from rag.chunker import chunk_text
        chunks = chunk_text("Short text.", chunk_size=500, overlap=50)
        assert len(chunks) == 1
        assert chunks[0]["text"] == "Short text."
        assert chunks[0]["index"] == 0

    def test_chunk_schema(self):
        from rag.chunker import chunk_text
        chunks = chunk_text("Some content.", chunk_size=500, overlap=50)
        for c in chunks:
            assert "index" in c
            assert "text" in c
            assert "start_char" in c
            assert "end_char" in c

    def test_long_text_multiple_chunks(self):
        from rag.chunker import chunk_text
        # Generate ~3000 chars across paragraphs
        para = "A" * 300
        text = "\n\n".join([para] * 10)
        chunks = chunk_text(text, chunk_size=100, overlap=10)
        assert len(chunks) > 1

    def test_chunks_cover_content(self):
        from rag.chunker import chunk_text
        para = "Security research content. " * 20
        text = "\n\n".join([para] * 5)
        chunks = chunk_text(text, chunk_size=100, overlap=10)
        # All chunk text should be non-empty
        assert all(len(c["text"]) > 0 for c in chunks)

    def test_chunk_indices_sequential(self):
        from rag.chunker import chunk_text
        para = "X" * 200
        text = "\n\n".join([para] * 10)
        chunks = chunk_text(text, chunk_size=50, overlap=5)
        for i, c in enumerate(chunks):
            assert c["index"] == i

    def test_empty_text_returns_empty(self):
        from rag.chunker import chunk_text
        chunks = chunk_text("", chunk_size=500, overlap=50)
        assert chunks == []

    @pytest.mark.asyncio
    async def test_chunk_item_saves_json(self, data_dir):
        from storage.index import ItemIndex
        from storage.filesystem import save_item
        from rag.chunker import chunk_item

        idx = ItemIndex(data_dir)
        await idx.load()

        item_id = await save_item(
            {"title": "Test", "category": "appsec", "tags": [], "source": "test", "content_type": "text", "summary": "", "classified_by": ""},
            "Paragraph one.\n\nParagraph two.\n\nParagraph three.",
            idx, data_dir,
        )
        chunks = chunk_item(item_id, idx, data_dir)
        assert len(chunks) >= 1
        # Verify chunks.json was written
        entry = idx.get(item_id)
        chunks_file = data_dir / entry["path"] / "chunks.json"
        assert chunks_file.exists()
        loaded = json.loads(chunks_file.read_text())
        assert len(loaded) == len(chunks)


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------

class TestEmbedder:
    @pytest.mark.asyncio
    async def test_embed_item_creates_npz(self, data_dir, mock_llm):
        from storage.index import ItemIndex
        from storage.filesystem import save_item
        from rag.chunker import chunk_item
        from rag.embedder import embed_item

        idx = ItemIndex(data_dir)
        await idx.load()
        item_id = await save_item(
            {"title": "Embed Test", "category": "netsec", "tags": [], "source": "test", "content_type": "text", "summary": "", "classified_by": ""},
            "Paragraph one about networks.\n\nParagraph two about pivoting.",
            idx, data_dir,
        )
        chunk_item(item_id, idx, data_dir)
        ok = await embed_item(item_id, mock_llm, idx, data_dir)
        assert ok is True
        npz_file = data_dir / "embeddings" / f"{item_id}.npz"
        assert npz_file.exists()

    @pytest.mark.asyncio
    async def test_embed_item_marks_embedded(self, data_dir, mock_llm):
        from storage.index import ItemIndex
        from storage.filesystem import save_item
        from rag.chunker import chunk_item
        from rag.embedder import embed_item

        idx = ItemIndex(data_dir)
        await idx.load()
        item_id = await save_item(
            {"title": "Embed Test", "category": "netsec", "tags": [], "source": "test", "content_type": "text", "summary": "", "classified_by": ""},
            "Content about network security.\n\nMore content.",
            idx, data_dir,
        )
        chunk_item(item_id, idx, data_dir)
        await embed_item(item_id, mock_llm, idx, data_dir)
        assert idx.get(item_id)["embedded"] is True

    @pytest.mark.asyncio
    async def test_embed_unknown_item_returns_false(self, data_dir, mock_llm):
        from storage.index import ItemIndex
        from rag.embedder import embed_item

        idx = ItemIndex(data_dir)
        await idx.load()
        ok = await embed_item("nonexistent-id", mock_llm, idx, data_dir)
        assert ok is False

    @pytest.mark.asyncio
    async def test_rebuild_vector_index_creates_files(self, data_dir, mock_llm):
        from storage.index import ItemIndex
        from storage.filesystem import save_item
        from rag.chunker import chunk_item
        from rag.embedder import embed_item, rebuild_vector_index

        idx = ItemIndex(data_dir)
        await idx.load()
        item_id = await save_item(
            {"title": "Vec Test", "category": "appsec", "tags": [], "source": "test", "content_type": "text", "summary": "", "classified_by": ""},
            "Web security content.\n\nMore paragraphs here.",
            idx, data_dir,
        )
        chunk_item(item_id, idx, data_dir)
        await embed_item(item_id, mock_llm, idx, data_dir)

        embed_dir = data_dir / "embeddings"
        assert (embed_dir / "index.npz").exists()
        assert (embed_dir / "item_map.json").exists()


# ---------------------------------------------------------------------------
# Vector search
# ---------------------------------------------------------------------------

class TestVectorIndex:
    def _build_index(self, data_dir, n_items=3, dims=4):
        """Helper: manually write index.npz + item_map.json."""
        import numpy as np
        embed_dir = data_dir / "embeddings"
        embed_dir.mkdir(exist_ok=True)

        vectors = []
        item_map = []
        for i in range(n_items):
            v = np.zeros(dims, dtype=np.float32)
            v[i % dims] = 1.0  # orthogonal unit vectors
            vectors.append(v)
            item_map.append(f"item{i}")

        combined = np.stack(vectors)
        np.savez_compressed(embed_dir / "index.npz", embeddings=combined)
        (embed_dir / "item_map.json").write_text(json.dumps(item_map))

    def test_load_sets_is_loaded(self, data_dir):
        from rag.search import VectorIndex
        self._build_index(data_dir)
        vi = VectorIndex(data_dir)
        vi.load()
        assert vi.is_loaded()

    def test_empty_dir_not_loaded(self, data_dir):
        from rag.search import VectorIndex
        vi = VectorIndex(data_dir)
        vi.load()
        assert not vi.is_loaded()

    def test_search_returns_top_k(self, data_dir):
        from rag.search import VectorIndex
        self._build_index(data_dir, n_items=3)
        vi = VectorIndex(data_dir)
        vi.load()
        query = [1.0, 0.0, 0.0, 0.0]
        results = vi.search(query, top_k=2)
        assert len(results) <= 2

    def test_search_best_match_first(self, data_dir):
        import numpy as np
        embed_dir = data_dir / "embeddings"
        embed_dir.mkdir(exist_ok=True)
        # item0: [0.9, 0.1, 0, 0] (closer to query), item1: [0.6, 0.8, 0, 0]
        v0 = np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32)
        v0 /= np.linalg.norm(v0)
        v1 = np.array([0.6, 0.8, 0.0, 0.0], dtype=np.float32)
        v1 /= np.linalg.norm(v1)
        combined = np.stack([v0, v1])
        np.savez_compressed(embed_dir / "index.npz", embeddings=combined)
        import json
        (embed_dir / "item_map.json").write_text(json.dumps(["item0", "item1"]))

        from rag.search import VectorIndex
        vi = VectorIndex(data_dir)
        vi.load()
        query = [1.0, 0.0, 0.0, 0.0]
        results = vi.search(query, top_k=3)
        assert len(results) >= 2
        assert results[0]["item_id"] == "item0"
        assert results[0]["score"] > results[1]["score"]

    def test_search_with_allowed_filter(self, data_dir):
        from rag.search import VectorIndex
        self._build_index(data_dir, n_items=3)
        vi = VectorIndex(data_dir)
        vi.load()
        query = [1.0, 0.0, 0.0, 0.0]
        results = vi.search(query, top_k=3, allowed_item_ids={"item1", "item2"})
        returned_ids = {r["item_id"] for r in results}
        assert "item0" not in returned_ids

    def test_search_result_schema(self, data_dir):
        from rag.search import VectorIndex
        self._build_index(data_dir, n_items=2)
        vi = VectorIndex(data_dir)
        vi.load()
        results = vi.search([1.0, 0.0, 0.0, 0.0], top_k=2)
        for r in results:
            assert "item_id" in r
            assert "score" in r
