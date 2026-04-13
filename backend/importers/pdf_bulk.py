"""Bulk PDF directory importer."""

from __future__ import annotations
import asyncio
from pathlib import Path


async def import_pdf_directory(
    dirpath: str,
    recursive: bool = True,
    llm=None,
    index=None,
    data_dir=None,
    progress=None,
) -> dict:
    """Import all PDFs from a directory. Returns {imported, skipped, failed}.

    progress: optional callable(n, path, status) called for each file.
    """
    from pipeline import ingest_pdf_pipeline

    root = Path(dirpath)
    pattern = "**/*.pdf" if recursive else "*.pdf"
    pdf_files = list(root.glob(pattern))

    imported, skipped, failed = 0, 0, 0

    for n, pdf_path in enumerate(pdf_files, 1):
        if progress:
            progress(n, pdf_path.name, "processing")
        try:
            result = await ingest_pdf_pipeline(
                file_path=str(pdf_path),
                original_filename=pdf_path.name,
                category=None,
                tags=None,
                llm=llm,
                index=index,
                data_dir=data_dir,
            )
            if result.get("duplicate"):
                skipped += 1
                if progress:
                    progress(n, pdf_path.name, "skip")
            else:
                imported += 1
                if progress:
                    progress(n, pdf_path.name, f"ok [{result['category']}] {result['title'][:50]}")
        except Exception as e:
            failed += 1
            if progress:
                progress(n, pdf_path.name, f"fail {type(e).__name__}: {str(e)[:60]}")
            from storage.failures import record_failure
            record_failure(data_dir, "pdf", str(pdf_path), e)

    return {"imported": imported, "skipped": skipped, "failed": failed}
