"""RAG query pipeline — embed question, retrieve chunks, generate answer."""

from __future__ import annotations
from pathlib import Path
from typing import Optional

from rag.search import VectorIndex, semantic_search

SYSTEM_PROMPT = """You are an IT security expert assistant with access to the user's personal knowledge base, which contains articles, blog posts, PDFs, wiki pages, and starred GitHub tool repositories. Answer the question based on the provided context. Cite sources by title using [title] notation — this includes both articles/docs and tools (GitHub repos). If the context doesn't contain enough information to answer confidently, say so — don't fabricate details."""


async def rag_query(
    question: str,
    llm,
    vector_index: VectorIndex,
    index,
    data_dir: Path | None = None,
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
    top_k: int = 8,
) -> dict:
    """RAG query. Returns {answer, sources: [{item_id, title, url, relevance_score}]}."""
    if data_dir is None and hasattr(index, "_data_dir"):
        data_dir = index._data_dir

    results = await semantic_search(
        query=question,
        llm=llm,
        vector_index=vector_index,
        index=index,
        data_dir=data_dir,
        category=category,
        tags=tags,
        top_k=top_k,
    )

    if not results:
        return {
            "answer": "No relevant content found in your knowledge base for this question.",
            "sources": [],
            "tools": [],
            "thinking": "",
        }

    # Build context from top results — truncate each doc to keep total context manageable
    max_chars_per_doc = 4000
    context_parts = []
    seen_items: dict[str, dict] = {}
    for r in results:
        item_id = r["item_id"]
        title = r["title"]
        content = r["content"][:max_chars_per_doc]
        context_parts.append(f"[{title}]\n{content}")
        if item_id not in seen_items:
            seen_items[item_id] = {
                "item_id": item_id,
                "title": title,
                "url": r.get("url"),
                "relevance_score": r["score"],
            }

    context = "\n\n---\n\n".join(context_parts)
    prompt = f"Context from knowledge base:\n\n{context}\n\n---\n\nQuestion: {question}"

    if hasattr(llm, "complete_with_thinking"):
        answer, thinking = await llm.complete_with_thinking(SYSTEM_PROMPT, prompt, max_tokens=4096)
    else:
        answer, thinking = await llm.complete(SYSTEM_PROMPT, prompt, max_tokens=4096), ""

    # Split results: GitHub repos → tools list, everything else → sources list
    sources = []
    tools = []
    for item in seen_items.values():
        url = item.get("url") or ""
        if "github.com" in url and "/" in item["title"]:
            tools.append({
                "item_id": item["item_id"],
                "title": item["title"],
                "url": url,
                "relevance_score": item["relevance_score"],
            })
        else:
            sources.append(item)

    return {
        "answer": answer,
        "thinking": thinking,
        "sources": sources,
        "tools": tools,
    }
