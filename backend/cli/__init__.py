"""bRAInZ CLI — python -m brainz <command> or brainz <command>."""

from __future__ import annotations
import argparse
import sys

from cli import add_url, import_urls, import_pdfs, import_images, reindex, stats, search, query


def main():
    parser = argparse.ArgumentParser(prog="brainz", description="bRAInZ knowledge base CLI")
    sub = parser.add_subparsers(dest="command")

    add_url.register(sub)
    import_urls.register(sub)
    import_pdfs.register(sub)
    import_images.register(sub)
    reindex.register(sub)
    stats.register(sub)
    search.register(sub)
    query.register(sub)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
