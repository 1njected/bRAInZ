"""Tests for CLI commands — argument parsing, output, and integration with index."""

import argparse
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs):
    """Build a minimal argparse.Namespace."""
    return argparse.Namespace(**kwargs)


def _mock_deps(data_dir, mock_llm, index):
    """Return a (config, llm, index, data_dir) tuple suitable for patching get_deps."""
    config = MagicMock()
    return config, mock_llm, index, data_dir


# ---------------------------------------------------------------------------
# extract_urls (pure function, no deps)
# ---------------------------------------------------------------------------

class TestExtractUrls:
    def test_extracts_http_and_https(self, tmp_path):
        from cli.import_urls import extract_urls
        f = tmp_path / "links.txt"
        f.write_text("See https://example.com and http://other.org for details.")
        assert "https://example.com" in extract_urls(str(f))
        assert "http://other.org" in extract_urls(str(f))

    def test_deduplicates(self, tmp_path):
        from cli.import_urls import extract_urls
        f = tmp_path / "dup.txt"
        f.write_text("https://example.com\nhttps://example.com\nhttps://example.com\n")
        assert extract_urls(str(f)).count("https://example.com") == 1

    def test_sorted(self, tmp_path):
        from cli.import_urls import extract_urls
        f = tmp_path / "sorted.txt"
        f.write_text("https://zzz.com https://aaa.com https://mmm.com")
        result = extract_urls(str(f))
        assert result == sorted(result)

    def test_strips_trailing_punctuation(self, tmp_path):
        from cli.import_urls import extract_urls
        f = tmp_path / "punct.txt"
        f.write_text("Check https://example.com/path. And https://other.org/x,")
        urls = extract_urls(str(f))
        assert "https://example.com/path" in urls
        assert "https://other.org/x" in urls

    def test_empty_file_returns_empty(self, tmp_path):
        from cli.import_urls import extract_urls
        f = tmp_path / "empty.txt"
        f.write_text("")
        assert extract_urls(str(f)) == []

    def test_no_urls_returns_empty(self, tmp_path):
        from cli.import_urls import extract_urls
        f = tmp_path / "nourl.txt"
        f.write_text("Just plain text with no hyperlinks at all.")
        assert extract_urls(str(f)) == []

    def test_ignores_ftp_scheme(self, tmp_path):
        from cli.import_urls import extract_urls
        f = tmp_path / "ftp.txt"
        f.write_text("ftp://files.example.com/file.zip https://good.com/ok")
        urls = extract_urls(str(f))
        assert not any(u.startswith("ftp://") for u in urls)
        assert "https://good.com/ok" in urls


# ---------------------------------------------------------------------------
# register() — argparse wiring
# ---------------------------------------------------------------------------

