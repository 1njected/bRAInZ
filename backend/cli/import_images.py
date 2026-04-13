"""CLI command: import-images — bulk import a directory of images."""

from __future__ import annotations
from pathlib import Path

from importers.image_bulk import IMAGE_EXTENSIONS


def run(args):
    from cli.deps import get_deps, run_async
    config, llm, index, data_dir = get_deps()

    root = Path(args.dirpath)
    pattern = "**/*" if not args.no_recursive else "*"
    image_files = [
        p for p in root.glob(pattern)
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]
    total = len(image_files)
    if not total:
        print(f"No images found in {args.dirpath}")
        return

    print(f"Found {total} image(s) in {args.dirpath}")
    tag_list = [t.strip() for t in args.tags.split(",")] if args.tags else None

    async def _run():
        from importers.image_bulk import import_image_directory

        def progress(n, name, status):
            print(f"  [{n}/{total}] {status}: {name}", flush=True)

        result = await import_image_directory(
            dirpath=args.dirpath,
            recursive=not args.no_recursive,
            category=args.category or None,
            tags=tag_list,
            llm=llm,
            index=index,
            data_dir=data_dir,
        )
        print(f"\nDone — Imported: {result['imported']}  Skipped: {result['skipped']}  Failed: {result['failed']}")

    run_async(_run())


def register(subparsers):
    p = subparsers.add_parser(
        "import-images",
        help="Bulk import images from a directory (JPG, PNG, GIF, WebP)",
    )
    p.add_argument("dirpath", help="Directory containing images")
    p.add_argument("--no-recursive", action="store_true",
                   help="Only scan the top-level directory")
    p.add_argument("--category", "-c", default=None, metavar="CATEGORY",
                   help="Force a category for all items; omit to auto-classify")
    p.add_argument("--tags", "-t", default=None, metavar="TAGS",
                   help="Comma-separated tags to apply to all items")
    p.set_defaults(func=run)
