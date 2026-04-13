"""CLI command: stats — show item counts by category."""

from __future__ import annotations


def run(args):
    from cli.deps import get_deps
    config, llm, index, data_dir = get_deps()
    items = index.all_items()
    cat_counts: dict[str, int] = {}
    embedded = 0
    for m in items.values():
        cat = m.get("category", "misc")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        if m.get("embedded"):
            embedded += 1

    print(f"Total items: {len(items)}  Embedded: {embedded}")
    print()
    for cat, count in sorted(cat_counts.items()):
        print(f"  {cat:<20} {count}")


def register(subparsers):
    p = subparsers.add_parser("stats", help="Show item counts by category")
    p.set_defaults(func=run)
