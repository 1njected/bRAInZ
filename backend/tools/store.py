"""GitHub Stars tool subscription storage — reads/writes /data/tools.yaml."""

from __future__ import annotations
import uuid
from pathlib import Path
from typing import Any

import yaml

_TOOLS_FILE = "tools.yaml"
_MAX_SEEN = 5000


def _tools_path(data_dir: Path) -> Path:
    return data_dir / _TOOLS_FILE


def load_tools(data_dir: Path) -> list[dict[str, Any]]:
    path = _tools_path(data_dir)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("tools", [])


def save_tools(data_dir: Path, tools: list[dict[str, Any]]) -> None:
    path = _tools_path(data_dir)
    path.write_text(yaml.dump({"tools": tools}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def add_tool(data_dir: Path, username: str, title: str) -> dict[str, Any]:
    tools = load_tools(data_dir)
    for t in tools:
        if t["username"].lower() == username.lower():
            return t
    tool: dict[str, Any] = {
        "id": uuid.uuid4().hex[:8],
        "username": username,
        "title": title or username,
        "enabled": True,
        "auto_ingest": False,
        "last_fetched": None,
        "last_error": None,
        "seen_ids": [],
        "latest_ids": [],
    }
    tools.append(tool)
    save_tools(data_dir, tools)
    return tool


def remove_tool(data_dir: Path, tool_id: str) -> bool:
    tools = load_tools(data_dir)
    new_tools = [t for t in tools if t["id"] != tool_id]
    if len(new_tools) == len(tools):
        return False
    save_tools(data_dir, new_tools)
    return True


def update_tool(data_dir: Path, tool_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    tools = load_tools(data_dir)
    for tool in tools:
        if tool["id"] == tool_id:
            tool.update(updates)
            save_tools(data_dir, tools)
            return tool
    return None


def get_tool(data_dir: Path, tool_id: str) -> dict[str, Any] | None:
    for t in load_tools(data_dir):
        if t["id"] == tool_id:
            return t
    return None


def set_latest_ids(data_dir: Path, tool_id: str, ids: list[str]) -> None:
    tools = load_tools(data_dir)
    for tool in tools:
        if tool["id"] == tool_id:
            tool["latest_ids"] = ids
            save_tools(data_dir, tools)
            return


def mark_ids_seen(data_dir: Path, tool_id: str, ids: list[str]) -> dict[str, Any] | None:
    tools = load_tools(data_dir)
    for tool in tools:
        if tool["id"] == tool_id:
            seen = set(tool.get("seen_ids") or [])
            seen.update(ids)
            tool["seen_ids"] = list(seen)[-_MAX_SEEN:]
            save_tools(data_dir, tools)
            return tool
    return None