class TestRegister:
    def _make_subparsers(self):
        p = argparse.ArgumentParser()
        return p, p.add_subparsers(dest="command")

    def test_stats_registered(self):
        from cli import stats
        _, sub = self._make_subparsers()
        stats.register(sub)

    def test_reindex_registered(self):
        from cli import reindex
        _, sub = self._make_subparsers()
        reindex.register(sub)

    def test_search_registered(self):
        from cli import search
        _, sub = self._make_subparsers()
        search.register(sub)

    def test_query_registered(self):
        from cli import query
        _, sub = self._make_subparsers()
        query.register(sub)

    def test_add_url_registered(self):
        from cli import add_url
        _, sub = self._make_subparsers()
        add_url.register(sub)

    def test_import_urls_registered(self):
        from cli import import_urls
        _, sub = self._make_subparsers()
        import_urls.register(sub)

    def test_search_parses_query_and_category(self):
        from cli import search
        p = argparse.ArgumentParser()
        sub = p.add_subparsers(dest="command")
        search.register(sub)
        args = p.parse_args(["search", "kerberoasting", "--category", "redteam"])
        assert args.query == "kerberoasting"
        assert args.category == "redteam"

    def test_search_default_top_k(self):
        from cli import search
        p = argparse.ArgumentParser()
        sub = p.add_subparsers(dest="command")
        search.register(sub)
        args = p.parse_args(["search", "xss"])
        assert args.top_k == 10

    def test_add_url_parses_tags(self):
        from cli import add_url
        p = argparse.ArgumentParser()
        sub = p.add_subparsers(dest="command")
        add_url.register(sub)
        args = p.parse_args(["add-url", "https://example.com", "--tags", "xss,sqli"])
        assert args.tags == "xss,sqli"
        assert args.url == "https://example.com"

    def test_import_urls_default_rate_limit(self):
        from cli import import_urls
        p = argparse.ArgumentParser()
        sub = p.add_subparsers(dest="command")
        import_urls.register(sub)
        args = p.parse_args(["import-urls", "file.txt"])
        assert args.rate_limit == 1.0

    def test_query_parses_question(self):
        from cli import query
        p = argparse.ArgumentParser()
        sub = p.add_subparsers(dest="command")
        query.register(sub)
        args = p.parse_args(["query", "What is SQL injection?"])
        assert args.question == "What is SQL injection?"


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_empty_index_prints_zero(self, data_dir, mock_llm, index, capsys):
        from cli import stats
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)):
            stats.run(_make_args())
        out = capsys.readouterr().out
        assert "Total items: 0" in out
        assert "Embedded: 0" in out

    def test_counts_per_category(self, data_dir, mock_llm, index, capsys):
        import asyncio
        from pipeline import ingest_text_pipeline
        asyncio.run(ingest_text_pipeline("A", "body a", category="appsec", tags=[], llm=mock_llm, index=index, data_dir=data_dir))
        asyncio.run(ingest_text_pipeline("B", "body b unique", category="appsec", tags=[], llm=mock_llm, index=index, data_dir=data_dir))
        asyncio.run(ingest_text_pipeline("C", "body c content", category="netsec", tags=[], llm=mock_llm, index=index, data_dir=data_dir))

        from cli import stats
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)):
            stats.run(_make_args())
        out = capsys.readouterr().out
        assert "Total items: 3" in out
        assert "appsec" in out
        assert "netsec" in out

    def test_embedded_count(self, data_dir, mock_llm, index, capsys):
        import asyncio
        from pipeline import ingest_text_pipeline
        asyncio.run(ingest_text_pipeline("Embedded", "body content here", category="misc", tags=[], llm=mock_llm, index=index, data_dir=data_dir))

        from cli import stats
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)):
            stats.run(_make_args())
        out = capsys.readouterr().out
        assert "Embedded: 1" in out


# ---------------------------------------------------------------------------
# reindex
# ---------------------------------------------------------------------------

class TestReindex:
    def test_reindex_prints_count(self, data_dir, mock_llm, index, capsys):
        import asyncio
        from pipeline import ingest_text_pipeline
        asyncio.run(ingest_text_pipeline("X", "body x", category="misc", tags=[], llm=mock_llm, index=index, data_dir=data_dir))

        from cli import reindex
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)):
            reindex.run(_make_args())
        out = capsys.readouterr().out
        assert "Reindexed" in out
        assert "1" in out

    def test_reindex_empty_prints_zero(self, data_dir, mock_llm, index, capsys):
        from cli import reindex
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)):
            reindex.run(_make_args())
        out = capsys.readouterr().out
        assert "Reindexed 0" in out


# ---------------------------------------------------------------------------
# add-url
# ---------------------------------------------------------------------------

class TestAddUrl:
    def test_new_url_prints_saved(self, data_dir, mock_llm, index, capsys):
        from cli import add_url

        mock_result = {
            "duplicate": False,
            "item_id": "abc123",
            "category": "appsec",
            "title": "Test Article",
        }

        async def mock_pipeline(**kwargs):
            return mock_result

        args = _make_args(url="https://example.com", category=None, tags=None)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("pipeline.ingest_url_pipeline", mock_pipeline):
            add_url.run(args)

        out = capsys.readouterr().out
        assert "Saved" in out
        assert "appsec" in out
        assert "Test Article" in out

    def test_duplicate_url_prints_duplicate(self, data_dir, mock_llm, index, capsys):
        from cli import add_url

        mock_result = {"duplicate": True, "item_id": "existing123"}

        async def mock_pipeline(**kwargs):
            return mock_result

        args = _make_args(url="https://example.com", category=None, tags=None)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("pipeline.ingest_url_pipeline", mock_pipeline):
            add_url.run(args)

        out = capsys.readouterr().out
        assert "Duplicate" in out
        assert "existing123" in out

    def test_tags_parsed_from_comma_string(self, data_dir, mock_llm, index):
        from cli import add_url

        captured = {}

        async def mock_pipeline(**kwargs):
            captured["tags"] = kwargs.get("tags")
            return {"duplicate": False, "item_id": "x", "category": "misc", "title": "T"}

        args = _make_args(url="https://example.com", category=None, tags="xss,sqli,rce")
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("pipeline.ingest_url_pipeline", mock_pipeline):
            add_url.run(args)

        assert captured["tags"] == ["xss", "sqli", "rce"]

    def test_no_tags_passes_none(self, data_dir, mock_llm, index):
        from cli import add_url

        captured = {}

        async def mock_pipeline(**kwargs):
            captured["tags"] = kwargs.get("tags")
            return {"duplicate": False, "item_id": "x", "category": "misc", "title": "T"}

        args = _make_args(url="https://example.com", category=None, tags=None)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("pipeline.ingest_url_pipeline", mock_pipeline):
            add_url.run(args)

        assert captured["tags"] is None


