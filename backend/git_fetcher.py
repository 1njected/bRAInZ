"""Git repository cloner and markdown TOC builder for wiki import."""

from __future__ import annotations
import asyncio
import re
from pathlib import Path
from typing import Any


async def fetch_repo(repo_id: str, url: str, data_dir: Path) -> dict[str, Any]:
    from utils import validate_url_no_ssrf
    validate_url_no_ssrf(url, allowed_schemes=("https",))
    repo_dir = data_dir / "wikis" / repo_id
    loop = asyncio.get_event_loop()
    title = await loop.run_in_executor(None, _sync_repo, url, repo_dir)
    toc, pages = await loop.run_in_executor(None, _build_toc, repo_dir)
    return {"title": title, "toc": toc, "pages": pages}


def _sync_repo(url: str, repo_dir: Path) -> str:
    import git
    repo_dir.mkdir(parents=True, exist_ok=True)
    if (repo_dir / ".git").exists():
        git.Repo(repo_dir).remotes.origin.pull()
    else:
        git.Repo.clone_from(url, repo_dir, depth=1)
    title = re.sub(r"\.git$", "", url.rstrip("/").rsplit("/", 1)[-1])
    return title.replace("-", " ").replace("_", " ")


def _build_toc(repo_dir: Path) -> tuple[list[dict], list[dict]]:
    summary = repo_dir / "SUMMARY.md"
    if summary.exists():
        return _parse_summary(repo_dir, summary)
    docs_dir = repo_dir / "docs"
    content_root = docs_dir if docs_dir.is_dir() else repo_dir
    return _toc_from_filesystem(repo_dir, content_root)


def _parse_summary(repo_dir: Path, summary_path: Path) -> tuple[list[dict], list[dict]]:
    text = summary_path.read_text(encoding="utf-8", errors="ignore")
    toc: list[dict] = []
    pages: list[dict] = []
    seen_paths: set[str] = set()
    stack: list[tuple[int, list]] = [(-1, toc)]

    for line in text.splitlines():
        if re.match(r"^#\s", line):
            continue
        m_heading = re.match(r"^(#{2,6})\s+(.+)", line)
        if m_heading:
            title = re.sub(r"<[^>]+>", "", m_heading.group(2)).strip()
            node = {"title": title, "rel_path": None, "level": 0, "children": []}
            toc.append(node)
            stack = [(-1, node["children"])]
            continue
        m = re.match(r"^(\s*)[*\-]\s+\[([^\]]*)\]\(([^)]*)\)", line)
        if m:
            indent = len(m.group(1))
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            rel_path = m.group(3).strip().replace("\\", "/").split("#")[0]
            abs_path = repo_dir / rel_path
            size = abs_path.stat().st_size if abs_path.exists() else 0
            node = {"title": title, "rel_path": rel_path or None, "level": indent // 2, "children": []}
            while len(stack) > 1 and stack[-1][0] >= indent:
                stack.pop()
            stack[-1][1].append(node)
            stack.append((indent, node["children"]))
            if rel_path and rel_path not in seen_paths:
                seen_paths.add(rel_path)
                pages.append({"rel_path": rel_path, "title": title, "size": size})
            continue
        m2 = re.match(r"^(\s*)[*\-]\s+(.+)", line)
        if m2:
            indent = len(m2.group(1))
            title = re.sub(r"<[^>]+>", "", m2.group(2)).strip()
            node = {"title": title, "rel_path": None, "level": indent // 2, "children": []}
            while len(stack) > 1 and stack[-1][0] >= indent:
                stack.pop()
            stack[-1][1].append(node)
            stack.append((indent, node["children"]))

    return toc, pages


def _toc_from_filesystem(repo_dir: Path, content_root: Path) -> tuple[list[dict], list[dict]]:
    pages: list[dict] = []

    def _build_dir(directory: Path, level: int) -> list[dict]:
        nodes: list[dict] = []
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return nodes
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                children = _build_dir(entry, level + 1)
                if children:
                    nodes.append({"title": entry.name.replace("-", " ").replace("_", " ").title(),
                                  "rel_path": None, "level": level, "children": children})
            elif entry.suffix.lower() == ".md":
                rel_str = str(entry.relative_to(repo_dir)).replace("\\", "/")
                title = _page_title(entry, rel_str)
                size = entry.stat().st_size
                nodes.append({"title": title, "rel_path": rel_str, "level": level, "children": []})
                pages.append({"rel_path": rel_str, "title": title, "size": size})
        return nodes

    return _build_dir(content_root, 0), pages


def _page_title(md_file: Path, rel_path: str) -> str:
    try:
        for line in md_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("#"):
                m = re.match(r"^#+ *(.+)", line)
                if m:
                    return m.group(1).strip()
            if line:
                break
    except Exception:
        pass
    stem = md_file.stem.replace("-", " ").replace("_", " ")
    return stem if stem.lower() not in ("readme", "summary", "index") else rel_path
