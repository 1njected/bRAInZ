"""Auto-classify security content into categories with tags and summary."""

from __future__ import annotations
import json
import re
from pathlib import Path
from config import get_config, get_categories, get_tags_for_category, get_category_descriptions


async def _get_similar_verified(
    title: str,
    content: str,
    llm,
    data_dir: Path,
    index,
    exclude_item_id: str | None,
    top_k: int = 5,
) -> list[dict]:
    """Return up to top_k verified items most similar to the given content."""
    import numpy as np
    from rag.search import VectorIndex

    verified_ids = {
        iid for iid, meta in index.all_items().items()
        if meta.get("verified") and iid != exclude_item_id
    }
    if not verified_ids:
        return []

    vi = VectorIndex(data_dir)
    vi.load()
    if not vi.is_loaded():
        return []

    query_text = title + " " + " ".join(content.split()[:200])
    embeddings = await llm.embed([query_text])
    q = embeddings[0]

    results = vi.search(q, top_k=top_k, allowed_item_ids=verified_ids)
    out = []
    for r in results:
        meta = index.get(r["item_id"])
        if meta:
            out.append({
                "title": meta.get("title", ""),
                "category": meta.get("category", ""),
                "tags": meta.get("tags", []),
                "score": r["score"],
            })
    return out


async def classify_content(
    title: str,
    content: str,
    llm,
    description: str = "",
    data_dir=None,
    index=None,
    exclude_item_id: str | None = None,
) -> dict:
    """Classify content — two short LLM calls, each with a compact prompt.

    Signal priority:
      1. Title       — most important, listed first in every prompt
      2. Description — og:description / meta description / PDF subject (if available)
      3. Body        — short excerpt (classifier_body_words, default 100), confirms only

    When index is provided and verified items exist, similar verified items are
    injected as few-shot examples to guide both category and tag selection.
    """
    categories = get_categories()
    descriptions = get_category_descriptions()
    cfg = get_config().get("ingestion", {})
    body_words = cfg.get("classifier_body_words", 100)
    excerpt = " ".join(content.split()[:body_words])

    # Retrieve similar verified items for few-shot guidance
    similar: list[dict] = []
    if data_dir and index:
        try:
            similar = await _get_similar_verified(
                title, content, llm, data_dir, index, exclude_item_id, top_k=5
            )
        except Exception:
            similar = []

    # Build per-category description lines with tags as classification signals
    def _cat_line(c: str) -> str:
        line = f"  {c}: {descriptions.get(c, '')}"
        tags = get_tags_for_category(c)
        if tags:
            line += f" [tags: {', '.join(tags)}]"
        return line

    cat_lines = "\n".join(_cat_line(c) for c in categories)

    # User prompt: title first, then description (if any), then short body
    def _user_prompt(title: str, description: str, excerpt: str, body_words: int) -> str:
        parts = [f"TITLE: {title}"]
        if description:
            parts.append(f"DESCRIPTION: {description}")
        parts.append(f"BODY (first {body_words} words):\n{excerpt}")
        return "\n\n".join(parts)

    user_prompt = _user_prompt(title, description, excerpt, body_words)

    # ── Pass 1: category + summary ────────────────────────────────────────────
    examples_block = ""
    if similar:
        ex_lines = "\n".join(
            f'  "{e["title"]}" → {e["category"]}'
            for e in similar
        )
        examples_block = f"\nVerified examples (use as guidance):\n{ex_lines}\n"

    system1 = (
        "You are an IT security content classifier.\n"
        "Signal priority: TITLE is the strongest signal. "
        "DESCRIPTION is secondary. BODY is supporting context only.\n"
        "Reply in this exact format, nothing else:\n"
        "CATEGORY: <one category name>\n"
        "SUMMARY: <one sentence>\n"
        f"{examples_block}"
        f"\nCategories:\n{cat_lines}"
    )
    raw1 = await _call(llm, system1, user_prompt)
    cat_result = _parse_category(raw1, set(categories))
    category = cat_result["category"]
    summary = cat_result["summary"]

    # ── Pass 2: tags from that category's allowlist ───────────────────────────
    category_tags = get_tags_for_category(category)
    tags: list[str] = []
    if category_tags:
        tag_list = ", ".join(category_tags)

        # Few-shot examples from verified items in the same category
        examples = ""
        cat_similar = [e for e in similar if e.get("category") == category and e.get("tags")][:3]
        if cat_similar:
            ex_lines = []
            for e in cat_similar:
                ex_tags = json.dumps([t for t in e["tags"] if t in set(category_tags)])
                ex_lines.append(f'  Title: {e["title"]}\n  Tags: {ex_tags}')
            examples = "\n\nExamples from this category:\n" + "\n\n".join(ex_lines)

        system2 = (
            "You are an IT security content tagger.\n"
            "Your job is two steps:\n"
            "1. TECHNIQUES: List the specific techniques, tools, protocols, or vulnerability "
            "classes mentioned in the content (one per line, be concrete).\n"
            "2. TAGS: Map those to 0-5 tags from the allowed list below. "
            "Only pick tags that directly match something identified in step 1. "
            "Prefer specific over generic. If nothing matches well, return [].\n\n"
            f"Allowed tags: {tag_list}"
            f"{examples}\n\n"
            "Reply in this exact format:\n"
            "TECHNIQUES:\n- <technique>\n- <technique>\n\n"
            'TAGS: ["<tag>","<tag>"]'
        )
        raw2 = await _call(llm, system2, user_prompt)
        tags = _parse_tags(raw2, set(category_tags))

    return {
        "category": category,
        "tags": tags,
        "summary": summary,
        "classified_by": getattr(llm, "provider_name", "unknown"),
    }


