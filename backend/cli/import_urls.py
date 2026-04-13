"""CLI command: import-urls — extract URLs from any text file and bulk import."""

from __future__ import annotations
import re


_URL_RE = re.compile(
    r'https?://[^\s\'"<>)\]},;\\]+'
)


def extract_urls(filepath: str) -> list[str]:
    """Extract, deduplicate, and sort all HTTP/HTTPS URLs from a text file."""
    with open(filepath, encoding="utf-8", errors="replace") as f:
        text = f.read()
    found = _URL_RE.findall(text)
    # Strip trailing punctuation that's unlikely to be part of the URL
    cleaned = [u.rstrip(".,!?;:'\"") for u in found]
    return sorted(set(cleaned))


def run(args):
    from cli.deps import get_deps, run_async
    config, llm, index, data_dir = get_deps()

    urls = extract_urls(args.filepath)
    total = len(urls)
    if not total:
        print(f"No URLs found in {args.filepath}")
        return

    print(f"Found {total} unique URLs in {args.filepath}")

    async def _run():
        from pipeline import ingest_url_pipeline
        from rag.embedder import embed_all
        imported = skipped = failed = 0

        for n, url in enumerate(urls, 1):
            try:
                result = await ingest_url_pipeline(
                    url=url,
                    category=args.category or None,
                    tags=[t.strip() for t in args.tags.split(",")] if args.tags else [],
                    llm=llm,
                    index=index,
                    data_dir=data_dir,
                )
                if result.get("duplicate"):
                    skipped += 1
                    print(f"  [{n}/{total}] skip: {url[:80]}", flush=True)
                else:
                    imported += 1
                    print(f"  [{n}/{total}] ok [{result.get('category','')}] {result.get('title','')[:60]}", flush=True)
            except Exception as e:
                failed += 1
                print(f"  [{n}/{total}] fail: {url[:80]} — {e}", flush=True)

            if args.rate_limit:
                import asyncio
                await asyncio.sleep(args.rate_limit)

        print(f"\nDone — Imported: {imported}  Skipped: {skipped}  Failed: {failed}")

    run_async(_run())


def register(subparsers):
    p = subparsers.add_parser(
        "import-urls",
        help="Extract URLs from any text file and import them into the library",
    )
    p.add_argument("filepath", help="Path to the file to extract URLs from")
    p.add_argument("--category", "-c", default=None, metavar="CATEGORY",
                   help="Force a category for all items; omit to auto-classify")
    p.add_argument("--tags", "-t", default=None, metavar="TAGS",
                   help="Comma-separated tags to apply to all items")
    p.add_argument("--rate-limit", type=float, default=1.0, metavar="SECONDS",
                   help="Seconds to wait between requests (default: 1.0)")
    p.set_defaults(func=run)
