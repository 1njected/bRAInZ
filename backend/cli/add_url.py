"""CLI command: add-url — ingest a single URL."""

from __future__ import annotations


def run(args):
    from cli.deps import get_deps, run_async
    config, llm, index, data_dir = get_deps()
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None

    async def _run():
        from pipeline import ingest_url_pipeline
        print(f"Fetching {args.url} ...", flush=True)
        result = await ingest_url_pipeline(
            url=args.url,
            category=args.category,
            tags=tags,
            llm=llm,
            index=index,
            data_dir=data_dir,
        )
        if result["duplicate"]:
            print(f"Duplicate — already exists: {result['item_id']}")
        else:
            print(f"Saved [{result['category']}] {result['title']} → {result['item_id']}")

    run_async(_run())


def register(subparsers):
    p = subparsers.add_parser("add-url", help="Add a URL to the knowledge base")
    p.add_argument("url")
    p.add_argument("--category", "-c", default=None)
    p.add_argument("--tags", "-t", default=None, help="Comma-separated tags")
    p.set_defaults(func=run)
