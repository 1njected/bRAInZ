"""Bulk image directory importer."""

from __future__ import annotations
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


async def import_image_directory(
    dirpath: str,
    recursive: bool = True,
    category: str | None = None,
    tags: list[str] | None = None,
    llm=None,
    index=None,
    data_dir=None,
    vector_index=None,
    progress=None,
) -> dict:
    """Import all images from a directory. Returns {imported, skipped, failed}.

    progress: optional callable(n, path, status) called for each file.
    """
    from pipeline import ingest_image_pipeline

    root = Path(dirpath)
    pattern = "**/*" if recursive else "*"
    image_files = sorted(
        p for p in root.glob(pattern)
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )

    imported, skipped, failed = 0, 0, 0

    for n, img_path in enumerate(image_files, 1):
        if progress:
            progress(n, img_path.name, "processing")
        try:
            result = await ingest_image_pipeline(
                file_path=str(img_path),
                original_filename=img_path.name,
                category=category,
                tags=tags,
                llm=llm,
                index=index,
                data_dir=data_dir,
                vector_index=vector_index,
            )
            if result.get("duplicate"):
                skipped += 1
                if progress:
                    progress(n, img_path.name, "skip")
            else:
                imported += 1
                if progress:
                    progress(n, img_path.name, f"ok [{result['category']}] {result['title'][:50]}")
        except Exception as e:
            failed += 1
            if progress:
                progress(n, img_path.name, f"fail {type(e).__name__}: {str(e)[:60]}")
            from storage.failures import record_failure
            record_failure(data_dir, "image", str(img_path), e)

    return {"imported": imported, "skipped": skipped, "failed": failed}
