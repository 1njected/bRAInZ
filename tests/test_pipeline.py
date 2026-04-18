"""End-to-end pipeline integration tests — ingest → classify → save → chunk → embed."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

TESTDATA = Path(__file__).parent / "testdata"
PDF_SMALL = TESTDATA / "MS-IR-Guidebook-Final.pdf"


# ---------------------------------------------------------------------------
# ingest_text_pipeline
# ---------------------------------------------------------------------------

class TestTextPipeline:
    @pytest.mark.asyncio
    async def test_text_pipeline_returns_item_id(self, data_dir, mock_llm, index):
        from pipeline import ingest_text_pipeline
        result = await ingest_text_pipeline(
            "Test Article", "This is the body of the test article.",
            category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        assert "item_id" in result
        assert result["item_id"]

    @pytest.mark.asyncio
    async def test_text_pipeline_item_indexed(self, data_dir, mock_llm, index):
        from pipeline import ingest_text_pipeline
        result = await ingest_text_pipeline(
            "Indexed Article", "Body content here.",
            category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        item_id = result["item_id"]
        assert index.get(item_id) is not None

    @pytest.mark.asyncio
    async def test_text_pipeline_files_created(self, data_dir, mock_llm, index):
        from pipeline import ingest_text_pipeline
        result = await ingest_text_pipeline(
            "File Article", "Article body content.",
            category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        # At least one content.md should exist somewhere under library/
        content_files = list((data_dir / "library").glob("**/content.md"))
        assert len(content_files) >= 1

    @pytest.mark.asyncio
    async def test_text_pipeline_not_duplicate(self, data_dir, mock_llm, index):
        from pipeline import ingest_text_pipeline
        result = await ingest_text_pipeline(
            "Unique Article", "Unique body that has not been ingested.",
            category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        assert result["duplicate"] is False

    @pytest.mark.asyncio
    async def test_text_pipeline_dedup(self, data_dir, mock_llm, index):
        from pipeline import ingest_text_pipeline
        body = "Duplicate article body content that is identical."
        # First ingest
        r1 = await ingest_text_pipeline(
            "Original", body, category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        # Second ingest of same content
        r2 = await ingest_text_pipeline(
            "Duplicate Title", body, category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        assert r2["duplicate"] is True
        assert r2["item_id"] == r1["item_id"]

    @pytest.mark.asyncio
    async def test_text_pipeline_manual_category_used(self, data_dir, mock_llm, index):
        from pipeline import ingest_text_pipeline
        result = await ingest_text_pipeline(
            "Manual Cat", "body",
            category="appsec", tags=["xss"],
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        assert result["category"] == "appsec"
        assert "xss" in result["tags"]

    @pytest.mark.asyncio
    async def test_text_pipeline_llm_classifies_when_no_category(self, data_dir, mock_llm, index):
        from pipeline import ingest_text_pipeline
        result = await ingest_text_pipeline(
            "Auto Classified", "body",
            category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        # mock_llm returns netsec
        assert result["category"] == "netsec"

    @pytest.mark.asyncio
    async def test_text_pipeline_embedding_created(self, data_dir, mock_llm, index):
        from pipeline import ingest_text_pipeline
        result = await ingest_text_pipeline(
            "Embedded Article", "This body should be embedded.",
            category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        item_id = result["item_id"]
        npz_file = data_dir / "embeddings" / f"{item_id}.npz"
        assert npz_file.exists()

    @pytest.mark.asyncio
    async def test_text_pipeline_with_url(self, data_dir, mock_llm, index):
        from pipeline import ingest_text_pipeline
        result = await ingest_text_pipeline(
            "URL Article", "body",
            category=None, tags=None, url="https://example.com/article",
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        meta = index.get(result["item_id"])
        assert meta["url"] == "https://example.com/article"

    @pytest.mark.asyncio
    async def test_text_pipeline_returns_title(self, data_dir, mock_llm, index):
        from pipeline import ingest_text_pipeline
        result = await ingest_text_pipeline(
            "My Title", "body",
            category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        assert result["title"] == "My Title"


# ---------------------------------------------------------------------------
# ingest_pdf_pipeline
# ---------------------------------------------------------------------------

class TestPdfPipeline:
    @pytest.mark.asyncio
    async def test_pdf_pipeline_returns_item_id(self, data_dir, mock_llm, index):
        from pipeline import ingest_pdf_pipeline
        result = await ingest_pdf_pipeline(
            str(PDF_SMALL), "MS-IR-Guidebook-Final.pdf",
            category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        assert "item_id" in result
        assert result["item_id"]

    @pytest.mark.asyncio
    async def test_pdf_pipeline_item_indexed(self, data_dir, mock_llm, index):
        from pipeline import ingest_pdf_pipeline
        result = await ingest_pdf_pipeline(
            str(PDF_SMALL), "MS-IR-Guidebook-Final.pdf",
            category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        assert index.get(result["item_id"]) is not None

    @pytest.mark.asyncio
    async def test_pdf_pipeline_content_type_is_pdf(self, data_dir, mock_llm, index):
        from pipeline import ingest_pdf_pipeline
        result = await ingest_pdf_pipeline(
            str(PDF_SMALL), "MS-IR-Guidebook-Final.pdf",
            category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        meta = index.get(result["item_id"])
        assert meta["content_type"] == "pdf"

    @pytest.mark.asyncio
    async def test_pdf_pipeline_dedup(self, data_dir, mock_llm, index):
        from pipeline import ingest_pdf_pipeline
        r1 = await ingest_pdf_pipeline(
            str(PDF_SMALL), "original.pdf",
            category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        r2 = await ingest_pdf_pipeline(
            str(PDF_SMALL), "copy.pdf",
            category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )
        assert r2["duplicate"] is True
        assert r2["item_id"] == r1["item_id"]


# ---------------------------------------------------------------------------
# _dedup_check helper
# ---------------------------------------------------------------------------

class TestDedupCheck:
    @pytest.mark.asyncio
    async def test_no_match_returns_none(self, data_dir, mock_llm, index):
        from pipeline import _dedup_check
        result = _dedup_check("unique content that has never been seen", index, "title")
        assert result is None

    @pytest.mark.asyncio
    async def test_match_returns_duplicate_dict(self, data_dir, mock_llm, index):
        from pipeline import ingest_text_pipeline, _dedup_check
        from utils import content_hash

        body = "Content for dedup test body."
        await ingest_text_pipeline(
            "Original", body, category=None, tags=None,
            llm=mock_llm, index=index, data_dir=data_dir,
        )

        result = _dedup_check(body, index, "Different Title")
        assert result is not None
        assert result["duplicate"] is True
        assert "item_id" in result


# ---------------------------------------------------------------------------
# _classify_or_manual helper
# ---------------------------------------------------------------------------

class TestClassifyOrManual:
    @pytest.mark.asyncio
    async def test_manual_category_skips_llm(self, data_dir, mock_llm, index):
        from pipeline import _classify_or_manual
        from unittest.mock import AsyncMock

        # Replace llm.complete_classify with one that fails if called
        mock_llm.complete_classify = AsyncMock(side_effect=AssertionError("LLM should not be called"))

        cat, tags, summary, classified_by = await _classify_or_manual(
            "Title", "body", mock_llm,
            category="redteam", tags=["kerberoast"],
        )
        assert cat == "redteam"
        assert "kerberoast" in tags
        assert classified_by == "manual"

    @pytest.mark.asyncio
    async def test_no_category_calls_llm(self, data_dir, mock_llm, index):
        from pipeline import _classify_or_manual

        cat, tags, summary, classified_by = await _classify_or_manual(
            "Title", "body content", mock_llm,
            category=None, tags=None, data_dir=data_dir, index=index,
        )
        assert cat  # some category returned
        assert classified_by != "manual"
