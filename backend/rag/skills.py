"""Generate SKILL.md files from knowledge base content."""

from __future__ import annotations
from pathlib import Path
from typing import Optional

from rag.search import VectorIndex, semantic_search
from utils import slug

SYSTEM_PROMPT = """You are an expert IT security practitioner. Generate a SKILL.md file that condenses the provided security knowledge into a structured, practical quick-reference.

Structure the file as:
# <Topic> — Quick Reference

## Overview
Brief description of the topic.

## Key Concepts
Core concepts and definitions.

## Techniques & Attack Patterns
Specific techniques relevant to this topic.

## Tools
Key tools with brief usage notes.

## Common Commands / Payloads
Ready-to-use commands, queries, or payloads.

## References
Source titles from the knowledge base.

---
Format as clean Markdown. Be concise and practical — this is a pentest reference, not a textbook."""


async def generate_skill(
    topic: str,
    llm,
    vector_index: VectorIndex,
    index,
    data_dir: Path,
    categories: Optional[list[str]] = None,
    description: Optional[str] = None,
    top_k: int = 20,
) -> str:
    """Generate a SKILL.md for the given topic. Returns the content."""
    if data_dir is None and hasattr(index, "_data_dir"):
        data_dir = index._data_dir

    query = f"{topic} {description or ''}".strip()

    # Gather top results across categories
    all_results = []
    if categories:
        per_cat = max(1, top_k // len(categories))
        for cat in categories:
            results = await semantic_search(
                query=query,
                llm=llm,
                vector_index=vector_index,
                index=index,
                data_dir=data_dir,
                category=cat,
                top_k=per_cat,
            )
            all_results.extend(results)
        seen: set[str] = set()
        deduped = []
        for r in sorted(all_results, key=lambda x: -x["score"]):
            if r["item_id"] not in seen:
                seen.add(r["item_id"])
                deduped.append(r)
        all_results = deduped[:top_k]
    else:
        all_results = await semantic_search(
            query=query,
            llm=llm,
            vector_index=vector_index,
            index=index,
            data_dir=data_dir,
            top_k=top_k,
        )

    if not all_results:
        return f"# {topic}\n\nNo relevant content found in the knowledge base."

    # Build context — truncate each doc to keep total context manageable
    max_chars_per_doc = 4000
    context_parts = []
    for r in all_results:
        context_parts.append(f"[{r['title']}]\n{r['content'][:max_chars_per_doc]}")

    context = "\n\n---\n\n".join(context_parts)
    prompt = f"Topic: {topic}\n{('Description: ' + description) if description else ''}\n\nKnowledge base content:\n\n{context}"

    content = await llm.complete(SYSTEM_PROMPT, prompt, max_tokens=4000)

    # Save to disk
    topic_slug = slug(topic, max_len=50)
    skill_dir = data_dir / "skills" / topic_slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    return content
