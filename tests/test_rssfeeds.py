"""Regression tests for RSS feed fetching and cache safety.

Covers the failure that wiped populated feeds on "Refresh all": Reddit
rate-limited the fetch, feedparser reported the 429 as a successful parse with
zero entries, and the empty result overwrote the good cache.
"""

import json

import pytest

from rssfeeds.fetcher import (
    FeedFetchError,
    fetch_feed,
    load_feed_cache,
    save_feed_cache,
)

FEED_URL = "https://www.reddit.com/r/netsec/.rss"

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>r/netsec</title>
  <entry>
    <title>Some finding</title>
    <link href="https://www.reddit.com/r/netsec/comments/abc/some_finding/"/>
    <summary type="html">&lt;a href="https://example.com/post"&gt;link&lt;/a&gt;
      &lt;a href="https://www.reddit.com/r/netsec/comments/abc/"&gt;comments&lt;/a&gt;</summary>
    <published>2026-09-07T10:00:00+00:00</published>
  </entry>
</feed>
"""


# ---------------------------------------------------------------------------
# save_feed_cache — never destroy a populated cache
# ---------------------------------------------------------------------------

def test_empty_result_does_not_overwrite_populated_cache(data_dir):
    populated = {"title": "r/netsec", "entries": [{"url": "https://example.com/a"}]}
    assert save_feed_cache(data_dir, "feed1", populated) is True

    assert save_feed_cache(data_dir, "feed1", {"title": "r/netsec", "entries": []}) is False

    assert load_feed_cache(data_dir, "feed1") == populated


def test_empty_result_is_written_when_no_cache_exists(data_dir):
    assert save_feed_cache(data_dir, "feed2", {"title": "r/new", "entries": []}) is True
    assert load_feed_cache(data_dir, "feed2") == {"title": "r/new", "entries": []}


def test_populated_result_overwrites_previous_cache(data_dir):
    save_feed_cache(data_dir, "feed3", {"title": "t", "entries": [{"url": "https://a"}]})
    fresh = {"title": "t", "entries": [{"url": "https://b"}, {"url": "https://c"}]}
    assert save_feed_cache(data_dir, "feed3", fresh) is True
    assert load_feed_cache(data_dir, "feed3") == fresh


def test_cache_file_is_valid_json_on_disk(data_dir):
    save_feed_cache(data_dir, "feed4", {"title": "t", "entries": [{"url": "https://a"}]})
    raw = json.loads((data_dir / "rssfeeds" / "feed4.json").read_text(encoding="utf-8"))
    assert raw["entries"][0]["url"] == "https://a"


# ---------------------------------------------------------------------------
# fetch_feed — a blocked fetch must raise, not return an empty feed
# ---------------------------------------------------------------------------

class _FakeParsed:
    def __init__(self, entries=None, status=None, feed=None):
        self.entries = entries or []
        self.feed = feed if feed is not None else {}
        if status is not None:
            self.status = status


def _patch_httpx_failure(monkeypatch):
    """Make the httpx leg raise so fetch_feed falls back to feedparser."""
    import httpx

    class _FailingClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            raise httpx.HTTPStatusError("429", request=None, response=None)

    monkeypatch.setattr(httpx, "AsyncClient", _FailingClient)


async def test_fallback_http_error_raises_instead_of_returning_empty(monkeypatch, data_dir):
    import feedparser

    _patch_httpx_failure(monkeypatch)
    monkeypatch.setattr(feedparser, "parse", lambda *a, **kw: _FakeParsed(status=429))

    with pytest.raises(FeedFetchError) as exc:
        await fetch_feed(FEED_URL)
    assert "429" in str(exc.value)


async def test_fallback_empty_after_fetch_error_raises(monkeypatch, data_dir):
    import feedparser

    _patch_httpx_failure(monkeypatch)
    monkeypatch.setattr(feedparser, "parse", lambda *a, **kw: _FakeParsed(status=200))

    with pytest.raises(FeedFetchError):
        await fetch_feed(FEED_URL)


async def test_fallback_passes_user_agent_to_feedparser(monkeypatch, data_dir):
    import feedparser

    _patch_httpx_failure(monkeypatch)
    seen = {}

    def _parse(url, **kw):
        seen.update(kw)
        return _FakeParsed(entries=[{"title": "x", "link": "https://a"}], status=200)

    monkeypatch.setattr(feedparser, "parse", _parse)
    await fetch_feed(FEED_URL)
    assert seen.get("agent"), "fallback must send a custom User-Agent"


async def test_successful_httpx_fetch_parses_entries(monkeypatch, data_dir):
    import httpx

    class _OKClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return httpx.Response(200, content=ATOM.encode("utf-8"),
                                  request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", _OKClient)

    data = await fetch_feed(FEED_URL)
    assert data["title"] == "r/netsec"
    assert len(data["entries"]) == 1
    entry = data["entries"][0]
    # Reddit entries resolve to the external link, keeping the comments URL aside
    assert entry["url"] == "https://example.com/post"
    assert entry["comments_url"].startswith("https://www.reddit.com/r/netsec/comments/")


async def test_genuinely_empty_feed_via_httpx_is_not_an_error(monkeypatch, data_dir):
    import httpx

    empty_atom = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Quiet</title></feed>'

    class _OKClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return httpx.Response(200, content=empty_atom,
                                  request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", _OKClient)

    data = await fetch_feed("https://example.com/quiet.rss")
    assert data["entries"] == []
