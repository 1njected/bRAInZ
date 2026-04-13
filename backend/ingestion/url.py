"""URL fetching, content extraction, date detection, and self-contained HTML snapshot."""

from __future__ import annotations
import asyncio
import concurrent.futures
import re
import tempfile
import os
import httpx
from config import get_config
from utils import validate_url_no_ssrf

# Process pool for CPU-bound work that holds the GIL (trafilatura, regex on large HTML)
_process_pool = concurrent.futures.ProcessPoolExecutor(max_workers=2)


def _ingestion_cfg() -> dict:
    return get_config().get("ingestion", {})


def _extract_meta_in_process(html_head: str, url: str, base_url: str) -> tuple:
    """Top-level function (picklable) for extracting title/desc/date in a subprocess."""
    from ingestion.url import _extract_title, _extract_description
    from ingestion.dates import extract_year_from_html
    return (
        _extract_title(html_head, url),
        _extract_description(html_head),
        extract_year_from_html(html_head, base_url),
    )


def _extract_content_in_process(html: str) -> tuple:
    """Top-level function (picklable) for running trafilatura in a subprocess."""
    from ingestion.url import _extract_content
    return _extract_content(html)


def _decode_and_fix(raw_bytes: bytes) -> str:
    """Decode monolith stdout bytes and fix script close tags (picklable, for process pool)."""
    from ingestion.url import _fix_script_close_tags
    return _fix_script_close_tags(raw_bytes.decode("utf-8", errors="replace"))



async def ingest_url(url: str) -> dict:
    """Fetch a URL and return {title, content_md, snapshot_html, pub_date}.

    If the URL points to a PDF, routes through the PDF extraction pipeline.
    """
    validate_url_no_ssrf(url)
    cfg = _ingestion_cfg()
    user_agent = cfg.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    timeout = cfg.get("request_timeout", 30)
    max_bytes = cfg.get("max_content_length", 10_000_000)

    async with httpx.AsyncClient(
        timeout=float(timeout),
        follow_redirects=True,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        },
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        if len(resp.content) > max_bytes:
            raise ValueError(f"Response too large ({len(resp.content)} bytes)")
        content_type = resp.headers.get("content-type", "").lower()
        base_url = str(resp.url)

        # Detect PDF by content-type or URL extension
        is_pdf = "application/pdf" in content_type or base_url.split("?")[0].lower().endswith(".pdf")

        if is_pdf:
            return await _ingest_pdf_from_bytes(resp.content, base_url)

        html = resp.text

    loop = asyncio.get_event_loop()
    title, description, pub_date = await loop.run_in_executor(
        _process_pool, _extract_meta_in_process, html[:50_000], url, base_url
    )

    snapshot_html = await _make_snapshot(base_url, html)

    # Always extract content from the original fetched HTML — never from the snapshot.
    # Monolith output can be binary/corrupt for some sites, so we use the clean httpx response.
    content_md, content_llm_md = await loop.run_in_executor(
        _process_pool, _extract_content_in_process, html
    )

    return {
        "title": title,
        "description": description,
        "content_md": content_md,
        "content_llm_md": content_llm_md,
        "snapshot_html": snapshot_html,
        "pub_date": pub_date,
    }


async def _ingest_pdf_from_bytes(data: bytes, url: str) -> dict:
    """Save PDF bytes to a temp file and extract via the PDF pipeline.

    Returns a tmp_pdf_path that the caller must clean up after save_item copies it.
    """
    from ingestion.pdf import ingest_pdf

    filename = url.rstrip("/").split("/")[-1].split("?")[0] or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.write(data)
    tmp.close()
    tmp_path = tmp.name

    result = await ingest_pdf(tmp_path, original_filename=filename)

    from ingestion.dates import extract_year_from_url
    return {
        "title": result["title"],
        "content_md": result["content_md"],
        "snapshot_html": None,
        "pub_date": result.get("pub_date") or extract_year_from_url(url),
        "content_type": "pdf",
        "tmp_pdf_path": tmp_path,   # caller must os.unlink after save_item
    }


