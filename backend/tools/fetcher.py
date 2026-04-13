"""GitHub starred-repos fetcher with README download and rate-limit awareness."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

_GH_API = "https://api.github.com"
_RATE_LIMIT_STOP = 5   # stop paginating if remaining calls drop below this


def _headers(token: str | None) -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _repos_cache_path(data_dir: Path, tool_id: str) -> Path:
    return data_dir / "tools" / f".repos_{tool_id}.json"


def load_repos_cache(data_dir: Path, tool_id: str) -> list[dict[str, Any]] | None:
    """Return cached repo list for a tool account, or None if not yet fetched."""
    p = _repos_cache_path(data_dir, tool_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_repos_cache(data_dir: Path, tool_id: str, repos: list[dict[str, Any]]) -> None:
    p = _repos_cache_path(data_dir, tool_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(repos), encoding="utf-8")


def _readme_dir(data_dir: Path, full_name: str) -> Path:
    """Return /data/tools/{owner}/{repo}/"""
    return data_dir / "tools" / full_name


def _meta_path(data_dir: Path, full_name: str) -> Path:
    return _readme_dir(data_dir, full_name) / ".meta.json"


def _load_meta(data_dir: Path, full_name: str) -> dict:
    p = _meta_path(data_dir, full_name)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_meta(data_dir: Path, full_name: str, meta: dict) -> None:
    p = _meta_path(data_dir, full_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta), encoding="utf-8")


async def _download_readme(client: httpx.AsyncClient, full_name: str,
                            updated_at: str, data_dir: Path) -> str | None:
    """Download README for a repo if it has changed since last fetch.

    Returns the local file path (relative to data_dir) or None if unavailable.
    """
    meta = _load_meta(data_dir, full_name)
    readme_file = _readme_dir(data_dir, full_name) / "README.md"

    # Skip if unchanged
    if readme_file.exists() and meta.get("updated_at") == updated_at:
        return str(readme_file)

    try:
        resp = await client.get(f"{_GH_API}/repos/{full_name}/readme")
        if resp.status_code in (404, 429, 403):
            return None
        resp.raise_for_status()
        data = resp.json()
        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        readme_file.parent.mkdir(parents=True, exist_ok=True)
        readme_file.write_text(content, encoding="utf-8")
        _save_meta(data_dir, full_name, {"updated_at": updated_at})
        return str(readme_file)
    except Exception as exc:
        log.warning("README fetch failed for %s: %s", full_name, exc)
        return None


async def fetch_starred(username: str, token: str | None, data_dir: Path) -> list[dict[str, Any]]:
    """Fetch all starred repos for a GitHub user, downloading READMEs.

    Returns list of repo dicts:
        {node_id, full_name, html_url, description, topics, language,
         stargazers_count, updated_at, readme_path}
    """
    repos: list[dict[str, Any]] = []
    headers = _headers(token)

    async with httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=True) as client:
        page = 1
        while True:
            resp = await client.get(
                f"{_GH_API}/users/{username}/starred",
                params={"per_page": 100, "page": page},
            )

            # Handle rate limiting gracefully — return what we have so far
            if resp.status_code == 429 or resp.status_code == 403:
                reset = resp.headers.get("X-RateLimit-Reset", "")
                log.warning("GitHub rate limited (HTTP %d). Reset at %s. Returning %d repos collected so far.",
                            resp.status_code, reset, len(repos))
                break

            resp.raise_for_status()

            # Proactive rate limit check
            remaining = int(resp.headers.get("X-RateLimit-Remaining", 999))
            if remaining < _RATE_LIMIT_STOP:
                log.warning("GitHub rate limit low (%d remaining) — stopping pagination", remaining)
                break

            batch = resp.json()
            if not batch:
                break

            for repo in batch:
                full_name = repo["full_name"]
                updated_at = repo.get("updated_at", "")
                readme_path = await _download_readme(client, full_name, updated_at, data_dir)

                # Check rate limit again after README fetch
                remaining = int(resp.headers.get("X-RateLimit-Remaining", 999))
                if remaining < _RATE_LIMIT_STOP:
                    log.warning("GitHub rate limit low after README fetch — stopping")
                    repos.append(_repo_dict(repo, readme_path))
                    return repos

                repos.append(_repo_dict(repo, readme_path))

            page += 1

    return repos


def _repo_dict(repo: dict, readme_path: str | None) -> dict[str, Any]:
    return {
        "node_id": repo["node_id"],
        "full_name": repo["full_name"],
        "html_url": repo["html_url"],
        "description": repo.get("description") or "",
        "topics": repo.get("topics") or [],
        "language": repo.get("language") or "",
        "stargazers_count": repo.get("stargazers_count", 0),
        "updated_at": repo.get("updated_at", ""),
        "readme_path": readme_path,
    }
