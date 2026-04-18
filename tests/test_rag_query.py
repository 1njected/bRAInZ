"""Tests for rag/query.py — RAG answer generation, source attribution, empty results."""

import math
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


# ---------------------------------------------------------------------------
# Fixture: a seeded VectorIndex with one item
# ---------------------------------------------------------------------------

async def _seed_item(data_dir, mock_llm, index, title="Test Article", body="This is test content about security."):
    """Ingest one text item and return its item_id."""
    from pipeline import ingest_text_pipeline
    result = await ingest_text_pipeline(
        title, body, category="netsec", tags=["test"],
        llm=mock_llm, index=index, data_dir=data_dir,
    )
    return result["item_id"]


async def _build_vector_index(data_dir):
    from rag.embedder import rebuild_vector_index
    from rag.search import VectorIndex
    rebuild_vector_index(data_dir)
    vi = VectorIndex(data_dir)
    vi.load()
    return vi


# ---------------------------------------------------------------------------
# Empty knowledge base
# ---------------------------------------------------------------------------

class TestRagQueryEmpty:
    @pytest.mark.asyncio
    async def test_empty_index_returns_no_content_message(self, data_dir, mock_llm, index):
        from rag.query import rag_query
        from rag.search import VectorIndex

        vi = VectorIndex(data_dir)
        # Don't load — no vectors exist

        result = await rag_query("What is XSS?", mock_llm, vi, index, data_dir=data_dir)

        assert "answer" in result
        assert "sources" in result
        assert result["sources"] == []
        assert len(result["answer"]) > 0

    @pytest.mark.asyncio
    async def test_empty_result_has_tools_key(self, data_dir, mock_llm, index):
        from rag.query import rag_query
        from rag.search import VectorIndex

        vi = VectorIndex(data_dir)

        result = await rag_query("question", mock_llm, vi, index, data_dir=data_dir)
        assert "tools" in result


# ---------------------------------------------------------------------------
# With seeded data
# ---------------------------------------------------------------------------