async def _call(llm, system: str, prompt: str) -> str:
    if hasattr(llm, "complete_classify"):
        return await llm.complete_classify(system, prompt)
    return await llm.complete(system, prompt, max_tokens=2048)


def _parse_category(raw: str, valid_categories: set[str]) -> dict:
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    # Try key-value format first: "CATEGORY: appsec\nSUMMARY: ..."
    cat_m = re.search(r"^CATEGORY:\s*(.+)$", raw, re.I | re.M)
    sum_m = re.search(r"^SUMMARY:\s*(.+)$", raw, re.I | re.M)
    if cat_m:
        category = cat_m.group(1).strip().lower()
        if category in valid_categories:
            return {
                "category": category,
                "summary": sum_m.group(1).strip() if sum_m else "",
            }

    # Fall back to JSON
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*?\}", raw, re.S)
        try:
            data = json.loads(m.group()) if m else {}
        except (json.JSONDecodeError, AttributeError):
            return {"category": "misc", "summary": ""}
    category = str(data.get("category", "misc")).lower().strip()
    if category not in valid_categories:
        category = "misc"
    summary = data.get("summary")
    return {"category": category, "summary": str(summary).strip() if summary is not None else ""}


def _parse_tags(raw: str, valid_tags: set[str]) -> list[str]:
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    # Try JSON array
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(t).lower().strip() for t in data
                    if str(t).lower().strip() in valid_tags][:7]
        if isinstance(data, dict) and "tags" in data:
            return [str(t).lower().strip() for t in data["tags"]
                    if str(t).lower().strip() in valid_tags][:7]
    except json.JSONDecodeError:
        pass
    # Fall back: extract quoted strings matching valid tags
    found = re.findall(r'"([^"]+)"', raw)
    return [t.lower().strip() for t in found if t.lower().strip() in valid_tags][:7]


# Backward compat for tests
def _parse_classification(raw: str, valid_categories: set[str], valid_tags: set[str] = set()) -> dict:
    result = _parse_category(raw, valid_categories)
    raw_clean = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        data = json.loads(raw_clean)
        if isinstance(data, dict) and "tags" in data:
            raw_tags = data["tags"]
            if not isinstance(raw_tags, list):
                result["tags"] = []
                return result
            tags = [str(t).lower().strip() for t in raw_tags if t]
            if valid_tags:
                tags = [t for t in tags if t in valid_tags]
            result["tags"] = tags[:7]
            return result
    except (json.JSONDecodeError, Exception):
        pass
    result["tags"] = []
    return result
