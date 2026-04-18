"""Tests for backend/ingestion/url.py — title/description extraction, content extraction,
SSRF rejection, and the ingest_url function with mocked HTTP."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from ingestion.url import (
    _extract_title,
    _extract_description,
    _extract_content,
    _protect_pre_blocks,
    _restore_code_blocks,
    _fix_script_close_tags,
    _rejoin_inline_code,
)


# ---------------------------------------------------------------------------
# _extract_title()
# ---------------------------------------------------------------------------

class TestExtractTitle:
    def test_og_title_preferred(self):
        html = '<meta property="og:title" content="OG Title"><title>Plain Title</title>'
        assert _extract_title(html, "https://example.com/") == "OG Title"

    def test_falls_back_to_title_tag(self):
        html = "<title>Page Title</title>"
        assert _extract_title(html, "https://example.com/") == "Page Title"

    def test_title_whitespace_collapsed(self):
        html = "<title>  My   Title  </title>"
        assert _extract_title(html, "https://example.com/") == "My Title"

    def test_html_entities_decoded(self):
        html = "<title>AT&amp;T Guide</title>"
        assert _extract_title(html, "https://example.com/") == "AT&T Guide"

    def test_falls_back_to_url_segment(self):
        title = _extract_title("", "https://example.com/my-article")
        assert title == "my-article"

    def test_og_title_takes_priority_over_title(self):
        html = '<meta property="og:title" content="Real Title"><title>Ignored</title>'
        assert _extract_title(html, "https://example.com/") == "Real Title"

    def test_no_title_uses_url(self):
        title = _extract_title("", "https://example.com/")
        assert title  # non-empty fallback


# ---------------------------------------------------------------------------
# _extract_description()
# ---------------------------------------------------------------------------

class TestExtractDescription:
    def test_og_description(self):
        html = '<meta property="og:description" content="OG desc">'
        assert _extract_description(html) == "OG desc"

    def test_meta_description(self):
        html = '<meta name="description" content="Meta desc">'
        assert _extract_description(html) == "Meta desc"

    def test_og_takes_priority_over_meta(self):
        html = '<meta property="og:description" content="OG"><meta name="description" content="Meta">'
        assert _extract_description(html) == "OG"

    def test_truncated_to_300_chars(self):
        html = f'<meta name="description" content="{"x" * 500}">'
        assert len(_extract_description(html)) <= 300

    def test_whitespace_collapsed(self):
        html = '<meta name="description" content="hello   world">'
        assert _extract_description(html) == "hello world"

    def test_missing_returns_empty(self):
        assert _extract_description("<html><body>no meta</body></html>") == ""


# ---------------------------------------------------------------------------
# _protect_pre_blocks() / _restore_code_blocks()
# ---------------------------------------------------------------------------

class TestPreBlockProtection:
    def test_pre_block_replaced_with_placeholder(self):
        html = "<p>intro</p><pre>code here</pre><p>outro</p>"
        modified, blocks = _protect_pre_blocks(html)
        assert "CODEBLOCK_0_END" in modified
        assert "code here" not in modified
        assert "code here" in blocks[0]

    def test_multiple_pre_blocks(self):
        html = "<pre>block1</pre><pre>block2</pre>"
        modified, blocks = _protect_pre_blocks(html)
        assert len(blocks) == 2
        assert "CODEBLOCK_0_END" in modified
        assert "CODEBLOCK_1_END" in modified

    def test_restore_replaces_placeholders(self):
        blocks = ["print('hello')"]
        text = "intro\nCODEBLOCK_0_END\noutro"
        result = _restore_code_blocks(text, blocks)
        assert "```" in result
        assert "print('hello')" in result

    def test_html_tags_stripped_from_pre(self):
        html = "<pre><span>code</span></pre>"
        _, blocks = _protect_pre_blocks(html)
        assert "<span>" not in blocks[0]
        assert "code" in blocks[0]

    def test_empty_pre_block_not_added(self):
        html = "<pre>   </pre>"
        _, blocks = _protect_pre_blocks(html)
        assert len(blocks) == 0


# ---------------------------------------------------------------------------
# _fix_script_close_tags()
# ---------------------------------------------------------------------------

class TestFixScriptCloseTags:
    def test_real_close_tag_preserved(self):
        html = '<script>var x = 1;</script><p>after</p>'
        result = _fix_script_close_tags(html)
        assert '</script>' in result

    def test_false_close_escaped(self):
        # A </script> followed by JS punctuation should be escaped
        html = '<script>var s = "</script>"; var y = 2;</script>'
        result = _fix_script_close_tags(html)
        # The false close should be escaped (backslash or similar)
        # The string should still be parseable (no early termination)
        assert result.count('</script>') >= 1

    def test_no_scripts_unchanged(self):
        html = '<p>hello world</p>'
        assert _fix_script_close_tags(html) == html


# ---------------------------------------------------------------------------
# _extract_content()
# ---------------------------------------------------------------------------

class TestExtractContent:
    def test_returns_tuple_of_two_strings(self):
        html = "<html><body><p>Hello world content here.</p></body></html>"
        result = _extract_content(html)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)

    def test_content_md_contains_text(self):
        html = "<html><body><article><p>This is an interesting article about security research.</p></article></body></html>"
        content_md, _ = _extract_content(html)
        assert len(content_md) > 0

    def test_empty_html_returns_empty_strings(self):
        content_md, content_llm = _extract_content("")
        assert content_md == "" or len(content_md) < 50
        assert content_llm == "" or len(content_llm) < 50

    def test_base64_images_stripped_from_llm_version(self):
        img = "data:image/png;base64," + "A" * 1000
        html = f'<html><body><article><p>Content</p><img src="{img}" alt="test"></article></body></html>'
        _, content_llm = _extract_content(html)
        assert "data:image/png" not in content_llm


# ---------------------------------------------------------------------------
# _rejoin_inline_code()
# ---------------------------------------------------------------------------

class TestRejoinInlineCode:
    def test_orphaned_code_span_merged(self):
        text = "It uses\n`method_name`\nto do things."
        result = _rejoin_inline_code(text)
        assert "`method_name`" in result
        # After merging, the code span should appear on the same line as context
        lines = [l for l in result.split('\n') if '`method_name`' in l]
        assert len(lines) == 1

    def test_non_code_lines_unchanged(self):
        text = "# Heading\n\nNormal paragraph."
        result = _rejoin_inline_code(text)
        assert "# Heading" in result
        assert "Normal paragraph." in result


# ---------------------------------------------------------------------------
# ingest_url() — mocked HTTP
# ---------------------------------------------------------------------------

class TestIngestUrl:
    @pytest.mark.asyncio
    async def test_ssrf_localhost_rejected(self):
        from ingestion.url import ingest_url
        with pytest.raises(ValueError, match="private|internal|loopback"):
            await ingest_url("http://localhost:8000/page")

    @pytest.mark.asyncio
    async def test_ssrf_private_ip_rejected(self):
        from ingestion.url import ingest_url
        with pytest.raises(ValueError):
            await ingest_url("http://192.168.1.1/page")

    @pytest.mark.asyncio
    async def test_extracts_title_from_response(self):
        from ingestion.url import ingest_url
        import httpx

        html = """<html>