def _extract_description(html: str) -> str:
    """Extract a short page description from og:description or meta[name=description]."""
    patterns = [
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:description["\']',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I | re.S)
        if m:
            text = re.sub(r"\s+", " ", m.group(1)).strip()
            if text:
                return text[:300]
    return ""


def _extract_title(html: str, url: str) -> str:
    from html import unescape
    og = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', html, re.I)
    if og:
        return unescape(og.group(1).strip())
    t = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if t:
        return unescape(re.sub(r"\s+", " ", t.group(1)).strip())
    return url.rstrip("/").split("/")[-1] or url


_PRE_TAG_RE = re.compile(r'<pre[^>]*>(.*?)</pre>', re.DOTALL | re.IGNORECASE)
_HTML_TAG_RE = re.compile(r'<[^>]+>')
_PLACEHOLDER_RE = re.compile(r'CODEBLOCK_(\d+)_END')
_B64_SRC_RE = re.compile(r'src="data:([^;]+);base64,[A-Za-z0-9+/=]+"', re.IGNORECASE)
_MIME_TO_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
                "image/webp": "webp", "image/svg+xml": "svg", "image/avif": "avif"}


def _stub_base64_images(html: str) -> str:
    """Replace base64 image src attrs with stub asset paths so trafilatura includes them."""
    counter = [0]
    def _replace(m: re.Match) -> str:
        mime = m.group(1).lower()
        ext = _MIME_TO_EXT.get(mime, "bin")
        counter[0] += 1
        return f'src="assets/img_{counter[0]}.{ext}"'
    return _B64_SRC_RE.sub(_replace, html)


def _strip_html_tags(text: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = _HTML_TAG_RE.sub('', text)
    text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'")
    return text


def _protect_pre_blocks(html: str) -> tuple[str, list[str]]:
    """Replace <pre> blocks with placeholders. Returns modified HTML and list of code texts."""
    code_blocks: list[str] = []

    def _replace(m: re.Match) -> str:
        inner = _strip_html_tags(m.group(1))
        # Remove leading/trailing line numbers (common in syntax-highlighted blogs)
        # Lines that are purely numeric are line number artifacts
        lines = inner.split('\n')
        cleaned = [ln for ln in lines if not ln.strip().isdigit()]
        code = '\n'.join(cleaned).strip()
        if not code:
            return ''
        idx = len(code_blocks)
        code_blocks.append(code)
        return f'<p>CODEBLOCK_{idx}_END</p>'

    modified = _PRE_TAG_RE.sub(_replace, html)
    return modified, code_blocks


def _restore_code_blocks(text: str, code_blocks: list[str]) -> str:
    """Replace CODEBLOCK_N_END placeholders with fenced markdown code blocks."""
    def _replace(m: re.Match) -> str:
        idx = int(m.group(1))
        if idx < len(code_blocks):
            return f'\n```\n{code_blocks[idx]}\n```\n'
        return ''
    return _PLACEHOLDER_RE.sub(_replace, text)


_INLINE_ONLY_RE = re.compile(r'^(`[^`\n]+`[.,;:)!?\s]*|[.,;:)!?\s]*`[^`\n]+`)$')


def _rejoin_inline_code(text: str) -> str:
    """Rejoin lines that trafilatura split around inline code spans.

    Trafilatura often emits inline code on its own line, e.g.:
        It uses the method
        `ConsoleShell.Start`
        to create a console.

    Without breaks:true this still renders as separate paragraphs.
    Merge such orphaned inline-content lines with adjacent non-blank lines.
    """
    lines = text.split('\n')
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # If this line is non-blank and the NEXT line looks like orphaned inline content
        # (just a code span or punctuation+code), merge them
        if (line.strip() and i + 1 < len(lines)
                and _INLINE_ONLY_RE.match(lines[i + 1].strip())
                and not line.strip().startswith('#')
                and not line.strip().startswith('```')):
            merged = line.rstrip() + ' ' + lines[i + 1].strip()
            # Also check if line after that continues the sentence (non-blank, not heading/code)
            j = i + 2
            while (j < len(lines)
                   and lines[j].strip()
                   and _INLINE_ONLY_RE.match(lines[j].strip())
                   and not lines[j].strip().startswith('#')):
                merged += ' ' + lines[j].strip()
                j += 1
            # If the line after the inline span is also a plain continuation, merge it too
            if (j < len(lines)
                    and lines[j].strip()
                    and not lines[j].strip().startswith('#')
                    and not lines[j].strip().startswith('```')
                    and not lines[j].strip().startswith('!')
                    and not _INLINE_ONLY_RE.match(lines[j].strip())
                    and j == i + 2):  # only one level of lookahead for continuation
                merged += ' ' + lines[j].strip()
                i = j + 1
            else:
                i = j
            out.append(merged)
        else:
            out.append(line)
            i += 1
    return '\n'.join(out)


_IMG_TAG_RE = re.compile(r'<img[^>]+>', re.IGNORECASE)
_IMG_SRC_RE = re.compile(r'\bsrc=(?:"([^"]+)"|\'([^\']+)\')', re.IGNORECASE)
_IMG_ALT_RE = re.compile(r'\balt=(?:"([^"]*)"|\'([^\']*)\')', re.IGNORECASE)
_MD_IMG_SRC_RE = re.compile(r'!\[.*?\]\(([^)]+)\)')
# Skip images whose src looks like icons/avatars/logos (very small or tracking pixels)
_SKIP_SRC_RE = re.compile(r'(icon|logo|avatar|pixel|tracker|badge|button|1x1|spacer)', re.IGNORECASE)


def _inject_missing_images(md: str, html: str) -> str:
    """Insert images found in HTML that trafilatura missed, inline at their approximate position.

    For each missing image, we look at the text immediately before it in the HTML,
    find that text in the markdown, and insert the image after it.
    """
    existing = {m.group(1) for m in _MD_IMG_SRC_RE.finditer(md)}

    # Build list of (position_in_html, img_markdown) for missing images
    insertions: list[tuple[int, str]] = []
    for tag in _IMG_TAG_RE.finditer(html):
        raw = tag.group(0)
        src_m = _IMG_SRC_RE.search(raw)
        if not src_m:
            continue
        src = src_m.group(1) or src_m.group(2)
        if not src or src in existing:
            continue
        if _SKIP_SRC_RE.search(src):
            continue
        if src.startswith('data:') and len(src) < 2000:
            continue
        alt_m = _IMG_ALT_RE.search(raw)
        alt = (alt_m.group(1) or alt_m.group(2) or '').strip() if alt_m else ''
        img_md = f'![{alt}]({src})'
        insertions.append((tag.start(), img_md))
        existing.add(src)

    if not insertions:
        return md

    # Strip all HTML tags to get plain text, building a char-position map html→plain
    plain_chars = []
    html_to_plain: dict[int, int] = {}
    i = 0
    in_tag = False
    while i < len(html):
        if html[i] == '<':
            in_tag = True
        elif html[i] == '>':
            in_tag = False
        elif not in_tag:
            html_to_plain[i] = len(plain_chars)
            plain_chars.append(html[i])
        i += 1
    plain_text = ''.join(plain_chars)

    # Split markdown into paragraphs with their positions
    md_paragraphs = []  # list of (start_pos, end_pos, text)
    pos = 0
    for para in re.split(r'\n\n+', md):
        md_paragraphs.append((pos, pos + len(para), para))
        pos += len(para) + 2

    def _find_insert_pos(html_pos: int) -> int:
        """Find the markdown insertion position for an image at html_pos."""
        # Get ~100 chars of plain text before the image position
        plain_pos = html_to_plain.get(html_pos)
        if plain_pos is None:
            # Find nearest mapped position
            for offset in range(1, 200):
                if html_pos - offset in html_to_plain:
                    plain_pos = html_to_plain[html_pos - offset]
                    break
            else:
                return len(md)

        # Get a snippet of text before this position to locate in markdown
        snippet_start = max(0, plain_pos - 80)
        snippet = plain_text[snippet_start:plain_pos].strip()
        if not snippet:
            return len(md)

        # Try progressively shorter snippets to find a match in markdown
        for length in (60, 40, 20, 10):
            fragment = re.sub(r'\s+', ' ', snippet[-length:]).strip()
            if not fragment:
                continue
            # Search in markdown (stripped of markdown syntax for comparison)
            md_plain = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', md)  # remove link syntax
            md_plain = re.sub(r'[*_`#>]', '', md_plain)
            idx = md_plain.find(fragment)
            if idx != -1:
                # Find end of the paragraph containing this position
                end = md.find('\n\n', idx)
                return end if end != -1 else len(md)

        return len(md)

    # Sort insertions by html position and insert from end to preserve positions
    insertions.sort(key=lambda x: x[0])

    # Build insertion points in markdown (as char positions) and insert
    md_insertions: list[tuple[int, str]] = []
    for html_pos, img_md in insertions:
        insert_at = _find_insert_pos(html_pos)
        md_insertions.append((insert_at, img_md))

    # Insert from end to front to preserve positions
    md_insertions.sort(key=lambda x: x[0], reverse=True)
    # Deduplicate same position
    seen_pos: set[int] = set()
    result = md
    for insert_at, img_md in md_insertions:
        if insert_at in seen_pos:
            insert_at = max(0, insert_at - 1)
        seen_pos.add(insert_at)
        result = result[:insert_at] + f'\n\n{img_md}\n\n' + result[insert_at:]

    return result


def _extract_content(html: str) -> tuple[str, str]:
    """Extract content from HTML. Returns (content_md, content_llm_md).

    content_md     — full markdown with images, for display.
    content_llm_md — same but without inline images, for chunking/embedding.
    """
    _data_img_re = re.compile(r'!\[[^\]]*\]\(data:[^)]+\)', re.I)

    # Protect <pre> blocks before trafilatura mangles them
    protected_html, code_blocks = _protect_pre_blocks(html)

    try:
        import trafilatura

        full = trafilatura.extract(
            protected_html,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
            include_images=True,
            include_formatting=True,
            include_links=True,
            no_fallback=False,
        )
        if full and len(full) > 200:
            full = _restore_code_blocks(full, code_blocks)
            full = _rejoin_inline_code(full)
            full = _inject_missing_images(full, html)
            from html import unescape
            full = unescape(full)
            llm = _data_img_re.sub('', full)
            return full, llm
    except Exception:
        pass

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        plain = "\n".join(lines)
        return plain, plain
    except Exception:
        pass

    return "", ""


async def _estimate_asset_sizes(html: str, base_url: str) -> dict[str, int]:
    """Return {'css': N, 'js': N} total bytes from Content-Length headers of linked assets."""
    from urllib.parse import urljoin

    css_urls = []
    for m in re.finditer(r'<link\b[^>]*>', html[:100_000], re.I):
        tag = m.group(0)
        if not re.search(r'rel=["\']stylesheet["\']', tag, re.I):
            continue
        href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
        if href and not href.group(1).startswith("data:"):
            css_urls.append(urljoin(base_url, href.group(1)))
    async def _head_size(client: httpx.AsyncClient, url: str) -> int:
        try:
            r = await client.head(url, timeout=5.0, follow_redirects=True)
            return int(r.headers.get("content-length", 0))
        except Exception:
            return 0

    cfg = _ingestion_cfg()
    user_agent = cfg.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
    async with httpx.AsyncClient(headers={"User-Agent": user_agent, "Accept": "*/*"}) as client:
        css_sizes = await asyncio.gather(*[_head_size(client, u) for u in css_urls])

    return {"css": sum(css_sizes)}


def _fix_script_close_tags(html: str) -> str:
    """Escape </script> occurrences that appear inside <script> block content.

    The HTML parser terminates a <script> block at the first bare </script>,
    even if it's inside a JS string literal.  We detect false closes by the
    character that immediately follows the '>': JS punctuation (' " , ; ) })
    means it's inside a string, whereas whitespace or '<' means it's the real
    structural close tag.
    """
    close_re = re.compile(r'</(script\b[^>]*)>([\s\S]?)', re.I)
    open_re = re.compile(r'<script\b[^>]*>', re.I)

    def _js_punct(ch: str) -> bool:
        """True if ch looks like JS that follows a string-embedded </script>."""
        return ch in ("'", '"', ',', ';', ')', ']', '}', '+', '\\', ':')

    out: list[str] = []
    pos = 0
    n = len(html)

    while pos < n:
        om = open_re.search(html, pos)
        if om is None:
            out.append(html[pos:])
            break

        out.append(html[pos:om.end()])
        pos = om.end()

        # Scan forward, escaping false </script> closes until we hit the real one
        while pos < n:
            cm = close_re.search(html, pos)
            if cm is None:
                out.append(html[pos:])
                pos = n
                break

            inner = html[pos:cm.start()]
            out.append(inner)
            after_char = cm.group(2)  # char right after the >

            if after_char and _js_punct(after_char):
                # False close — escape it and keep scanning inside the block
                out.append('<\\/' + cm.group(1) + '>' + after_char)
            else:
                # Real structural close tag
                out.append('</' + cm.group(1) + '>' + after_char)
                pos = cm.end()
                break

            pos = cm.end()

    return ''.join(out)


async def _make_snapshot(url: str, html: str = "") -> str | None:
    """Produce a self-contained HTML snapshot using monolith.

    If html is provided, it is piped into monolith via stdin with -b set to
    the real URL so relative asset URLs resolve correctly.
    If html is not provided, monolith fetches the URL itself.
    """
    cfg = _ingestion_cfg()
    css_threshold = cfg.get("snapshot_css_threshold", 500_000)
    user_agent = cfg.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

    flags = ["-a", "-v", "-F"]  # always exclude audio, video, fonts

    if html:
        try:
            sizes = await _estimate_asset_sizes(html[:100_000], url)
            if sizes["css"] > css_threshold:
                flags.append("-c")
        except Exception:
            pass

    try:
        if html:
            # Pipe pre-fetched HTML into monolith; use -b to set base URL for
            # resolving relative asset references, and -I to prevent it from
            # fetching the page itself again.
            proc = await asyncio.create_subprocess_exec(
                "monolith", "-", *flags,
                "-b", url,
                "-t", "30",
                "-u", user_agent,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdin_bytes = html.encode("utf-8", errors="replace")
            stdout, _ = await asyncio.wait_for(proc.communicate(input=stdin_bytes), timeout=60)
        else:
            proc = await asyncio.create_subprocess_exec(
                "monolith", url, *flags,
                "-t", "30",
                "-u", user_agent,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)

        if proc.returncode == 0 and stdout:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(_process_pool, _decode_and_fix, stdout)
        return None
    except Exception:
        return None
