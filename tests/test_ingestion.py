"""Tests for ingestion modules using real testdata files."""

import pytest
from pathlib import Path

TESTDATA = Path(__file__).parent / "testdata"
PDF_SMALL = TESTDATA / "MS-IR-Guidebook-Final.pdf"
PDF_MEDIUM = TESTDATA / "abusing_wcf_endpoints.pdf"
PDF_LARGE = TESTDATA / "TrimarcBlogPost - Owner or Pwned.pdf"


# ---------------------------------------------------------------------------
# PDF ingestion
# ---------------------------------------------------------------------------

class TestPDFIngestion:
    @pytest.mark.asyncio
    async def test_small_pdf_returns_expected_keys(self):
        from ingestion.pdf import ingest_pdf
        result = await ingest_pdf(str(PDF_SMALL))
        assert "title" in result
        assert "content_md" in result
        assert "page_count" in result

    @pytest.mark.asyncio
    async def test_small_pdf_has_content(self):
        from ingestion.pdf import ingest_pdf
        result = await ingest_pdf(str(PDF_SMALL))
        assert len(result["content_md"]) > 100
        assert result["page_count"] > 0

    @pytest.mark.asyncio
    async def test_small_pdf_title_from_filename(self):
        from ingestion.pdf import ingest_pdf
        result = await ingest_pdf(str(PDF_SMALL), original_filename="MS-IR-Guidebook-Final.pdf")
        # Should derive a human-readable title
        assert len(result["title"]) > 0

    @pytest.mark.asyncio
    async def test_medium_pdf_extracts_text(self):
        from ingestion.pdf import ingest_pdf
        result = await ingest_pdf(str(PDF_MEDIUM), original_filename="abusing_wcf_endpoints.pdf")
        assert result["page_count"] > 0
        assert len(result["content_md"]) > 500

    @pytest.mark.asyncio
    async def test_large_pdf_extracts_text(self):
        from ingestion.pdf import ingest_pdf
        result = await ingest_pdf(str(PDF_LARGE))
        assert result["page_count"] > 0
        assert len(result["content_md"]) > 1000

    @pytest.mark.asyncio
    async def test_missing_pdf_raises(self):
        from ingestion.pdf import ingest_pdf
        with pytest.raises(Exception):
            await ingest_pdf("/nonexistent/path/file.pdf")


# ---------------------------------------------------------------------------
# Text ingestion
# ---------------------------------------------------------------------------

class TestTextIngestion:
    @pytest.mark.asyncio
    async def test_basic_passthrough(self):
        from ingestion.text import ingest_text
        result = await ingest_text("My Note", "This is the body.")
        assert result["title"] == "My Note"
        assert result["content_md"] == "This is the body."

    @pytest.mark.asyncio
    async def test_empty_body(self):
        from ingestion.text import ingest_text
        result = await ingest_text("Empty", "")
        assert result["title"] == "Empty"
        assert result["content_md"] == ""

    @pytest.mark.asyncio
    async def test_multiline_body_preserved(self):
        from ingestion.text import ingest_text
        body = "Line one\n\nLine two\n\nLine three"
        result = await ingest_text("Multi", body)
        assert result["content_md"] == body
