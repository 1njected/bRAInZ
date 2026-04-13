# bRAInZ MCP Server

The bRAInZ MCP server exposes read-only access to your knowledge base for any MCP-compatible AI agent — including Claude Code, Claude Desktop, Cursor, and custom agents built with the Claude SDK.

[!CAUTION]
asdasdasd
---

## Tools

| Tool | Description |
|------|-------------|
| `health` | Check bRAInZ status and get item counts per category |
| `list_categories` | List all categories with item counts |
| `list_tags` | List the most common tags |
| `list_library` | Browse library items with optional category/tag filtering |
| `get_item` | Fetch full content of a library item by ID |
| `search` | Semantic search across the library |
| `query` | RAG — ask a question, get an AI-generated answer grounded in the library |
| `list_digest_pages` | List curated Digest reference pages |
| `get_digest_page` | Fetch full content of a Digest page by ID |

---

## Setup

The MCP server lives in `mcp/` and requires its own Python environment.

```bash
cd mcp
python3 -m venv .venv
.venv/bin/pip install mcp httpx
```

---

## Configuration

The server reads two environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BRAINZ_URL` | `http://localhost:8000` | Base URL of the bRAInZ API |
| `BRAINZ_KEY` | _(empty)_ | API key (leave empty for open-access installs) |

---

## Claude Code

Add the server to `~/.claude/settings.json`:

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

Then restart Claude Code. The tools will appear automatically.

**Example prompts:**

- *"Search bRAInZ for SSRF techniques"*
- *"Query bRAInZ: how do I exploit Kerberoasting?"*
- *"List my bRAInZ digest pages in the redteam category"*
- *"Get the full content of bRAInZ item a1b2c3d4"*

---

## Claude Desktop

Add the same block to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) and restart Claude Desktop.

---

## Running manually

```bash
cd mcp
BRAINZ_URL=http://localhost:8000 BRAINZ_KEY=your-key .venv/bin/python server.py
```

---

## Tool reference

### `search`

Semantic (vector) search over the library. Best for finding items related to a topic.

```
query    – natural language or keywords
top_k    – max results (default 10)
category – optional category filter
tag      – optional tag filter
```

Returns: list of `{item_id, title, category, url, snippet}`

---

### `query`

RAG query — retrieves relevant chunks and generates an answer using the configured LLM.

```
question – the question to answer
category – optional category to restrict retrieval
top_k    – number of source chunks (default 8)
```

Returns: `{answer, sources: [{item_id, title, url}]}`

---

### `list_library`

Browse the library index without semantic search. Useful for enumerating items in a category.

```
category – filter by category
tag      – filter by tag
limit    – max items (default 50)
offset   – pagination offset
```

Returns: `{total, items: [{item_id, title, category, tags, url, added, summary}]}`

---

### `get_item`

Fetch the full markdown content of a single library item.

```
item_id – 8-character item ID (from search or list_library results)
```

Returns: full item including `content` (markdown)

---

### `list_digest_pages`

List all Digest pages — curated reference notes generated from library items.

```
category – optional filter
```

Returns: list of `{page_id, title, category, tags, updated, word_count}`

---

### `get_digest_page`

Fetch the full markdown content of a Digest page.

```
page_id – format "category/slug"  e.g. "redteam/sliver"
```

Returns: full page including `content` (markdown)
