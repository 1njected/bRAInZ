"""Date extraction from URLs, HTML metadata, and plain text content.

Returns a 4-digit year string (e.g. '2024') or None.
Priority: HTML meta > JSON-LD > <time> element > content text > URL.
"""

from __future__ import annotations
import re
from datetime import datetime, timezone

# Current year — reject anything in the future or before 2000
_THIS_YEAR = datetime.now(timezone.utc).year
_MIN_YEAR = 2000


def _valid(year: int) -> bool:
    return _MIN_YEAR <= year <= _THIS_YEAR


def _year(s: str) -> str | None:
    try:
        y = int(s[:4])
        return str(y) if _valid(y) else None
    except (ValueError, TypeError):
        return None


def extract_year_from_html(html: str, url: str) -> str | None:
    """Full extraction for HTML pages: meta > JSON-LD > time > text > URL."""
    # 1. HTML meta tags (most reliable)
    meta_patterns = [
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([\d]{4})',
        r'<meta[^>]+content=["\']([\d]{4})[^>]+property=["\']article:published_time["\']',
        r'<meta[^>]+name=["\'](?:date|pubdate|publish[_-]?date|publication[_-]?date|DC\.date)["\'][^>]+content=["\']([\d]{4})',
        r'<meta[^>]+content=["\']([\d]{4})[^>]+name=["\'](?:date|pubdate|publish[_-]?date)',
        r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\']([\d]{4})',
        r'<meta[^>]+content=["\']([\d]{4})[^>]+itemprop=["\']datePublished["\']',
    ]
    for pat in meta_patterns:
        m = re.search(pat, html, re.I)
        if m:
            y = _year(m.group(1))
            if y:
                return y

    # 2. JSON-LD datePublished
    m = re.search(r'"datePublished"\s*:\s*"([\d]{4})', html, re.I)
    if m:
        y = _year(m.group(1))
        if y:
            return y

    # 3. <time> element with datetime attribute
    m = re.search(r'<time[^>]+datetime=["\']([\d]{4})', html, re.I)
    if m:
        y = _year(m.group(1))
        if y:
            return y

    # 4. Text content of the HTML (visible dates)
    text_year = extract_year_from_text(html)
    if text_year:
        return text_year

    # 5. URL fallback
    return extract_year_from_url(url)


def extract_year_from_text(text: str) -> str | None:
    """Find the most likely publication year in plain text.

    Looks for common date patterns like:
      - 'Published: 12 March 2023'
      - 'First published: September 2024'
      - 'January 2024'
      - '2023-08-15'
      - 'Updated: 2024'

    Priority: publication keywords (published/created/released/posted/written/authored) >
    update keywords (updated/modified/revised) > month-year > ISO date.
    Within each tier, returns the earliest year found.
    """
    # Tier 1: explicit publication keywords (highest priority — return earliest match immediately)
    pub_patterns = [
        r'(?:first\s+)?(?:published|released|created|posted|written|authored)[^\d]{0,30}(20\d{2})',
        # "September 2024" following a publication keyword on same/previous line
        r'(?:first\s+)?(?:published|released|created|posted|written|authored)[^\d]{0,60}'
        r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
        r'jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
        r'[^\d]{0,10}(20\d{2})',
    ]

    # Tier 2: update/revision keywords (prefer publication over these)
    update_patterns = [
        r'(?:updated?|modified|revised|last\s+(?:updated?|modified|revised))[^\d]{0,30}(20\d{2})',
        r'(?:updated?|modified|revised)[^\d]{0,60}'
        r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
        r'jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
        r'[^\d]{0,10}(20\d{2})',
    ]

    # Tier 3: month-year and ISO dates without keyword context
    generic_patterns = [
        r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
        r'jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
        r'\s+(\d{1,2},?\s+)?(20\d{2})',
        r'\d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
        r'jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
        r'\s+(20\d{2})',
        r'\b(20\d{2})[-/]\d{2}[-/]\d{2}\b',
    ]

    def _collect(patterns: list[str]) -> list[int]:
        years: list[int] = []
        for pat in patterns:
            for m in re.finditer(pat, text, re.I):
                raw = m.group(m.lastindex or 1)
                ym = re.search(r'(20\d{2})', raw)
                if ym:
                    try:
                        y = int(ym.group(1))
                        if _valid(y):
                            years.append(y)
                    except ValueError:
                        pass
        return years

    pub_years = _collect(pub_patterns)
    if pub_years:
        return str(min(pub_years))  # earliest publication date wins

    update_years = _collect(update_patterns)
    generic_years = _collect(generic_patterns)

    # Prefer earliest update year if no generic context, else earliest generic
    all_fallback = update_years + generic_years
    if all_fallback:
        return str(min(all_fallback))

    return None


def extract_year_from_url(url: str) -> str | None:
    """Extract a 4-digit year from a URL path."""
    # Prefer year in path segments like /2024/ or /2024-05/
    m = re.search(r'/(\d{4})(?:[/\-_]|$)', url)
    if m:
        y = _year(m.group(1))
        if y:
            return y
    # Any 4-digit year in the URL
    for m in re.finditer(r'(20\d{2})', url):
        y = _year(m.group(1))
        if y:
            return y
    return None


def extract_year_from_pdf_metadata(file_path: str) -> str | None:
    """Extract year from PDF document metadata (CreationDate, ModDate, etc.)."""
    try:
        import fitz
        doc = fitz.open(file_path)
        meta = doc.metadata
        doc.close()
        for field in ("creationDate", "modDate"):
            val = (meta.get(field) or "").strip()
            # PDF date format: D:20240115120000
            m = re.search(r'D:(20\d{2})', val)
            if m:
                y = _year(m.group(1))
                if y:
                    return y
        # Also try 'title' and other fields for embedded year
        for field in ("subject", "keywords", "producer", "creator"):
            val = meta.get(field) or ""
            m = re.search(r'(20\d{2})', val)
            if m:
                y = _year(m.group(1))
                if y:
                    return y
    except Exception:
        pass
    return None