class TestRagQueryWithData:
    @pytest.mark.asyncio
    async def test_returns_answer_and_sources(self, data_dir, mock_llm, index):
        from rag.query import rag_query

        await _seed_item(data_dir, mock_llm, index)
        vi = await _build_vector_index(data_dir)

        result = await rag_query("Tell me about security", mock_llm, vi, index, data_dir=data_dir)

        assert "answer" in result
        assert "sources" in result
        assert isinstance(result["answer"], str)
        assert len(result["answer"]) > 0

    @pytest.mark.asyncio
    async def test_sources_have_required_fields(self, data_dir, mock_llm, index):
        from rag.query import rag_query

        await _seed_item(data_dir, mock_llm, index, title="Source Article")
        vi = await _build_vector_index(data_dir)

        result = await rag_query("security", mock_llm, vi, index, data_dir=data_dir)

        for source in result["sources"]:
            assert "item_id" in source
            assert "title" in source
            assert "relevance_score" in source

    @pytest.mark.asyncio
    async def test_sources_relevance_score_is_float(self, data_dir, mock_llm, index):
        from rag.query import rag_query

        await _seed_item(data_dir, mock_llm, index)
        vi = await _build_vector_index(data_dir)

        result = await rag_query("question", mock_llm, vi, index, data_dir=data_dir)

        for source in result.get("sources", []) + result.get("tools", []):
            assert isinstance(source["relevance_score"], (int, float))

    @pytest.mark.asyncio
    async def test_result_has_thinking_key(self, data_dir, mock_llm, index):
        from rag.query import rag_query

        await _seed_item(data_dir, mock_llm, index)
        vi = await _build_vector_index(data_dir)

        result = await rag_query("question", mock_llm, vi, index, data_dir=data_dir)
        assert "thinking" in result

    @pytest.mark.asyncio
    async def test_llm_called_with_question_in_prompt(self, data_dir, mock_llm, index):
        from rag.query import rag_query

        await _seed_item(data_dir, mock_llm, index)
        vi = await _build_vector_index(data_dir)

        captured_prompt = {}

        async def capturing_complete(system, prompt, max_tokens=4096):
            captured_prompt["system"] = system
            captured_prompt["prompt"] = prompt
            return "Test answer"

        async def capturing_complete_with_thinking(system, prompt, max_tokens=4096):
            captured_prompt["system"] = system
            captured_prompt["prompt"] = prompt
            return "Test answer", ""

        mock_llm.complete = capturing_complete
        mock_llm.complete_with_thinking = capturing_complete_with_thinking

        question = "How does kerberoasting work?"
        await rag_query(question, mock_llm, vi, index, data_dir=data_dir)

        assert question in captured_prompt.get("prompt", "")

    @pytest.mark.asyncio
    async def test_multiple_items_deduped_in_sources(self, data_dir, mock_llm, index):
        """The same item_id should appear only once in sources even if multiple chunks match."""
        from rag.query import rag_query
        from pipeline import ingest_text_pipeline

        # Ingest one item with enough content to produce multiple chunks
        long_body = " ".join(["Security vulnerability analysis. " * 20] * 5)
        await ingest_text_pipeline(
            "Long Article", long_body, category="netsec", tags=["vuln"],
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        vi = await _build_vector_index(data_dir)

        result = await rag_query("security", mock_llm, vi, index, data_dir=data_dir, top_k=10)

        all_items = result["sources"] + result["tools"]
        item_ids = [s["item_id"] for s in all_items]
        assert len(item_ids) == len(set(item_ids)), "Duplicate item_ids in sources/tools"


# ---------------------------------------------------------------------------
# GitHub repo → tools vs sources routing
# ---------------------------------------------------------------------------

class TestRagQueryToolsRouting:
    @pytest.mark.asyncio
    async def test_github_url_goes_to_tools(self, data_dir, mock_llm, index):
        from rag.query import rag_query
        from pipeline import ingest_text_pipeline

        # Ingest as a starred repo (title matches "owner/repo" pattern, URL is github.com)
        await ingest_text_pipeline(
            "owner/awesome-tool", "A great security tool for pentesting.",
            category="netsec", tags=["tool"],
            url="https://github.com/owner/awesome-tool",
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        vi = await _build_vector_index(data_dir)

        result = await rag_query("tool", mock_llm, vi, index, data_dir=data_dir)

        tools_item_ids = {t["item_id"] for t in result.get("tools", [])}
        source_item_ids = {s["item_id"] for s in result.get("sources", [])}

        # The github item should appear in tools, not sources
        all_ingested = list(index.all_items().keys())
        github_id = next((iid for iid in all_ingested
                          if "github.com" in (index.get(iid) or {}).get("url", "")), None)
        if github_id and github_id in tools_item_ids | source_item_ids:
            assert github_id in tools_item_ids
            assert github_id not in source_item_ids

    @pytest.mark.asyncio
    async def test_non_github_url_goes_to_sources(self, data_dir, mock_llm, index):
        from rag.query import rag_query
        from pipeline import ingest_text_pipeline

        await ingest_text_pipeline(
            "Blog Post", "Security research content.",
            category="netsec", tags=["research"],
            url="https://blog.example.com/post",
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        vi = await _build_vector_index(data_dir)

        result = await rag_query("research", mock_llm, vi, index, data_dir=data_dir)

        all_ingested = list(index.all_items().keys())
        blog_id = next((iid for iid in all_ingested
                        if "blog.example.com" in (index.get(iid) or {}).get("url", "")), None)
        if blog_id:
            source_ids = {s["item_id"] for s in result.get("sources", [])}
            tools_ids = {t["item_id"] for t in result.get("tools", [])}
            if blog_id in source_ids | tools_ids:
                assert blog_id in source_ids
                assert blog_id not in tools_ids


# ---------------------------------------------------------------------------
# Category / tag filtering
# ---------------------------------------------------------------------------

class TestRagQueryFiltering:
    @pytest.mark.asyncio
    async def test_category_filter_limits_results(self, data_dir, mock_llm, index):
        from rag.query import rag_query
        from pipeline import ingest_text_pipeline

        # Ingest into two different categories
        await ingest_text_pipeline(
            "Netsec Article", "Network security content.",
            category="netsec", tags=["network"],
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        await ingest_text_pipeline(
            "Appsec Article", "Application security content.",
            category="appsec", tags=["web"],
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        vi = await _build_vector_index(data_dir)

        result = await rag_query(
            "security", mock_llm, vi, index,
            data_dir=data_dir, category="netsec",
        )

        # All returned sources should be from netsec category
        all_results = result.get("sources", []) + result.get("tools", [])
        for item in all_results:
            meta = index.get(item["item_id"])
            if meta:
                assert meta.get("category") == "netsec"
