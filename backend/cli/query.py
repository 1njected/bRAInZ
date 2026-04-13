"""CLI command: query — RAG query against the knowledge base."""

from __future__ import annotations


def run(args):
    from cli.deps import get_deps, run_async
    config, llm, index, data_dir = get_deps()

    async def _run():
        from rag.search import VectorIndex
        from rag.query import rag_query
        vi = VectorIndex(data_dir)
        vi.load()
        result = await rag_query(
            question=args.question,
            llm=llm,
            vector_index=vi,
            index=index,
            category=args.category,
        )
        print(result["answer"])
        print()
        print("Sources:")
        for src in result["sources"]:
            print(f"  [{src['relevance_score']:.3f}] {src['title']}")

    run_async(_run())


def register(subparsers):
    p = subparsers.add_parser("query", help="RAG query against the knowledge base")
    p.add_argument("question")
    p.add_argument("--category", "-c", default=None)
    p.set_defaults(func=run)