# ---------------------------------------------------------------------------
# import-urls
# ---------------------------------------------------------------------------

class TestImportUrls:
    def test_no_urls_in_file_prints_message(self, data_dir, mock_llm, index, tmp_path, capsys):
        from cli import import_urls
        f = tmp_path / "empty.txt"
        f.write_text("no urls here")

        args = _make_args(filepath=str(f), category=None, tags=None, rate_limit=0)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)):
            import_urls.run(args)

        out = capsys.readouterr().out
        assert "No URLs found" in out

    def test_prints_found_count(self, data_dir, mock_llm, index, tmp_path, capsys):
        from cli import import_urls
        f = tmp_path / "links.txt"
        f.write_text("https://aaa.com https://bbb.com")

        async def mock_pipeline(**kwargs):
            return {"duplicate": False, "item_id": "x", "category": "misc", "title": "T"}

        args = _make_args(filepath=str(f), category=None, tags=None, rate_limit=0)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("pipeline.ingest_url_pipeline", mock_pipeline):
            import_urls.run(args)

        out = capsys.readouterr().out
        assert "Found 2 unique URLs" in out

    def test_prints_done_summary(self, data_dir, mock_llm, index, tmp_path, capsys):
        from cli import import_urls
        f = tmp_path / "links.txt"
        f.write_text("https://example.com/page1")

        async def mock_pipeline(**kwargs):
            return {"duplicate": False, "item_id": "x", "category": "misc", "title": "T"}

        args = _make_args(filepath=str(f), category=None, tags=None, rate_limit=0)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("pipeline.ingest_url_pipeline", mock_pipeline):
            import_urls.run(args)

        out = capsys.readouterr().out
        assert "Done" in out
        assert "Imported: 1" in out

    def test_failed_url_counted_in_summary(self, data_dir, mock_llm, index, tmp_path, capsys):
        from cli import import_urls
        f = tmp_path / "links.txt"
        f.write_text("https://fail.example.com/page")

        async def mock_pipeline(**kwargs):
            raise RuntimeError("Connection refused")

        args = _make_args(filepath=str(f), category=None, tags=None, rate_limit=0)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("pipeline.ingest_url_pipeline", mock_pipeline):
            import_urls.run(args)

        out = capsys.readouterr().out
        assert "Failed: 1" in out

    def test_duplicate_url_counted_as_skipped(self, data_dir, mock_llm, index, tmp_path, capsys):
        from cli import import_urls
        f = tmp_path / "links.txt"
        f.write_text("https://already.example.com/page")

        async def mock_pipeline(**kwargs):
            return {"duplicate": True, "item_id": "existing"}

        args = _make_args(filepath=str(f), category=None, tags=None, rate_limit=0)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("pipeline.ingest_url_pipeline", mock_pipeline):
            import_urls.run(args)

        out = capsys.readouterr().out
        assert "Skipped: 1" in out


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

