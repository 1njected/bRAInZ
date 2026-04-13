"""OPML import/export for RSS feed lists."""

from __future__ import annotations
import defusedxml.ElementTree as ET
import xml.etree.ElementTree as _ET  # used only for serialization (generate_opml)
from typing import Any


def parse_opml(xml_bytes: bytes) -> list[dict[str, str]]:
    """Parse OPML, return list of {title, url}."""
    root = ET.fromstring(xml_bytes)
    feeds = []
    body = root.find("body")
    if body is None:
        return feeds
    for outline in body.iter("outline"):
        url = outline.get("xmlUrl") or outline.get("url")
        if url:
            title = outline.get("title") or outline.get("text") or url
            feeds.append({"title": title, "url": url})
    return feeds


def generate_opml(feeds: list[dict[str, Any]]) -> bytes:
    """Generate OPML XML bytes from a list of feed dicts."""
    opml = _ET.Element("opml", version="2.0")
    head = _ET.SubElement(opml, "head")
    _ET.SubElement(head, "title").text = "bRAInZ RSS Feeds"
    body = _ET.SubElement(opml, "body")
    for feed in feeds:
        _ET.SubElement(body, "outline", attrib={
            "type": "rss",
            "text": feed.get("title", feed.get("url", "")),
            "title": feed.get("title", feed.get("url", "")),
            "xmlUrl": feed.get("url", ""),
        })
    return _ET.tostring(opml, encoding="unicode", xml_declaration=False).encode("utf-8")
