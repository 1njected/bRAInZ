# bRAInZ API Reference

All endpoints require the `X-API-Key` header (unless the server has no API keys configured).

**Base URL**: `http://localhost:8000`

---

## Authentication

```bash
curl -H "X-API-Key: your-key" http://localhost:8000/api/health
```

---

## System

### GET /api/health

Health check and statistics.

```bash
curl -H "X-API-Key: $KEY" http://localhost:8000/api/health
```

Response:
```json
{
  "status": "ok",
  "total_items": 142,
  "categories": {"appsec": 45, "netsec": 30},
  "llm_provider": "ollama/llama3.1:8b",
  "embedded_items": 140
}
```

### POST /api/reindex

Rebuild `index.json` from filesystem (use after manual file changes).

```bash
curl -X POST -H "X-API-Key: $KEY" http://localhost:8000/api/reindex
```

### POST /api/reembed

Re-embed all items (use after switching embedding model).

```bash
curl -X POST -H "X-API-Key: $KEY" http://localhost:8000/api/reembed
```

### GET /api/config/categories

List configured categories.

### GET /api/config/llm

Current LLM provider configuration.

---

## Ingestion

### POST /api/ingest/url

Fetch a URL, extract text, classify, and store.

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article", "category": "appsec", "tags": ["xss", "csp"]}' \
  http://localhost:8000/api/ingest/url
```

Body:
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | yes | URL to fetch |
| `category` | string | no | One of the configured categories; omit to auto-classify |
| `tags` | string[] | no | Topic tags; omit to auto-generate |

Response:
```json
{
  "item_id": "a1b2c3d4",
  "title": "Page Title",
  "category": "appsec",
  "tags": ["xss", "csp"],
  "duplicate": false
}
```

### POST /api/ingest/pdf

Upload a PDF file.

```bash
curl -X POST -H "X-API-Key: $KEY" \
  -F "file=@/path/to/report.pdf" \
  -F "category=reversing" \
  http://localhost:8000/api/ingest/pdf
```

### POST /api/ingest/text

Store a text note.

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"title": "My Note", "body": "Content here...", "category": "misc"}' \
  http://localhost:8000/api/ingest/text
```

### POST /api/ingest/bulk-urls

Batch URL ingestion (rate-limited, 1s between requests).

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"urls": [{"url": "https://a.com"}, {"url": "https://b.com", "category": "netsec"}]}' \
  http://localhost:8000/api/ingest/bulk-urls
```

---

## Library

### GET /api/items

List and filter items.

```bash
# All items
curl -H "X-API-Key: $KEY" "http://localhost:8000/api/items"

# Filter by category
curl -H "X-API-Key: $KEY" "http://localhost:8000/api/items?category=appsec"

# Filter by tag + text search
curl -H "X-API-Key: $KEY" "http://localhost:8000/api/items?tag=jwt&q=attack"

# Paginate
curl -H "X-API-Key: $KEY" "http://localhost:8000/api/items?limit=20&offset=40"
```

Query params: `category`, `tag`, `q` (text search), `limit` (default 50), `offset` (default 0)

### GET /api/items/{id}

Get item metadata and content.

```bash
curl -H "X-API-Key: $KEY" http://localhost:8000/api/items/a1b2c3d4
```

### GET /api/items/{id}/content

Get raw `content.md` as plain text.

### PATCH /api/items/{id}

Update item metadata.

```bash
curl -X PATCH -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"category": "netsec", "tags": ["wifi", "wpa2"]}' \
  http://localhost:8000/api/items/a1b2c3d4
```

### DELETE /api/items/{id}

Delete an item.

```bash
curl -X DELETE -H "X-API-Key: $KEY" http://localhost:8000/api/items/a1b2c3d4
```

### POST /api/items/{id}/reclassify

Re-run LLM classification on an existing item.

### GET /api/categories

List categories with item counts.

### GET /api/tags

List all tags sorted by frequency.

---

## RAG / Search

### POST /api/query

RAG query — answer a question using the knowledge base.

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"question": "What are common Kerberoasting mitigations?", "category": "ad-hacking"}' \
  http://localhost:8000/api/query
```

Body:
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `question` | string | required | Your question |
| `category` | string | null | Restrict to category |
| `tags` | string[] | null | Restrict to items with these tags |
| `top_k` | int | 8 | Number of chunks to use as context |

Response:
```json
{
  "answer": "Kerberoasting mitigations include...",
  "sources": [
    {"item_id": "a1b2c3d4", "title": "AD Attack Guide", "url": null, "relevance_score": 0.92}
  ]
}
```

### POST /api/search

Semantic search — find relevant chunks without generating an answer.

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"query": "JWT algorithm confusion attack", "top_k": 5}' \
  http://localhost:8000/api/search
```

---

## Skills

### POST /api/skills/generate

Generate a SKILL.md quick-reference from the knowledge base.

```bash
curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"topic": "kerberoasting", "categories": ["ad-hacking"]}' \
  http://localhost:8000/api/skills/generate
```

### GET /api/skills

List all generated skills.

### GET /api/skills/{topic}

Get a SKILL.md file as plain text.

```bash
curl -H "X-API-Key: $KEY" http://localhost:8000/api/skills/kerberoasting
```
