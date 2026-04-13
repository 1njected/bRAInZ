"""Load configuration from /data/config.yaml with env var overrides.

Taxonomy (categories + per-category tags) lives in:
  /data/taxonomy.yaml  — single source of truth for categories and their tags
Re-read on every call so edits take effect without restart.
"""

import os
import yaml
from pathlib import Path

def _data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "/data"))

# Module-level alias for code that imports DATA_DIR directly
DATA_DIR = _data_dir()

def _config_path() -> Path:
    return _data_dir() / "config.yaml"

def _taxonomy_path() -> Path:
    return _data_dir() / "taxonomy.yaml"


DEFAULT_CATEGORIES = [
    "ai", "appsec", "blueteam", "cloud", "crypto", "devops",
    "forensics", "fuzzing", "hw", "ics", "malware", "mobile",
    "netsec", "os", "osint", "redteam", "reversing", "rf", "blockchain", "misc",
]

DEFAULT_CONFIG = {
    "llm": {
        "provider": "ollama",
        "ollama": {
            "base_url": "http://host.docker.internal:11434",
            "classification_model": "llama3.1:8b",
            "query_model": "llama3.1:8b",
            "embedding_model": "nomic-embed-text",
            "embedding_dimensions": 768,
            "query_timeout": 300,
            "classify_timeout": 120,
            "embed_timeout": 120,
        },
        "anthropic": {
            "classification_model": "claude-haiku-4-5-20251001",
            "vision_model": "claude-haiku-4-5-20251001",
            "query_model": "claude-sonnet-4-6",
            "embedding_model": "voyage-3",
            "embedding_dimensions": 1024,
        },
        "openai": {
            "classification_model": "gpt-4o-mini",
            "vision_model": "gpt-4o-mini",
            "query_model": "gpt-4o",
            "embedding_model": "text-embedding-3-small",
            "embedding_dimensions": 1536,
        },
        "openai_compatible": {
            "base_url": "http://localhost:1234/v1",
            "api_key": "lm-studio",
            "classification_model": "local-model",
            "query_model": "local-model",
            "embedding_model": "local-embed",
            "embedding_dimensions": 768,
        },
    },
    "ingestion": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "request_timeout": 30,
        "bulk_rate_limit": 1.0,
        "classifier_max_words": 2000,
        "max_content_length": 10_000_000,
        "snapshot_css_threshold": 500_000,
    },
    "rag": {
        "chunk_size": 400,
        "chunk_overlap": 50,
        "default_top_k": 10,
        "query_top_k": 8,
        "skill_top_chunks": 50,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> dict:
    config = _deep_merge({}, DEFAULT_CONFIG)

    config_path = _config_path()
    if config_path.exists():
        with open(config_path) as f:
            file_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, file_config)

    # Env var overrides
    provider = os.environ.get("LLM_PROVIDER")
    if provider:
        config["llm"]["provider"] = provider

    return config


_config: dict | None = None

_taxonomy: list[dict] | None = None
_taxonomy_mtime: float = 0.0


def get_config() -> dict:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _load_taxonomy() -> list[dict]:
    """Load taxonomy.yaml with mtime-based caching. Re-reads only when the file changes."""
    global _taxonomy, _taxonomy_mtime
    path = _taxonomy_path()
    if not path.exists():
        return []
    mtime = path.stat().st_mtime
    if _taxonomy is None or mtime != _taxonomy_mtime:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        _taxonomy = data.get("categories", [])
        _taxonomy_mtime = mtime
    return _taxonomy


def get_categories() -> list[str]:
    """Return ordered list of category names."""
    taxonomy = _load_taxonomy()
    if taxonomy:
        return [c["name"] for c in taxonomy if "name" in c]
    return DEFAULT_CATEGORIES


def get_tags() -> list[str]:
    """Return all curated tags across all categories (for autocomplete/API)."""
    taxonomy = _load_taxonomy()
    seen: dict[str, None] = {}
    for cat in taxonomy:
        for tag in cat.get("tags", []):
            seen[str(tag)] = None
    return list(seen)


def get_tags_for_category(category: str) -> list[str]:
    """Return tags valid for a specific category. Empty list if category unknown."""
    taxonomy = _load_taxonomy()
    for cat in taxonomy:
        if cat.get("name") == category:
            return [str(t) for t in cat.get("tags", [])]
    return []


def get_category_descriptions() -> dict[str, str]:
    """Return {name: description} for all categories."""
    taxonomy = _load_taxonomy()
    return {c["name"]: c.get("description", "") for c in taxonomy if "name" in c}



def add_tag_to_category(category: str, tag: str) -> bool:
    """Add tag to a category's tag list in taxonomy.yaml, preserving file formatting and comments.
    Returns True if added, False if already present or category not found.
    """
    import re
    path = _taxonomy_path()
    if not path.exists():
        return False
    tag = tag.strip().lower()
    if not tag:
        return False

    # Check via parsed data first (authoritative duplicate check)
    existing = get_tags_for_category(category)
    if tag in existing:
        return False
    cats = _load_taxonomy()
    if not any(c.get("name") == category for c in cats):
        return False

    # Edit the raw text to preserve comments and formatting.
    # Strategy: find the category block, then append the tag after the last tag line in that block.
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Find the line with "  - name: <category>"
    cat_line_idx = None
    for i, line in enumerate(lines):
        if re.match(rf"^\s*-\s*name:\s*{re.escape(category)}\s*$", line):
            cat_line_idx = i
            break

    if cat_line_idx is None:
        return False

    # Find the "    tags:" line within this category block
    tags_line_idx = None
    next_cat_idx = len(lines)
    for i in range(cat_line_idx + 1, len(lines)):
        # Next category starts a new "  - name:" block
        if re.match(r"^\s*-\s*name:\s*\S", lines[i]) and i != cat_line_idx:
            next_cat_idx = i
            break
        if re.match(r"^\s+tags:\s*$", lines[i]):
            tags_line_idx = i

    if tags_line_idx is None:
        return False

    # Find the last tag line in this category's tags list (lines matching "      - <tag>")
    last_tag_idx = tags_line_idx  # default: insert right after "tags:" if list is empty
    for i in range(tags_line_idx + 1, next_cat_idx):
        if re.match(r"^\s+-\s+\S", lines[i]):
            last_tag_idx = i
        else:
            break  # tags block ended

    # Determine indentation from existing tags or from "tags:" line
    if last_tag_idx != tags_line_idx:
        indent = re.match(r"^(\s*)-", lines[last_tag_idx]).group(1)
    else:
        # No existing tags — use two more spaces than tags: line
        tags_indent = re.match(r"^(\s*)", lines[tags_line_idx]).group(1)
        indent = tags_indent + "  "

    new_line = f"{indent}- {tag}\n"
    lines.insert(last_tag_idx + 1, new_line)
    path.write_text("".join(lines), encoding="utf-8")
    return True
