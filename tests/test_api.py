"""API endpoint tests using FastAPI TestClient."""

from pathlib import Path
import pytest


class TestHealth:
    def test_health_returns_ok(self, api_client):
        resp = api_client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "total_items" in data
        assert "llm_provider" in data

    def test_health_no_auth_required(self, api_client):
        # Health is public — no X-API-Key header
        resp = api_client.get("/api/health")
        assert resp.status_code == 200


class TestConfigEndpoints:
    def test_categories_returns_list(self, api_client):
        resp = api_client.get("/api/config/categories")
        assert resp.status_code == 200
        cats = resp.json()
        assert isinstance(cats, list)
        assert len(cats) > 0
        assert "misc" in cats

    def test_llm_config(self, api_client):
        resp = api_client.get("/api/config/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert "provider" in data
        assert "classification_model" in data
        assert "query_model" in data
        assert "embedding_model" in data


class TestItemsCRUD:
    def test_list_items_empty(self, api_client):
        resp = api_client.get("/api/items")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_ingest_text_and_retrieve(self, api_client):
        # Ingest a text note
        resp = api_client.post("/api/ingest/text", json={
            "title": "Test Note",
            "body": "This is a test note about XSS attacks.",
            "category": "appsec",
            "tags": ["xss"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "item_id" in data
        assert data["category"] == "appsec"
        item_id = data["item_id"]

        # Retrieve it
        resp2 = api_client.get(f"/api/items/{item_id}")
        assert resp2.status_code == 200
        item = resp2.json()
        assert item["title"] == "Test Note"
        assert item["category"] == "appsec"

    def test_ingest_text_appears_in_list(self, api_client):
        api_client.post("/api/ingest/text", json={
            "title": "Listed Note",
            "body": "Content for listing test.",
            "category": "misc",
            "tags": [],
        })
        resp = api_client.get("/api/items")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    def test_get_nonexistent_item_404(self, api_client):
        resp = api_client.get("/api/items/doesnotexist")
        assert resp.status_code == 404

    def test_get_item_content(self, api_client):
        resp = api_client.post("/api/ingest/text", json={
            "title": "Content Test",
            "body": "The actual content body.",
            "category": "misc",
            "tags": [],
        })
        item_id = resp.json()["item_id"]
        resp2 = api_client.get(f"/api/items/{item_id}/content")
        assert resp2.status_code == 200
        assert "actual content body" in resp2.text

    def test_patch_item_title(self, api_client):
        resp = api_client.post("/api/ingest/text", json={
            "title": "Original Title",
            "body": "Body content.",
            "category": "misc",
            "tags": [],
        })
        item_id = resp.json()["item_id"]
        patch = api_client.patch(f"/api/items/{item_id}", json={"title": "Updated Title"})
        assert patch.status_code == 200
        assert patch.json()["title"] == "Updated Title"

    def test_patch_item_category(self, api_client):
        resp = api_client.post("/api/ingest/text", json={
            "title": "Cat Change",
            "body": "Body.",
            "category": "misc",
            "tags": [],
        })
        item_id = resp.json()["item_id"]
        patch = api_client.patch(f"/api/items/{item_id}", json={"category": "appsec"})
        assert patch.status_code == 200
        assert patch.json()["category"] == "appsec"

    def test_delete_item(self, api_client):
        resp = api_client.post("/api/ingest/text", json={
            "title": "To Delete",
            "body": "This will be deleted.",
            "category": "misc",
            "tags": [],
        })
        item_id = resp.json()["item_id"]
        del_resp = api_client.delete(f"/api/items/{item_id}")
        assert del_resp.status_code == 200
        # Confirm gone
        get_resp = api_client.get(f"/api/items/{item_id}")
        assert get_resp.status_code == 404

    def test_delete_nonexistent_404(self, api_client):
        resp = api_client.delete("/api/items/ghost")
        assert resp.status_code == 404

    def test_filter_by_category(self, api_client):
        api_client.post("/api/ingest/text", json={"title": "A", "body": "a", "category": "appsec", "tags": []})
        api_client.post("/api/ingest/text", json={"title": "B", "body": "b", "category": "netsec", "tags": []})
        resp = api_client.get("/api/items?category=appsec")
        data = resp.json()
        assert all(i["category"] == "appsec" for i in data["items"])

    def test_duplicate_text_flagged(self, api_client):
        body = {"title": "Dup", "body": "Same content exactly.", "category": "misc", "tags": []}
        resp1 = api_client.post("/api/ingest/text", json=body)
        resp2 = api_client.post("/api/ingest/text", json=body)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp2.json()["duplicate"] is True


class TestCategoriesAndTags:
    def test_categories_endpoint(self, api_client):
        resp = api_client.get("/api/categories")
        assert resp.status_code == 200
        cats = resp.json()
        assert isinstance(cats, list)

    def test_tags_endpoint(self, api_client):
        resp = api_client.get("/api/tags")
        assert resp.status_code == 200
        tags = resp.json()
        assert isinstance(tags, list)
        for t in tags:
            assert "name" in t
            assert "count" in t

    def test_tags_include_curated(self, api_client, data_dir):
        import config
        # Write a minimal taxonomy so curated tags load
        taxonomy = (
            "categories:\n"
            "  - name: appsec\n"
            "    tags: [xss, sqli]\n"
            "  - name: netsec\n"
            "    tags: [mitm, arp-spoofing]\n"
        )
        (data_dir / "taxonomy.yaml").write_text(taxonomy)
        config._taxonomy = None
        config._taxonomy_mtime = None
        resp = api_client.get("/api/tags")
        names = [t["name"] for t in resp.json()]
        assert "xss" in names
        assert "mitm" in names

    def test_categories_after_ingest(self, api_client):
        api_client.post("/api/ingest/text", json={"title": "T", "body": "b", "category": "appsec", "tags": []})
        resp = api_client.get("/api/categories")
        names = [c["name"] for c in resp.json()]
        assert "appsec" in names


class TestReindex:
    def test_reindex_returns_count(self, api_client):
        resp = api_client.post("/api/reindex")
        assert resp.status_code == 200
        assert "rebuilt" in resp.json()


class TestIngestTextBehavioral:
    """Deeper behavioral checks — verify files and index state, not just HTTP codes."""

    def test_ingest_creates_content_file_on_disk(self, api_client, data_dir):
        resp = api_client.post("/api/ingest/text", json={
            "title": "Disk Check",
            "body": "Body for disk verification.",
            "category": "misc",
            "tags": [],
        })
        assert resp.status_code == 200
        content_files = list((data_dir / "library").glob("**/content.md"))
        assert len(content_files) >= 1

    def test_ingest_creates_metadata_file_on_disk(self, api_client, data_dir):
        resp = api_client.post("/api/ingest/text", json={
            "title": "Meta Check",
            "body": "Body for metadata verification.",
            "category": "misc",
            "tags": [],
        })
        assert resp.status_code == 200
        meta_files = list((data_dir / "library").glob("**/metadata.yaml"))
        assert len(meta_files) >= 1

    def test_ingest_item_appears_in_list(self, api_client):
        resp = api_client.post("/api/ingest/text", json={
            "title": "In List Article",
            "body": "Some content.",
            "category": "appsec",
            "tags": ["xss"],
        })
        item_id = resp.json()["item_id"]
        list_resp = api_client.get("/api/items")
        ids = [i["id"] for i in list_resp.json()["items"]]
        assert item_id in ids

    def test_ingest_tags_stored_correctly(self, api_client):
        resp = api_client.post("/api/ingest/text", json={
            "title": "Tagged Article",
            "body": "Body.",
            "category": "appsec",
            "tags": ["sqli", "rce"],
        })
        item_id = resp.json()["item_id"]
        item = api_client.get(f"/api/items/{item_id}").json()
        assert "sqli" in item["tags"]
        assert "rce" in item["tags"]

    def test_patch_title_persisted_in_get(self, api_client):
        resp = api_client.post("/api/ingest/text", json={
            "title": "Before Patch",
            "body": "body.",
            "category": "misc",
            "tags": [],
        })
        item_id = resp.json()["item_id"]
        api_client.patch(f"/api/items/{item_id}", json={"title": "After Patch"})
        item = api_client.get(f"/api/items/{item_id}").json()
        assert item["title"] == "After Patch"

    def test_patch_category_moves_item_in_list(self, api_client):
        resp = api_client.post("/api/ingest/text", json={
            "title": "Cat Move",
            "body": "body.",
            "category": "misc",
            "tags": [],
        })
        item_id = resp.json()["item_id"]
        api_client.patch(f"/api/items/{item_id}", json={"category": "netsec"})
        item = api_client.get(f"/api/items/{item_id}").json()
        assert item["category"] == "netsec"
        # Also appears in category filter
        filtered = api_client.get("/api/items?category=netsec").json()
        assert any(i["id"] == item_id for i in filtered["items"])

    def test_delete_removes_from_list(self, api_client):
        resp = api_client.post("/api/ingest/text", json={
            "title": "Will Be Gone",
            "body": "body.",
            "category": "misc",
            "tags": [],
        })
        item_id = resp.json()["item_id"]
        api_client.delete(f"/api/items/{item_id}")
        list_resp = api_client.get("/api/items").json()
        assert all(i["id"] != item_id for i in list_resp["items"])

    def test_total_count_increments_on_ingest(self, api_client):
        before = api_client.get("/api/items").json()["total"]
        api_client.post("/api/ingest/text", json={
            "title": "Counter Article",
            "body": "body.",
            "category": "misc",
            "tags": [],
        })
        after = api_client.get("/api/items").json()["total"]
        assert after == before + 1

    def test_health_reflects_item_count(self, api_client):
        before = api_client.get("/api/health").json()["total_items"]
        api_client.post("/api/ingest/text", json={
            "title": "Health Check Article",
            "body": "body.",
            "category": "misc",
            "tags": [],
        })
        after = api_client.get("/api/health").json()["total_items"]
        assert after == before + 1

    def test_duplicate_same_item_id_returned(self, api_client):
        body = {"title": "Dup ID", "body": "Unique dup content abc.", "category": "misc", "tags": []}
        r1 = api_client.post("/api/ingest/text", json=body)
        r2 = api_client.post("/api/ingest/text", json=body)
        assert r2.json()["item_id"] == r1.json()["item_id"]


class TestItemListPagination:
    def test_limit_parameter(self, api_client):
        for i in range(5):
            api_client.post("/api/ingest/text", json={
                "title": f"Article {i}",
                "body": f"Body {i} unique content.",
                "category": "misc",
                "tags": [],
            })
        resp = api_client.get("/api/items?limit=2").json()
        assert len(resp["items"]) <= 2

    def test_offset_parameter(self, api_client):
        for i in range(4):
            api_client.post("/api/ingest/text", json={
                "title": f"Page Article {i}",
                "body": f"Body page {i} unique.",
                "category": "misc",
                "tags": [],
            })
        page1 = api_client.get("/api/items?limit=2&offset=0").json()
        page2 = api_client.get("/api/items?limit=2&offset=2").json()
        ids1 = {i["id"] for i in page1["items"]}
        ids2 = {i["id"] for i in page2["items"]}
        assert ids1.isdisjoint(ids2)  # no overlap between pages
