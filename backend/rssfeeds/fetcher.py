"""RSS/Atom feed fetcher using feedparser."""

from __future__ import annotations
import asyncio
import json
import re
from pathlib import Path
from typing import Any


async def fetch_feed(url: str) -> dict[str, Any]:
    """Fetch and parse an RSS/Atom feed.

    Returns:
        {title: str, entries: [{title, url, summary, published, comments_url}]}

    Uses httpx to fetch the raw feed content so that custom User-Agent headers
    are sent (required by Reddit and other sites that block default crawlers).
    Falls back to letting feedparser fetch directly if httpx fails.
    """
    import feedparser
    from config import get_config
    from utils import validate_url_no_ssrf

    validate_url_no_ssrf(url)
    cfg = get_config()
    user_agent = cfg.get("ingestion", {}).get("user_agent", "Mozilla/5.0 (compatible; bRAInZ/0.1)")
    timeout = cfg.get("ingestion", {}).get("request_timeout", 30)

    raw_content: bytes | None = None
    try:
        import httpx
        async with httpx.AsyncClient(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw_content = resp.content
    except Exception:
        pass  # fall through to feedparser direct fetch

    loop = asyncio.get_event_loop()
    if raw_content is not None:
        d = await loop.run_in_executor(None, feedparser.parse, raw_content)
    else:
        d = await loop.run_in_executor(None, feedparser.parse, url)

    is_reddit = bool(re.search(r"reddit\.com", url, re.IGNORECASE))

    raw_entries = []
    for e in d.entries:
        # Prefer content[0].value (full body) over summary when available
        content_html = ""
        if e.get("content"):
            content_html = e["content"][0].get("value", "")
        raw_entries.append({
            "title": e.get("title", ""),
            "url": e.get("link", ""),
            "summary": e.get("summary", ""),
            "content_html": content_html,
            "published": e.get("published", ""),
            "_parsed": e.get("published_parsed") or (0,),
            "_is_reddit": is_reddit,
        })

    raw_entries.sort(key=lambda x: x["_parsed"], reverse=True)

    entries = []
    for e in raw_entries:
        summary_html = e["summary"]
        comments_url: str | None = None

        if e["_is_reddit"]:
            external, comments = _reddit_extract_urls(summary_html, e["url"])
            entry_url = external or e["url"]
            comments_url = comments
        else:
            entry_url = e["url"]

        entries.append({
            "title": e["title"],
            "url": entry_url,
            "summary": _strip_html(summary_html),
            "content": e["content_html"],  # raw HTML, sanitized client-side by DOMPurify
            "published": e["published"],
            "comments_url": comments_url,
        })

    title = d.feed.get("title", url)
    title = _reddit_title(url, title)

    return {
        "title": title,
        "entries": entries,
    }


def save_feed_cache(data_dir: Path, feed_id: str, data: dict[str, Any]) -> None:
    """Save fetched feed data to per-feed JSON cache."""
    cache_dir = data_dir / "rssfeeds"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{feed_id}.json"
    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_feed_cache(data_dir: Path, feed_id: str) -> dict[str, Any] | None:
    """Load cached feed data. Returns None if not found."""
    cache_path = data_dir / "rssfeeds" / f"{feed_id}.json"
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def delete_feed_cache(data_dir: Path, feed_id: str) -> None:
    """Remove the per-feed cache file when a feed is deleted."""
    cache_path = data_dir / "rssfeeds" / f"{feed_id}.json"
    if cache_path.exists():
        cache_path.unlink()


def _reddit_extract_urls(summary_html: str, fallback_url: str) -> tuple[str | None, str | None]:
    """Extract external link and comments URL from Reddit RSS summary HTML.

    Reddit summary contains links like:
      <a href="https://example.com/article">link</a>
      <a href="https://www.reddit.com/r/sub/comments/...">comments</a>
    Returns (external_url, comments_url).
    """
    links = re.findall(r'href=["\']([^"\']+)["\']', summary_html)
    external: str | None = None
    comments: str | None = None
    for link in links:
        if re.search(r"reddit\.com", link, re.IGNORECASE):
            if "/comments/" in link and comments is None:
                comments = link
        else:
            if external is None:
                external = link
    return external, comments


def _reddit_title(url: str, raw_title: str) -> str:
    """For Reddit feeds, return a clean label like 'r/redteamsec'."""
    m = re.search(r"reddit\.com/(?:r|subreddit)/([^/?#.]+)", url, re.IGNORECASE)
    if not m:
        return raw_title
    subs = m.group(1).split("+")
    return f"r/{subs[0]}" if len(subs) == 1 else "r/multi"


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string (best-effort)."""
    return re.sub(r"<[^>]+>", "", text).strip()
