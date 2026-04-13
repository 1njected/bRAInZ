# bRAInZ — System Overview

Personal security knowledge base. Ingests URLs, PDFs, and text → classifies → chunks → embeds → enables semantic search and RAG Q&A.

---

## Architecture

```
Frontend (single HTML, vanilla JS + marked.js)
    ↕ REST
FastAPI backend (Python 3.12, single worker, port 8000)
    ↓
pipeline.py → ingestion → classifier → storage → RAG
    ↓
/data/ (filesystem, no database)
```

Deployed via Docker. `/data` is a volume mount. Ollama runs on host; reached via `host.docker.internal`.

---

## Data Layout

```
/data/
├── config.yaml              # LLM provider + ingestion + RAG settings
├── taxonomy.yaml            # Categories + per-category tag allowlists (re-read on change)
├── corrections.yaml         # Manual corrections used for k-NN pre-classification
├── index.json               # In-memory item index (rebuilt from filesystem on startup)
├── library/
│   └── {category}/
│       └── {year_slug}/
│           ├── metadata.yaml
│           ├── content.md       # Full markdown (with images, for display)
│           ├── content_llm.md   # Image-stripped variant (for chunking/embedding)
│           ├── snapshot.html    # Self-contained HTML (URLs only)
│           ├── original.pdf
│           ├── chunks.json
│           └── assets/          # Base64 blobs extracted from snapshot
├── embeddings/
│   ├── {item_id}.npz        # Per-item L2-normalized chunk vectors
│   ├── index.npz            # Combined vector matrix (all items)
│   └── chunk_map.json       # Maps matrix row → {item_id, chunk_index}
└── skills/
    └── {slug}/SKILL.md
```

---

## Ingest Flow

```
POST /api/ingest/url|pdf|text
  → extract (title, content_md, snapshot, pub_date)
  → dedup (content_hash → skip if exists)
  → classify (k-NN on corrections → LLM two-pass if no match)
  → save_item (write files, update index.json)
  → chunk_item (paragraph-aware, overlapping ~400 tokens)
  → embed_item (LLM embed → .npz → rebuild index.npz)
```

**URL ingestion specifics:**
- `<pre>` blocks protected before trafilatura runs (prevent code mangling)
- Snapshots built by `monolith` binary; large CSS skipped if > threshold (HEAD request check)
- Base64 blobs > 75KB extracted to `assets/` recursively (including nested in CSS)
- Two content versions: `content.md` (images kept) / `content_llm.md` (images stripped)

**Classification (two-pass LLM):**
1. Category + summary from title/description/body excerpt
2. Tags from category's allowlist in taxonomy.yaml
- k-NN pre-classification skips LLM if corrected items match at ≥ 0.85 similarity

---

## RAG / Search

**Semantic search:** embed query → dot product against `index.npz` → retrieve top-k chunks → return with text  
**RAG query:** semantic search → build context → LLM with "security expert" system prompt → answer + cited sources  
**Skills:** generate SKILL.md from top-N chunks on a topic (manual trigger, not auto)

Vectors are L2-normalized at embed time so dot product == cosine similarity.

---

## LLM Providers

Configured via `config.yaml` (`llm.provider`). Override with `LLM_PROVIDER` env var.

| Provider | Classification model | Query model | Embedding model |
|---|---|---|---|
| `ollama` | llama3.1:8b | llama3.1:8b | nomic-embed-text (768d) |
| `anthropic` | claude-haiku-4-5 | claude-sonnet-4-6 | voyage-3 (1024d) |
| `openai` | gpt-4o-mini | gpt-4o | text-embedding-3-small (1536d) |
| `openai_compatible` | configurable | configurable | configurable |

Classification and query use separate models (cheap/fast for classify, strong for query).

---

## Key Modules

| Path | Role |
|---|---|
| `api.py` | FastAPI routes, auth middleware, static file serving |
| `pipeline.py` | Orchestrates all ingest flows; `_dedup_check`, `_classify_or_manual` helpers |
| `ingestion/url.py` | HTTP fetch, HTML→markdown, snapshot, pub_date detection |
| `ingestion/pdf.py` | pymupdf extraction |
| `ingestion/text.py` | Raw text ingest |
| `classifier/classify.py` | Two-pass LLM classification |
| `classifier/knn.py` | k-NN pre-classification from corrections |
| `storage/filesystem.py` | Write/read/delete item files; base64 extraction |
| `storage/index.py` | `ItemIndex` — in-memory dict + `index.json`; asyncio.Lock on all writes |
| `storage/corrections.py` | Read/write corrections.yaml |
| `rag/chunker.py` | Paragraph-aware chunker → `chunks.json` |
| `rag/embedder.py` | Embed chunks → `.npz`; rebuild `index.npz` |
| `rag/search.py` | `VectorIndex` — cosine search over combined matrix |
| `rag/query.py` | RAG pipeline (search → LLM → answer + sources) |
| `rag/skills.py` | SKILL.md generation |
| `llm/router.py` | `create_provider(config)` factory |
| `config.py` | Load config.yaml; taxonomy with mtime-based cache |
| `utils.py` | `now_iso()`, `slug()`, `content_hash()` |
| `auth.py` | API key middleware; dev mode if `API_KEYS` unset |

---

## Auth

- Header `X-API-Key` or query param `key`
- Dev mode (no auth) if `API_KEYS` env var is empty
- Asset paths (`/api/items/{id}/assets/*`) exempt from auth (needed for snapshot iframes)

---

## Frontend

Single file: `frontend/static/index.html`. No build step.  
Vanilla JS, CSS variables, dark theme. marked.js for markdown rendering.  
Views per item: **Snapshot** (iframe) | **Markdown** (rendered content.md).

---

## Notable Patterns

- **No database** — filesystem + JSON index. Human-auditable, Git-friendly.
- **Atomic saves** — write to `.tmp`, then `os.replace()`.
- **Two content files** — images in `content.md` for display; stripped in `content_llm.md` for embedding (avoids token bloat from base64).
- **Per-item .npz** — easy to delete/re-embed individual items without rebuilding all.
- **Taxonomy mtime cache** — re-reads `taxonomy.yaml` only when file changes.
- **Index lock** — `asyncio.Lock` on all `index.json` writes to prevent concurrent corruption.
