# bRAInZ MCP Server

Read-only access to your knowledge base for Claude Code, Claude Desktop, and Claude.ai.

> **Claude Desktop** only supports `stdio` — it cannot connect to a remote MCP server directly. Use the local proxy approach below, or switch to Claude Code for remote access.

---

## Tools

| Tool | Description |
|------|-------------|
| `health` | Status and basic stats |
| `list_categories` | All categories with item counts |
| `list_tags` | Most common tags |
| `list_library` | Browse items with optional category/tag filter |
| `get_item` | Full content of an item by ID |
| `search` | Semantic search across the library |
| `query` | RAG — AI-generated answer grounded in the library |
| `list_digest_pages` | List Digest pages |
| `get_digest_page` | Full content of a Digest page |

---

## Setup

```bash
cd mcp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

---

## Claude Code — local

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "brainz": {
      "command": "/path/to/bRAInZ/mcp/.venv/bin/python",
      "args": ["/path/to/bRAInZ/mcp/server.py"],
      "env": {
        "BRAINZ_URL": "http://localhost:8000",
        "BRAINZ_KEY": "your-api-key"
      }
    }
  }
}
```

## Claude Code — remote (stdio proxy)

The MCP server runs locally and proxies requests to a remote bRAInZ over Tailscale. No server-side changes needed.

```json
{
  "mcpServers": {
    "brainz": {
      "command": "/path/to/bRAInZ/mcp/.venv/bin/python",
      "args": ["/path/to/bRAInZ/mcp/server.py"],
      "env": {
        "BRAINZ_URL": "http://<tailscale-hostname>:8000",
        "BRAINZ_KEY": "your-api-key"
      }
    }
  }
}
```

## Claude Code — remote (HTTP)

Requires the MCP server running on the remote host with Tailscale HTTPS. See [Remote deployment](#remote-deployment-via-tailscale) below.

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "brainz": {
      "type": "http",
      "url": "https://<tailscale-hostname>.ts.net/mcp",
      "headers": {
        "Authorization": "Bearer your-mcp-bearer-token"
      }
    }
  }
}
```

## Claude Desktop

Supports `stdio` only. Use the same config as **Claude Code — local** or **Claude Code — remote (stdio proxy)** above, placing it in:

`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

---

## Remote deployment via Tailscale

`docker-compose-tailscale-mcp.yaml` runs bRAInZ, the MCP server, and Tailscale in a shared network namespace. Tailscale Serve terminates TLS and proxies `https://<hostname>.ts.net/mcp` → MCP on port 8002.

**`.env`:**

```bash
USETAILSCALE=true
USEMCP=true
TAILSCALE_AUTH_KEY=tskey-auth-...
TAILSCALE_HOSTNAME=brainz
API_KEYS=your-brainz-api-key
MCP_BEARER_TOKEN=your-mcp-bearer-token
MCP_PORT=8002
```

**Deploy:**

```bash
make deploy
```

---

## Tool reference

### `search`
```
query    – natural language or keywords
top_k    – max results (default 10)
category – optional filter
tag      – optional filter
```
Returns: `[{item_id, title, category, url, snippet}]`

### `query`
```
question – the question to answer
category – optional filter
top_k    – source chunks to retrieve (default 8)
```
Returns: `{answer, sources: [{item_id, title, url}]}`

### `list_library`
```
category – optional filter
tag      – optional filter
limit    – max items (default 50)
offset   – pagination offset
```
Returns: `{total, items: [{item_id, title, category, tags, url, added, summary}]}`

### `get_item`
```
item_id – 8-character item ID
```
Returns: full item with `content` (markdown)

### `list_digest_pages`
```
category – optional filter
```
Returns: `[{page_id, title, category, tags, updated, word_count}]`

### `get_digest_page`
```
page_id – "category/slug"  e.g. "redteam/sliver"
```
Returns: full page with `content` (markdown)
