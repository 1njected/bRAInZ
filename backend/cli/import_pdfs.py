"""CLI command: import-pdfs — bulk import a directory of PDFs."""

from __future__ import annotations
from pathlib import Path


def run(args):
    from cli.deps import get_deps, run_async
    config, llm, index, data_dir = get_deps()

    async def _run():
        from importers.pdf_bulk import import_pdf_directory
        root = Path(args.dirpath)
        pattern = "**/*.pdf" if not args.no_recursive else "*.pdf"
        total = len(list(root.glob(pattern)))
        print(f"Found {total} PDFs in {args.dirpath}")

        def progress(n, path, status):
            print(f"  [{n}/{total}] {status}: {path}", flush=True)

        result = await import_pdf_directory(
            dirpath=args.dirpath,
            recursive=not args.no_recursive,
            llm=llm,
            index=index,
            data_dir=data_dir,
            progress=progress,
        )
        print(f"\nDone — Imported: {result['imported']}  Skipped: {result['skipped']}  Failed: {result['failed']}")

    run_async(_run())


def register(subparsers):
    p = subparsers.add_parser("import-pdfs", help="Import a directory of PDFs")
    p.add_argument("dirpath")
    p.add_argument("--no-recursive", action="store_true")
    p.set_defaults(func=run)
