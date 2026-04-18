"""Tests for backend/ingestion/dates.py — year extraction from HTML, text, and URLs."""

import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from ingestion.dates import (
    extract_year_from_html,
    extract_year_from_text,
    extract_year_from_url,
)

_THIS_YEAR = str(datetime.now(timezone.utc).year)


# ---------------------------------------------------------------------------
# extract_year_from_html()
# ---------------------------------------------------------------------------

class TestExtractYearFromHtml:
    # Meta tag patterns
    def test_article_published_time_meta(self):
        html = '<meta property="article:published_time" content="2023-08-15T12:00:00Z">'
        assert extract_year_from_html(html, "https://example.com/") == "2023"

    def test_article_published_time_reversed_attrs(self):
        html = '<meta content="2022-05-01" property="article:published_time">'
        assert extract_year_from_html(html, "https://example.com/") == "2022"

    def test_dc_date_meta(self):
        html = '<meta name="DC.date" content="2021-03-10">'
        assert extract_year_from_html(html, "https://example.com/") == "2021"

    def test_pubdate_meta(self):
        html = '<meta name="pubdate" content="2020-12-01">'
        assert extract_year_from_html(html, "https://example.com/") == "2020"

    def test_itemprop_date_published(self):
        html = '<meta itemprop="datePublished" content="2019-07-04">'
        assert extract_year_from_html(html, "https://example.com/") == "2019"

    # JSON-LD
    def test_json_ld_date_published(self):
        html = '<script type="application/ld+json">{"datePublished": "2024-01-15"}</script>'
        assert extract_year_from_html(html, "https://example.com/") == "2024"

    # <time> element
    def test_time_element_datetime(self):
        html = '<time datetime="2023-06-01">June 1, 2023</time>'
        assert extract_year_from_html(html, "https://example.com/") == "2023"

    # URL fallback
    def test_falls_back_to_url(self):
        html = "<html><body>no date metadata</body></html>"
        assert extract_year_from_html(html, "https://example.com/blog/2021/post") == "2021"

    # Priority: meta beats JSON-LD
    def test_meta_takes_priority_over_json_ld(self):
        html = (
            '<meta property="article:published_time" content="2023-01-01">'
            '<script>{"datePublished": "2024-01-01"}</script>'
        )
        assert extract_year_from_html(html, "https://example.com/") == "2023"

    # Invalid year rejected
    def test_year_before_2000_rejected(self):
        html = '<meta property="article:published_time" content="1999-01-01">'
        # Falls through to URL or None
        result = extract_year_from_html(html, "https://example.com/")
        assert result != "1999"

    def test_future_year_rejected(self):
        html = '<meta property="article:published_time" content="2099-01-01">'
        result = extract_year_from_html(html, "https://example.com/")
        assert result != "2099"

    def test_no_date_returns_none(self):
        result = extract_year_from_html("<html><body>no dates</body></html>", "https://example.com/")
        assert result is None


# ---------------------------------------------------------------------------
# extract_year_from_text()
# ---------------------------------------------------------------------------

class TestExtractYearFromText:
    # Tier 1: publication keywords
    def test_published_keyword(self):
        assert extract_year_from_text("Published: 15 March 2023") == "2023"

    def test_first_published(self):
        assert extract_year_from_text("First published January 2021") == "2021"

    def test_released_keyword(self):
        assert extract_year_from_text("Released: 2022-05-10") == "2022"

    def test_posted_keyword(self):
        assert extract_year_from_text("Posted on August 2020") == "2020"

    def test_written_keyword(self):
        assert extract_year_from_text("Written by Alice in 2019") == "2019"

    # Tier 2: update keywords (lower priority than published)
    def test_updated_keyword(self):
        assert extract_year_from_text("Updated: March 2022") == "2022"

    def test_pub_beats_update_keyword(self):
        text = "Updated: 2024\nPublished: 2021"
        assert extract_year_from_text(text) == "2021"

    # Tier 3: month-year without keyword
    def test_month_year_pattern(self):
        assert extract_year_from_text("March 2023") == "2023"

    def test_iso_date(self):
        assert extract_year_from_text("Date: 2022-08-15") == "2022"

    def test_day_month_year(self):
        assert extract_year_from_text("15 September 2024") == "2024"

    # Invalid years
    def test_year_before_2000_ignored(self):
        result = extract_year_from_text("Published: 1998")
        assert result != "1998"

    def test_no_date_returns_none(self):
        assert extract_year_from_text("no dates here at all") is None

    # Earliest year in same tier
    def test_earliest_pub_year_wins(self):
        text = "First published 2021, republished 2023"
        assert extract_year_from_text(text) == "2021"


# ---------------------------------------------------------------------------
# extract_year_from_url()
# ---------------------------------------------------------------------------

class TestExtractYearFromUrl:
    def test_year_in_path_segment(self):
        assert extract_year_from_url("https://example.com/blog/2023/article") == "2023"

    def test_year_with_trailing_slash(self):
        assert extract_year_from_url("https://example.com/2024/") == "2024"

    def test_year_with_hyphen(self):
        assert extract_year_from_url("https://example.com/2022-05-post") == "2022"

    def test_year_in_query_string(self):
        result = extract_year_from_url("https://example.com/page?year=2021")
        assert result == "2021"

    def test_no_year_returns_none(self):
        assert extract_year_from_url("https://example.com/about") is None

    def test_year_before_2000_ignored(self):
        result = extract_year_from_url("https://example.com/1999/post")
        assert result != "1999"

    def test_future_year_ignored(self):
        result = extract_year_from_url("https://example.com/2099/post")
        assert result != "2099"

    def test_four_digit_non_year_ignored(self):
        # 1234 is not in range 2000–present
        result = extract_year_from_url("https://example.com/id/1234/details")
        assert result != "1234"
