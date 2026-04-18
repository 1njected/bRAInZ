"""Tests for API key authentication middleware (auth.py)."""

import asyncio
import math
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

TEST_KEY = "test-api-key-12345"


@pytest.fixture()
def auth_mock_llm():
    llm = MagicMock()
    llm.provider_name = "mock/test"
    llm.embedding_dimensions = 4

    async def _complete(system, prompt, max_tokens=2000):
        return '{"category": "netsec", "tags": ["mitm"], "summary": "test."}'

    async def _complete_classify(system, prompt):
        return '{"category": "netsec", "tags": ["mitm"], "summary": "test."}'

    async def _embed(texts):
        v = [1.0 / math.sqrt(4)] * 4
        return [v for _ in texts]

    llm.complete = _complete
    llm.complete_classify = _complete_classify
    llm.embed = _embed
    return llm


@pytest.fixture()
def secured_client(data_dir, auth_mock_llm):
    """TestClient with a real API key configured — auth is active."""
    from fastapi.testclient import TestClient
    import api as api_module
    from storage.index import ItemIndex

    os.environ["API_KEYS"] = TEST_KEY

    api_module._llm = auth_mock_llm
    idx = ItemIndex(data_dir)
    asyncio.get_event_loop().run_until_complete(idx.load())
    api_module._index = idx
    api_module._vector_index = None

    client = TestClient(api_module.app, raise_server_exceptions=True)
    yield client

    os.environ["API_KEYS"] = ""


# ---------------------------------------------------------------------------
# Missing / invalid key → 401
# ---------------------------------------------------------------------------

class TestUnauthorised:
    def test_no_key_returns_401(self, secured_client):
        resp = secured_client.get("/api/items")
        assert resp.status_code == 401

    def test_wrong_key_returns_401(self, secured_client):
        resp = secured_client.get("/api/items", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401

    def test_empty_key_returns_401(self, secured_client):
        resp = secured_client.get("/api/items", headers={"X-API-Key": ""})
        assert resp.status_code == 401

    def test_401_body_has_detail(self, secured_client):
        resp = secured_client.get("/api/items")
        assert "detail" in resp.json()


# ---------------------------------------------------------------------------
# Valid key → 200
# ---------------------------------------------------------------------------

class TestAuthorised:
    def test_valid_key_header_allowed(self, secured_client):
        resp = secured_client.get("/api/items", headers={"X-API-Key": TEST_KEY})
        assert resp.status_code == 200

    def test_valid_key_allows_post(self, secured_client):
        resp = secured_client.post(
            "/api/ingest/text",
            json={"title": "Auth test", "body": "body text", "category": "netsec", "tags": []},
            headers={"X-API-Key": TEST_KEY},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Auth-exempt paths (no key required)
# ---------------------------------------------------------------------------

class TestAuthExemptPaths:
    def test_health_no_auth(self, secured_client):
        resp = secured_client.get("/api/health")
        assert resp.status_code == 200

    def test_root_no_auth(self, secured_client):
        resp = secured_client.get("/")
        assert resp.status_code == 200

    def test_static_files_no_auth(self, secured_client):
        # /static/ is exempt — a 404 (file not found) is fine, not a 401
        resp = secured_client.get("/static/nonexistent.js")
        assert resp.status_code != 401

    def test_options_preflight_no_auth(self, secured_client):
        resp = secured_client.options("/api/items", headers={"Origin": "http://localhost:3000"})
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# Snapshot / original: ?key= query param accepted (browser iframes can't send headers)
# ---------------------------------------------------------------------------

class TestQueryParamAuth:
    def _ingest_item(self, client):
        resp = client.post(
            "/api/ingest/text",
            json={"title": "QP test", "body": "body", "category": "netsec", "tags": []},
            headers={"X-API-Key": TEST_KEY},
        )
        assert resp.status_code == 200
        return resp.json()["item_id"]

    def test_snapshot_allows_query_param_key(self, secured_client):
        item_id = self._ingest_item(secured_client)
        # No snapshot file exists → 404, but NOT 401 (auth should pass)
        resp = secured_client.get(f"/api/items/{item_id}/snapshot?key={TEST_KEY}")
        assert resp.status_code != 401

    def test_snapshot_rejects_wrong_query_param_key(self, secured_client):
        item_id = self._ingest_item(secured_client)
        resp = secured_client.get(f"/api/items/{item_id}/snapshot?key=wrong")
        assert resp.status_code == 401

    def test_original_allows_query_param_key(self, secured_client):
        item_id = self._ingest_item(secured_client)
        resp = secured_client.get(f"/api/items/{item_id}/original?key={TEST_KEY}")
        assert resp.status_code != 401

    def test_regular_endpoint_query_param_not_accepted(self, secured_client):
        # /api/items does NOT accept ?key= — only snapshot/original do
        resp = secured_client.get(f"/api/items?key={TEST_KEY}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Assets path: always exempt (snapshots reference relative asset paths)
# ---------------------------------------------------------------------------

class TestAssetsExempt:
    def test_assets_path_exempt_no_key(self, secured_client):
        # 404 (asset not found) is fine; 401 is wrong
        resp = secured_client.get("/api/items/some-item/assets/image.png")
        assert resp.status_code != 401
