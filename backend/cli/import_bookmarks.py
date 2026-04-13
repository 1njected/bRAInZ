"""CLI command: import-bookmarks — bulk import from a bookmarks file."""

from __future__ import annotations


def run(args):
    from cli.deps import get_deps, run_async
    config, llm, index, data_dir = get_deps()

    async def _run():
        from importers.bookmarks import import_bookmarks, parse_bookmarks_html, parse_bookmarks_json
        fmt = args.format
        if fmt == "html" and args.filepath.lower().endswith(".json"):
            fmt = "json"

        items = parse_bookmarks_json(args.filepath) if fmt == "json" else parse_bookmarks_html(args.filepath)
        total = len(items)
        print(f"Found {total} bookmarks in {args.filepath}")

        def progress(n, url, status):
            print(f"  [{n}/{total}] {status}: {url[:80]}", flush=True)

        result = await import_bookmarks(
            filepath=args.filepath,
            fmt=fmt,
            rate_limit=args.rate_limit,
            llm=llm,
            index=index,
            data_dir=data_dir,
            progress=progress,
        )
        print(f"\nDone — Imported: {result['imported']}  Skipped: {result['skipped']}  Failed: {result['failed']}")

    run_async(_run())


def register(subparsers):
    p = subparsers.add_parser("import-bookmarks", help="Import bookmarks file")
    p.add_argument("filepath")
    p.add_argument("--format", choices=["html", "json"], default="html")
    p.add_argument("--rate-limit", type=float, default=2.0, metavar="SECONDS")
    p.set_defaults(func=run)
