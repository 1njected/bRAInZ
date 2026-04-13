"""Feed subscription storage — reads/writes /data/feeds.yaml."""

from __future__ import annotations
import uuid
from pathlib import Path
from typing import Any

import yaml

_FEEDS_FILE = "feeds.yaml"
_MAX_SEEN = 500  # cap seen_urls per feed to avoid unbounded growth


def _feeds_path(data_dir: Path) -> Path:
    return data_dir / _FEEDS_FILE


def load_feeds(data_dir: Path) -> list[dict[str, Any]]:
    path = _feeds_path(data_dir)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("feeds", [])


def save_feeds(data_dir: Path, feeds: list[dict[str, Any]]) -> None:
    path = _feeds_path(data_dir)
    path.write_text(yaml.dump({"feeds": feeds}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def add_feed(data_dir: Path, url: str, title: str) -> dict[str, Any]:
    feeds = load_feeds(data_dir)
    for f in feeds:
        if f["url"] == url:
            return f
    feed: dict[str, Any] = {
        "id": uuid.uuid4().hex[:8],
        "url": url,
        "title": title,
        "enabled": True,
        "last_fetched": None,
        "last_error": None,
        "seen_urls": [],    # URLs explicitly marked read by the user
        "latest_urls": [],  # URLs from the most recent successful fetch (overwritten each time)
    }
    feeds.append(feed)
    save_feeds(data_dir, feeds)
    return feed


def remove_feed(data_dir: Path, feed_id: str) -> bool:
    feeds = load_feeds(data_dir)
    new_feeds = [f for f in feeds if f["id"] != feed_id]
    if len(new_feeds) == len(feeds):
        return False
    save_feeds(data_dir, new_feeds)
    from rssfeeds.fetcher import delete_feed_cache
    delete_feed_cache(data_dir, feed_id)
    return True


def update_feed(data_dir: Path, feed_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    feeds = load_feeds(data_dir)
    for feed in feeds:
        if feed["id"] == feed_id:
            feed.update(updates)
            save_feeds(data_dir, feeds)
            return feed
    return None


def get_feed(data_dir: Path, feed_id: str) -> dict[str, Any] | None:
    for f in load_feeds(data_dir):
        if f["id"] == feed_id:
            return f
    return None


def set_latest_urls(data_dir: Path, feed_id: str, entry_urls: list[str]) -> None:
    """Overwrite latest_urls with the current feed contents."""
    feeds = load_feeds(data_dir)
    for feed in feeds:
        if feed["id"] == feed_id:
            feed["latest_urls"] = entry_urls
            # Migrate away from old known_urls field if present
            feed.pop("known_urls", None)
            save_feeds(data_dir, feeds)
            return


def mark_all_read(data_dir: Path, feed_id: str, entry_urls: list[str]) -> dict[str, Any] | None:
    """Add entry_urls to seen_urls for a feed."""
    feeds = load_feeds(data_dir)
    for feed in feeds:
        if feed["id"] == feed_id:
            seen = set(feed.get("seen_urls") or [])
            seen.update(entry_urls)
            feed["seen_urls"] = list(seen)[-_MAX_SEEN:]
            save_feeds(data_dir, feeds)
            return feed
    return None
