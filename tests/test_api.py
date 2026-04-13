"""API endpoint tests using FastAPI TestClient."""

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
        import shutil
        from pathlib import Path
        # Copy the real tags.yaml into the test data dir so curated tags load
        real_tags = Path(__file__).parent.parent / "data" / "tags.yaml"
        if real_tags.exists():
            shutil.copy(real_tags, data_dir / "tags.yaml")
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