class TestSearch:
    def test_no_results_prints_nothing(self, data_dir, mock_llm, index, capsys):
        from cli import search

        async def mock_semantic_search(**kwargs):
            return []

        args = _make_args(query="xss", category=None, top_k=5)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("rag.search.semantic_search", mock_semantic_search):
            search.run(args)

        out = capsys.readouterr().out
        assert out.strip() == ""

    def test_results_printed_with_score_and_title(self, data_dir, mock_llm, index, capsys):
        from cli import search

        async def mock_semantic_search(**kwargs):
            return [
                {"score": 0.95, "title": "XSS Guide", "category": "appsec", "content": "Cross-site scripting basics."},
            ]

        args = _make_args(query="xss", category=None, top_k=5)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("rag.search.semantic_search", mock_semantic_search):
            search.run(args)

        out = capsys.readouterr().out
        assert "0.950" in out
        assert "XSS Guide" in out
        assert "appsec" in out

    def test_category_passed_to_search(self, data_dir, mock_llm, index):
        from cli import search

        captured = {}

        async def mock_semantic_search(**kwargs):
            captured.update(kwargs)
            return []

        args = _make_args(query="pivot", category="redteam", top_k=3)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("rag.search.semantic_search", mock_semantic_search):
            search.run(args)

        assert captured.get("category") == "redteam"
        assert captured.get("top_k") == 3


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

class TestQuery:
    def test_answer_printed(self, data_dir, mock_llm, index, capsys):
        from cli import query

        async def mock_rag_query(**kwargs):
            return {"answer": "SQL injection exploits unsanitised input.", "sources": [], "tools": [], "thinking": ""}

        args = _make_args(question="What is SQL injection?", category=None)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("rag.query.rag_query", mock_rag_query):
            query.run(args)

        out = capsys.readouterr().out
        assert "SQL injection" in out

    def test_sources_printed(self, data_dir, mock_llm, index, capsys):
        from cli import query

        async def mock_rag_query(**kwargs):
            return {
                "answer": "Answer here.",
                "sources": [{"relevance_score": 0.88, "title": "OWASP Top 10"}],
                "tools": [],
                "thinking": "",
            }

        args = _make_args(question="OWASP?", category=None)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("rag.query.rag_query", mock_rag_query):
            query.run(args)

        out = capsys.readouterr().out
        assert "Sources:" in out
        assert "OWASP Top 10" in out
        assert "0.880" in out

    def test_category_passed_to_rag_query(self, data_dir, mock_llm, index):
        from cli import query

        captured = {}

        async def mock_rag_query(**kwargs):
            captured.update(kwargs)
            return {"answer": "ok", "sources": [], "tools": [], "thinking": ""}

        args = _make_args(question="pivoting?", category="redteam")
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("rag.query.rag_query", mock_rag_query):
            query.run(args)

        assert captured.get("category") == "redteam"

    def test_empty_sources_no_source_lines(self, data_dir, mock_llm, index, capsys):
        from cli import query

        async def mock_rag_query(**kwargs):
            return {"answer": "Nothing found.", "sources": [], "tools": [], "thinking": ""}

        args = _make_args(question="q?", category=None)
        with patch("cli.deps.get_deps", return_value=_mock_deps(data_dir, mock_llm, index)), \
             patch("rag.query.rag_query", mock_rag_query):
            query.run(args)

        out = capsys.readouterr().out
        assert "Sources:" in out
        # No source lines after the header
        lines = [l for l in out.splitlines() if l.strip().startswith("[")]
        assert lines == []


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------

class TestMain:
    def test_no_command_exits_nonzero(self):
        from cli import main
        with patch("sys.argv", ["brainz"]), pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code != 0

    def test_all_commands_registered(self):
        import argparse as ap
        from cli import main as cli_main
        import cli as cli_module
        p = ap.ArgumentParser()
        sub = p.add_subparsers(dest="command")
        for mod in (cli_module.add_url, cli_module.import_urls, cli_module.import_pdfs,
                    cli_module.import_images, cli_module.reindex, cli_module.stats,
                    cli_module.search, cli_module.query):
            mod.register(sub)
        # Each command has a handler
        for cmd in ("add-url", "import-urls", "import-pdfs", "import-images",
                    "reindex", "stats", "search", "query"):
            args = p.parse_args([cmd] + (["x"] if cmd in ("add-url", "search") else
                                         ["f.txt"] if cmd == "import-urls" else
                                         ["dir"] if cmd in ("import-pdfs", "import-images") else
                                         ["q"] if cmd == "query" else []))
            assert hasattr(args, "func")
