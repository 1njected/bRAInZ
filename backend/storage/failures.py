"""Record failed ingestions to data/failed/ for later review and retry."""

from __future__ import annotations
from pathlib import Path

import yaml

from utils import now_iso, slug


def record_failure(
    data_dir: Path,
    source_type: str,
    target: str,
    exc: Exception,
    category: str | None = None,
    tags: list[str] | None = None,
) -> None:
    """Write a failure record to data/failed/<timestamp>_<slug>.yaml.

    Args:
        data_dir:    Root data directory (e.g. Path('/data'))
        source_type: 'url', 'pdf', or 'text'
        target:      The URL, file path, or title that failed
        exc:         The exception that was raised
        category:    Category hint that was passed (may be None)
        tags:        Tag hints that were passed (may be None)
    """
    try:
        failed_dir = data_dir / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)

        ts = now_iso().replace(":", "-")
        slug = slug(target)
        filename = f"{ts}_{slug}.yaml"

        record = {
            "timestamp": now_iso(),
            "source_type": source_type,
            "target": target,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "category": category,
            "tags": tags or [],
        }

        (failed_dir / filename).write_text(
            yaml.dump(record, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # Never let failure recording crash the caller
