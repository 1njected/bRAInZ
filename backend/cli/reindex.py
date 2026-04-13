"""CLI command: reindex — rebuild index.json from filesystem."""

from __future__ import annotations


def run(args):
    from cli.deps import get_deps, run_async
    config, llm, index, data_dir = get_deps()

    async def _run():
        count = await index.rebuild()
        print(f"Reindexed {count} items")

    run_async(_run())


def register(subparsers):
    p = subparsers.add_parser("reindex", help="Rebuild index.json from filesystem")
    p.set_defaults(func=run)
