"""bRAInZ MCP server — read-only access to the knowledge base.

Exposes tools for searching, querying, and reading library items and digest pages.

Configuration (environment variables or .env file):
  BRAINZ_URL    Base URL of the bRAInZ API  (default: http://localhost:8000)
  BRAINZ_KEY    API key                      (default: empty, for open-access installs)
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BRAINZ_URL = os.environ.get("BRAINZ_URL", "http://localhost:8000").rstrip("/")
BRAINZ_KEY = os.environ.get("BRAINZ_KEY", "")

mcp = FastMCP("bRAInZ")


def _headers() -> dict[str, str]:
    h: dict[str, str] = {}
    if BRAINZ_KEY:
        h["X-API-Key"] = BRAINZ_KEY
    return h


def _client() -> httpx.Client:
    return httpx.Client(base_url=BRAINZ_URL, headers=_headers(), timeout=30)


def _get(path: str, **params: Any) -> Any:
    with _client() as c:
        r = c.get(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()


def _post(path: str, body: dict[str, Any]) -> Any:
    with _client() as c:
        r = c.post(path, json=body)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def search(query: str, top_k: int = 10, category: str = "", tag: str = "") -> list[dict]:
    """Semantic search across the bRAInZ library.

    Returns ranked results with title, category, URL, and a content snippet.

    Args:
        query:    Search query (natural language or keywords).
        top_k:    Maximum number of results to return (default 10).
        category: Optional category filter (e.g. appsec, redteam, cloud).
        tag:      Optional tag filter.
    """
    body: dict[str, Any] = {"query": query, "top_k": top_k}
    if category:
        body["category"] = category
    if tag:
        body["tags"] = [tag]
    data = _post("/api/library/search", body)
    results = []
    for r in data.get("results", []):
        results.append({
            "item_id": r["item_id"],
            "title": r["title"],
            "category": r.get("category", ""),
            "url": r.get("url", ""),
            "snippet": (r.get("content") or "")[:400],
        })
    return results


@mcp.tool()
def query(question: str, category: str = "", top_k: int = 8) -> dict:
    """Ask a question and get an AI-generated answer grounded in the library.

    Returns the answer text and the source items used.

    Args:
        question: The question to answer.
        category: Optional category to restrict retrieval to.
        top_k:    Number of source chunks to retrieve (default 8).
    """
    body: dict[str, Any] = {"question": question, "top_k": top_k}
    if category:
        body["category"] = category
    data = _post("/api/query", body)
    return {
        "answer": data.get("answer", ""),
        "sources": [
            {"item_id": s["item_id"], "title": s["title"], "url": s.get("url", "")}
            for s in data.get("sources", [])
        ],
    }


@mcp.tool()
def list_library(
    category: str = "",
    tag: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List items in the bRAInZ library with optional filtering.

    Args:
        category: Filter by category (e.g. appsec, redteam, cloud, misc).
        tag:      Filter by tag.
        limit:    Maximum items to return (default 50).
        offset:   Pagination offset (default 0).
    """
    data = _get("/api/library", category=category or None, tag=tag or None,
                limit=limit, offset=offset)
    return {
        "total": data["total"],
        "items": [
            {
                "item_id": it["id"],
                "title": it["title"],
                "category": it["category"],
                "tags": it.get("tags", []),
                "url": it.get("url", ""),
                "added": it.get("added", ""),
                "summary": it.get("summary", ""),
            }
            for it in data.get("items", [])
        ],
    }


@mcp.tool()
def get_item(item_id: str) -> dict:
    """Get full details and content of a single library item by its ID.

    Args:
        item_id: The 8-character item ID (e.g. from search results).
    """
    data = _get(f"/api/items/{item_id}")
    return {
        "item_id": data["id"],
        "title": data["title"],
        "category": data["category"],
        "tags": data.get("tags", []),
        "url": data.get("url", ""),
        "added": data.get("added", ""),
        "summary": data.get("summary", ""),
        "content": data.get("content", ""),
    }


@mcp.tool()
def list_categories() -> list[dict]:
    """List all categories in the library with item counts."""
    data = _get("/api/categories")
    return [{"category": c["name"], "count": c["count"]} for c in data]


@mcp.tool()
def list_tags(limit: int = 50) -> list[dict]:
    """List the most common tags in the library.

    Args:
        limit: Maximum number of tags to return (default 50).
    """
    data = _get("/api/tags")
    return [{"tag": t["name"], "count": t["count"]} for t in data[:limit]]


@mcp.tool()
def list_digest_pages(category: str = "") -> list[dict]:
    """List all Digest pages (curated reference notes).

    Args:
        category: Optional category filter.
    """
    data = _get("/api/digest/pages")
    pages = []
    for p in data:
        if category and p.get("category") != category:
            continue
        pages.append({
            "page_id": p["page_id"],
            "title": p["title"],
            "category": p["category"],
            "tags": p.get("tags", []),
            "updated": p.get("updated", ""),
            "word_count": p.get("word_count", 0),
        })
    return pages


@mcp.tool()
def get_digest_page(page_id: str) -> dict:
    """Get the full content of a Digest page.

    Args:
        page_id: Page ID in the format "category/slug" (e.g. "redteam/sliver").
    """
    data = _get(f"/api/digest/pages/{page_id}")
    return {
        "page_id": data["page_id"],
        "title": data["title"],
        "category": data["category"],
        "tags": data.get("tags", []),
        "source_url": data.get("source_url", ""),
        "updated": data.get("updated", ""),
        "content": data.get("content", ""),
    }


@mcp.tool()
def health() -> dict:
    """Check bRAInZ status and get basic stats (total items, categories, LLM provider)."""
    data = _get("/api/health")
    return {
        "status": data["status"],
        "total_items": data["total_items"],
        "categories": data["categories"],
        "llm_provider": data["llm_provider"],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
