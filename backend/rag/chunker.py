"""Split content into overlapping chunks for RAG."""

from __future__ import annotations
import json
from pathlib import Path
from config import get_config

CHUNK_SIZE = 500   # default target tokens
OVERLAP = 50       # default overlap tokens


def _rag_cfg() -> dict:
    return get_config().get("rag", {})


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> list[dict]:
    """Split text into chunks. Each chunk: {index, text, start_char, end_char}."""
    # Estimate chars from tokens
    char_size = chunk_size * 4
    char_overlap = overlap * 4

    # Split into paragraphs first
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks = []
    current = ""
    current_start = 0
    char_pos = 0

    for para in paragraphs:
        if not current:
            current = para
            current_start = char_pos
        elif len(current) + len(para) + 2 <= char_size:
            current += "\n\n" + para
        else:
            # Flush current chunk
            if current:
                chunks.append({
                    "index": len(chunks),
                    "text": current,
                    "start_char": current_start,
                    "end_char": current_start + len(current),
                })
                # Overlap: keep tail of current chunk
                overlap_text = current[-char_overlap:] if char_overlap else ""
                current_start = current_start + len(current) - len(overlap_text)
                current = overlap_text + "\n\n" + para if overlap_text else para
        char_pos += len(para) + 2

    # Flush last chunk
    if current:
        chunks.append({
            "index": len(chunks),
            "text": current,
            "start_char": current_start,
            "end_char": current_start + len(current),
        })

    # If no paragraph breaks, fall back to sliding window
    if not chunks and text:
        pos = 0
        idx = 0
        while pos < len(text):
            end = min(pos + char_size, len(text))
            chunks.append({"index": idx, "text": text[pos:end], "start_char": pos, "end_char": end})
            pos += char_size - char_overlap
            idx += 1

    return chunks


def chunk_item(item_id: str, index, data_dir: Path, chunk_size: int | None = None, overlap: int | None = None) -> list[dict]:
    """Chunk an item's content.md and save chunks.json."""
    cfg = _rag_cfg()
    chunk_size = chunk_size or cfg.get("chunk_size", CHUNK_SIZE)
    overlap = overlap or cfg.get("chunk_overlap", OVERLAP)
    entry = index.get(item_id)
    if not entry:
        return []

    item_dir = data_dir / entry["path"]
    llm_file = item_dir / "content_llm.md"
    content_file = item_dir / "content.md"
    target = llm_file if llm_file.exists() else content_file
    if not target.exists():
        return []

    content = target.read_text(encoding="utf-8")
    chunks = chunk_text(content, chunk_size=chunk_size, overlap=overlap)

    chunks_file = item_dir / "chunks.json"
    chunks_file.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    return chunks


def chunk_all(index, data_dir: Path) -> int:
    """Chunk all items that are missing chunks.json."""
    count = 0
    for item_id, meta in index.all_items().items():
        item_dir = data_dir / meta["path"]
        if not (item_dir / "chunks.json").exists():
            chunk_item(item_id, index, data_dir)
            count += 1
    return count
