"""Tests for filesystem storage and ItemIndex using temp directories."""

import asyncio
from pathlib import Path

import pytest


SAMPLE_ITEM = {
    "title": "Test Article",
    "url": "https://example.com/test",
    "category": "appsec",
    "tags": ["xss", "csrf"],
    "source": "test",
    "content_type": "url",
    "summary": "A test article about web security.",
    "classified_by": "mock/test",
}
SAMPLE_CONTENT = "# Test Article\n\nThis is some test content about XSS and CSRF attacks."


class TestItemIndex:
    @pytest.mark.asyncio
    async def test_load_empty_index(self, data_dir):
        from storage.index import ItemIndex
        idx = ItemIndex(data_dir)
        await idx.load()
        assert idx.all_items() == {}

    @pytest.mark.asyncio
    async def test_add_and_get(self, data_dir):
        from storage.index import ItemIndex
        idx = ItemIndex(data_dir)
        await idx.load()
        idx.add("abc123", {**SAMPLE_ITEM, "content_hash": "sha256:aaa", "word_count": 10, "added": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z", "embedded": False}, "library/appsec/2026-01-01_test")
        entry = idx.get("abc123")
        assert entry is not None
        assert entry["category"] == "appsec"

    @pytest.mark.asyncio
    async def test_index_persists_to_disk(self, data_dir):
        from storage.index import ItemIndex
        idx = ItemIndex(data_dir)
        await idx.load()
        idx.add("abc123", {**SAMPLE_ITEM, "content_hash": "sha256:aaa", "word_count": 10, "added": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z", "embedded": False}, "library/appsec/test")
        # Reload from disk
        idx2 = ItemIndex(data_dir)
        await idx2.load()
        assert idx2.get("abc123") is not None

    @pytest.mark.asyncio
    async def test_remove(self, data_dir):
        from storage.index import ItemIndex
        idx = ItemIndex(data_dir)
        await idx.load()
        idx.add("abc123", {**SAMPLE_ITEM, "content_hash": "sha256:aaa", "word_count": 10, "added": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z", "embedded": False}, "library/appsec/test")
        idx.remove("abc123")
        assert idx.get("abc123") is None

    @pytest.mark.asyncio
    async def test_find_by_hash(self, data_dir):
        from storage.index import ItemIndex
        idx = ItemIndex(data_dir)
        await idx.load()
        idx.add("abc123", {**SAMPLE_ITEM, "content_hash": "sha256:deadbeef", "word_count": 10, "added": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z", "embedded": False}, "library/appsec/test")
        found = idx.find_by_hash("sha256:deadbeef")
        assert found == "abc123"

    @pytest.mark.asyncio
    async def test_find_by_hash_miss(self, data_dir):
        from storage.index import ItemIndex
        idx = ItemIndex(data_dir)
        await idx.load()
        assert idx.find_by_hash("sha256:nothere") is None

    @pytest.mark.asyncio
    async def test_search_by_category(self, data_dir):
        from storage.index import ItemIndex
        idx = ItemIndex(data_dir)
        await idx.load()
        meta = {**SAMPLE_ITEM, "content_hash": "sha256:aaa", "word_count": 10, "added": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z", "embedded": False}
        idx.add("id1", {**meta, "category": "appsec"}, "library/appsec/test1")
        idx.add("id2", {**meta, "category": "netsec", "content_hash": "sha256:bbb"}, "library/netsec/test2")
        results = idx.search(category="appsec")
        ids = [r["id"] for r in results]
        assert "id1" in ids
        assert "id2" not in ids

    @pytest.mark.asyncio
    async def test_search_by_tag(self, data_dir):
        from storage.index import ItemIndex
        idx = ItemIndex(data_dir)
        await idx.load()
        meta = {**SAMPLE_ITEM, "content_hash": "sha256:aaa", "word_count": 10, "added": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z", "embedded": False}
        idx.add("id1", {**meta, "tags": ["xss", "csrf"]}, "library/appsec/test1")
        idx.add("id2", {**meta, "tags": ["mitm"], "content_hash": "sha256:bbb"}, "library/netsec/test2")
        results = idx.search(tag="xss")
        ids = [r["id"] for r in results]
        assert "id1" in ids
        assert "id2" not in ids

    @pytest.mark.asyncio
    async def test_search_text_query(self, data_dir):
        from storage.index import ItemIndex
        idx = ItemIndex(data_dir)
        await idx.load()
        meta = {**SAMPLE_ITEM, "content_hash": "sha256:aaa", "word_count": 10, "added": "2026-01-01T00:00:00Z", "updated": "2026-01-01T00:00:00Z", "embedded": False}
        idx.add("id1", {**meta, "title": "Kerberoasting guide", "summary": "AD attacks"}, "library/redteam/test1")
        idx.add("id2", {**meta, "title": "Web fuzzing", "summary": "Fuzzing web apps", "content_hash": "sha256:bbb"}, "library/fuzzing/test2")
        results = idx.search(text_query="kerberoasting")
        ids = [r["id"] for r in results]
        assert "id1" in ids
        assert "id2" not in ids

    @pytest.mark.asyncio
    async def test_rebuild_from_filesystem(self, data_dir):
        from storage.index import ItemIndex
        from storage.filesystem import save_item
        idx = ItemIndex(data_dir)
        await idx.load()
        save_item(SAMPLE_ITEM, SAMPLE_CONTENT, idx, data_dir)
        # Wipe in-memory index and rebuild from disk
        idx2 = ItemIndex(data_dir)
        await idx2.load()
        count = await idx2.rebuild()
        assert count == 1


class TestFilesystem:
    @pytest.mark.asyncio
    async def test_save_and_load(self, data_dir):
        from storage.index import ItemIndex
        from storage.filesystem import save_item, load_item
        idx = ItemIndex(data_dir)
        await idx.load()
        item_id = save_item(SAMPLE_ITEM, SAMPLE_CONTENT, idx, data_dir)
        loaded = load_item(item_id, idx, data_dir)
        assert loaded is not None
        assert loaded["title"] == "Test Article"
        assert loaded["content"] == SAMPLE_CONTENT
        assert loaded["category"] == "appsec"

    @pytest.mark.asyncio
    async def test_save_creates_files(self, data_dir):
        from storage.index import ItemIndex
        from storage.filesystem import save_item
        idx = ItemIndex(data_dir)
        await idx.load()
        item_id = save_item(SAMPLE_ITEM, SAMPLE_CONTENT, idx, data_dir)
        entry = idx.get(item_id)
        item_dir = data_dir / entry["path"]
        assert (item_dir / "metadata.yaml").exists()
        assert (item_dir / "content.md").exists()

    @pytest.mark.asyncio
    async def test_content_hash_stored(self, data_dir):
        from storage.index import ItemIndex
        from storage.filesystem import save_item, load_item
        idx = ItemIndex(data_dir)
        await idx.load()
        item_id = save_item(SAMPLE_ITEM, SAMPLE_CONTENT, idx, data_dir)
        loaded = load_item(item_id, idx, data_dir)
        assert loaded["content_hash"].startswith("sha256:")

    @pytest.mark.asyncio
    async def test_delete_item(self, data_dir):
        from storage.index import ItemIndex
        from storage.filesystem import save_item, load_item, delete_item
        idx = ItemIndex(data_dir)
        await idx.load()
        item_id = save_item(SAMPLE_ITEM, SAMPLE_CONTENT, idx, data_dir)
        ok = await delete_item(item_id, idx, data_dir)
        assert ok is True
        assert load_item(item_id, idx, data_dir) is None
        assert idx.get(item_id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, data_dir):
        from storage.index import ItemIndex
        from storage.filesystem import delete_item
        idx = ItemIndex(data_dir)
        await idx.load()
        ok = await delete_item("doesnotexist", idx, data_dir)
        assert ok is False

    @pytest.mark.asyncio
    async def test_update_title(self, data_dir):
        from storage.index import ItemIndex
        from storage.filesystem import save_item, update_item
        idx = ItemIndex(data_dir)
        await idx.load()
        item_id = save_item(SAMPLE_ITEM, SAMPLE_CONTENT, idx, data_dir)
        updated = await update_item(item_id, {"title": "Updated Title"}, idx, data_dir)
        assert updated["title"] == "Updated Title"

    @pytest.mark.asyncio
    async def test_update_category_moves_directory(self, data_dir):
        from storage.index import ItemIndex
        from storage.filesystem import save_item, update_item
        idx = ItemIndex(data_dir)
        await idx.load()
        item_id = save_item(SAMPLE_ITEM, SAMPLE_CONTENT, idx, data_dir)
        await update_item(item_id, {"category": "netsec"}, idx, data_dir)
        entry = idx.get(item_id)
        assert entry["category"] == "netsec"
        assert "netsec" in entry["path"]

    @pytest.mark.asyncio
    async def test_dedup_by_hash(self, data_dir):
        from storage.index import ItemIndex
        from storage.filesystem import save_item
        idx = ItemIndex(data_dir)
        await idx.load()
        id1 = save_item(SAMPLE_ITEM, SAMPLE_CONTENT, idx, data_dir)
        # Same content → same hash
        existing = idx.find_by_hash(idx.get(id1)["content_hash"])
        assert existing == id1
