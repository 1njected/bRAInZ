# bRAInZ MCP Server

Read-only MCP server for the bRAInZ knowledge base. Exposes search, RAG query, library browsing, and Digest page access to any MCP-compatible agent.

## Tools

| Tool | Description |
|------|-------------|
| `search` | Semantic search across the library |
| `query` | RAG — ask a question, get an AI answer grounded in the library |
| `list_library` | Browse library items with category/tag filtering |
| `get_item` | Fetch full content of a library item by ID |
| `list_categories` | List all categories with item counts |
| `list_tags` | List most common tags |
| `list_digest_pages` | List curated Digest reference pages |
| `get_digest_page` | Fetch full content of a Digest page |
| `health` | Check bRAInZ status and stats |

## Setup

```bash
cd mcp
python3 -m venv .venv
.venv/bin/pip install mcp httpx
```

## Configuration

Set environment variables (or create a `.env` file):

```env
BRAINZ_URL=http://localhost:8000
BRAINZ_KEY=your-api-key-here
```

## Running

```bash
.venv/bin/python server.py
```

## Claude Code integration

Add to your Claude Code MCP config (`~/.claude/claude_desktop_config.json` or `settings.json`):

```json
{
  "mcpServers": {
    "brainz": {
      "command": "/path/to/bRAInZ/mcp/.venv/bin/python",
      "args": ["/path/to/bRAInZ/mcp/server.py"],
      "env": {
        "BRAINZ_URL": "http://localhost:8000",
        "BRAINZ_KEY": "your-api-key-here"
      }
    }
  }
}
```