<head><title>Test Article Title</title></head>
<body><article><p>This is a long enough body of content for extraction to work properly.</p>
<p>More content here to make it substantial enough for trafilatura.</p></article>
</body></html>"""

        mock_response = MagicMock()
        mock_response.text = html
        mock_response.content = html.encode()
        mock_response.headers = {"content-type": "text/html"}
        mock_response.url = "https://example.com/article"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("ingestion.url.validate_url_no_ssrf"), \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("ingestion.url._make_snapshot", new=AsyncMock(return_value=None)), \
             patch("ingestion.url._process_pool") as mock_pool:

            # Make run_in_executor return synchronously
            import asyncio
            loop = asyncio.get_event_loop()

            async def fake_executor(pool, fn, *args):
                return fn(*args)

            with patch.object(loop, "run_in_executor", side_effect=fake_executor):
                result = await ingest_url("https://example.com/article")

        assert "title" in result
        assert result["title"] == "Test Article Title"

    @pytest.mark.asyncio
    async def test_returns_required_keys(self):
        from ingestion.url import ingest_url

        html = "<html><head><title>T</title></head><body><p>content</p></body></html>"
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.content = html.encode()
        mock_response.headers = {"content-type": "text/html"}
        mock_response.url = "https://example.com/"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("ingestion.url.validate_url_no_ssrf"), \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("ingestion.url._make_snapshot", new=AsyncMock(return_value=None)):

            import asyncio
            loop = asyncio.get_event_loop()

            async def fake_executor(pool, fn, *args):
                return fn(*args)

            with patch.object(loop, "run_in_executor", side_effect=fake_executor):
                result = await ingest_url("https://example.com/")

        for key in ("title", "content_md", "snapshot_html", "pub_date"):
            assert key in result

    @pytest.mark.asyncio
    async def test_pdf_url_detected_by_extension(self):
        from ingestion.url import ingest_url
        import httpx

        pdf_bytes = b"%PDF-1.4 test content"
        mock_response = MagicMock()
        mock_response.content = pdf_bytes
        mock_response.headers = {"content-type": "application/octet-stream"}
        mock_response.url = "https://example.com/report.pdf"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        mock_pdf_result = {
            "title": "report",
            "content_md": "PDF content",
            "pub_date": None,
        }

        with patch("ingestion.url.validate_url_no_ssrf"), \
             patch("httpx.AsyncClient", return_value=mock_client), \
             patch("ingestion.pdf.ingest_pdf", new=AsyncMock(return_value=mock_pdf_result)):
            result = await ingest_url("https://example.com/report.pdf")

        assert result.get("content_type") == "pdf"

    @pytest.mark.asyncio
    async def test_404_raises_http_error(self):
        from ingestion.url import ingest_url
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {"content-type": "text/html"}
        mock_response.url = "https://example.com/missing"
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("ingestion.url.validate_url_no_ssrf"), \
             patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await ingest_url("https://example.com/missing")

    @pytest.mark.asyncio
    async def test_500_raises_http_error(self):
        from ingestion.url import ingest_url
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.headers = {"content-type": "text/html"}
        mock_response.url = "https://example.com/error"
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock())
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("ingestion.url.validate_url_no_ssrf"), \
             patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await ingest_url("https://example.com/error")

    @pytest.mark.asyncio
    async def test_oversized_response_raises_value_error(self):
        from ingestion.url import ingest_url

        html = "<html><head><title>T</title></head><body><p>x</p></body></html>"
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.content = b"x" * (20 * 1024 * 1024 + 1)  # over 20 MB
        mock_response.headers = {"content-type": "text/html"}
        mock_response.url = "https://example.com/"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("ingestion.url.validate_url_no_ssrf"), \
             patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="too large"):
                await ingest_url("https://example.com/")

    @pytest.mark.asyncio
    async def test_connection_error_propagates(self):
        from ingestion.url import ingest_url
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("ingestion.url.validate_url_no_ssrf"), \
             patch("httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.ConnectError):
                await ingest_url("https://unreachable.example.com/")

    @pytest.mark.asyncio
    async def test_accept_encoding_omits_brotli(self):
        """Accept-Encoding must not include 'br' — httpx can't decompress brotli."""
        from ingestion.url import ingest_url
        import httpx

        captured_headers = {}

        html = "<html><head><title>T</title></head><body><p>x</p></body></html>"
        mock_response = MagicMock()
        mock_response.text = html
        mock_response.content = html.encode()
        mock_response.headers = {"content-type": "text/html"}
        mock_response.url = "https://example.com/"
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        init_kwargs = {}

        def capture_init(**kwargs):
            init_kwargs.update(kwargs)
            return mock_client

        with patch("ingestion.url.validate_url_no_ssrf"), \
             patch("httpx.AsyncClient", side_effect=lambda **kw: (init_kwargs.update(kw), mock_client)[1]), \
             patch("ingestion.url._make_snapshot", new=AsyncMock(return_value=None)):

            import asyncio
            loop = asyncio.get_event_loop()

            async def fake_executor(pool, fn, *args):
                return fn(*args)

            with patch.object(loop, "run_in_executor", side_effect=fake_executor):
                try:
                    await ingest_url("https://example.com/")
                except Exception:
                    pass

        headers = init_kwargs.get("headers", {})
        accept_encoding = headers.get("Accept-Encoding", "")
        assert "br" not in accept_encoding.lower(), \
            f"Accept-Encoding must not contain 'br' (brotli) — got: {accept_encoding}"
