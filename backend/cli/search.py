"""CLI command: search — semantic vector search."""

from __future__ import annotations


def run(args):
    from cli.deps import get_deps, run_async
    config, llm, index, data_dir = get_deps()

    async def _run():
        from rag.search import VectorIndex, semantic_search
        vi = VectorIndex(data_dir)
        vi.load()
        results = await semantic_search(
            query=args.query,
            llm=llm,
            vector_index=vi,
            index=index,
            category=args.category,
            tags=None,
            top_k=args.top_k,
        )
        for r in results:
            print(f"[{r['score']:.3f}] {r['title']} ({r['category']})")
            snippet = r.get("content", "")[:200].strip()
            if snippet:
                print(f"  {snippet}...")
            print()

    run_async(_run())


def register(subparsers):
    p = subparsers.add_parser("search", help="Semantic search")
    p.add_argument("query")
    p.add_argument("--category", "-c", default=None)
    p.add_argument("--top-k", type=int, default=10)
    p.set_defaults(func=run)
