# bRAInZ CLI Reference

The CLI runs inside the Docker container and operates directly on the filesystem — no HTTP server required.

**All commands are run via `docker exec`:**

```bash
docker exec -it brainz-brainz-1 python -m cli <command> [options]
```

Set a shell alias to reduce typing:

```bash
alias brainz='docker exec -it $(docker ps -qf name=brainz) python -m cli'
```

---

## Commands

### add-url

Fetch a URL, extract content, classify, and store.

```bash
brainz add-url <url> [--category CATEGORY] [--tags TAG1,TAG2]
```

| Argument | Description |
|----------|-------------|
| `url` | URL to fetch and ingest |
| `--category`, `-c` | Category to assign; omit to auto-classify |
| `--tags`, `-t` | Comma-separated tags; omit to auto-generate |

Examples:

```bash
# Auto-classify
brainz add-url https://portswigger.net/research/request-smuggling

# Manual category and tags
brainz add-url https://example.com/xss-writeup -c appsec -t xss,csp
```

Output:
```
Saved [appsec] XSS Writeup → a1b2c3d4
```

If the URL was already ingested:
```
Duplicate — already exists: a1b2c3d4
```

---

### import-urls

Extract all HTTP/HTTPS URLs from any text file, deduplicate, sort, and import them into the library. Works with browser bookmark exports, markdown files, plain text lists, HTML, JSON, or any format that contains URLs as text.

```bash
brainz import-urls <filepath> [--category CATEGORY] [--tags TAGS] [--rate-limit SECONDS]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `filepath` | — | Path to file containing URLs (inside the container — mount it first) |
| `--category`, `-c` | auto | Force a category for all items; omit to auto-classify |
| `--tags`, `-t` | — | Comma-separated tags to apply to all items |
| `--rate-limit` | `2.0` | Seconds to wait between requests |

Copy the file into the container, then import:

```bash
docker cp ~/Downloads/urls.txt brainz-brainz-1:/tmp/urls.txt
brainz import-urls /tmp/urls.txt
```

Force a category and tags:

```bash
brainz import-urls /tmp/redteam-links.md -c redteam -t lateral-movement,persistence
```

Output:
```
Found 84 unique URLs in /tmp/urls.txt
  [1/84] ok [appsec] XSS Writeup → a1b2c3d4
  [2/84] skip: https://already-imported.com
  [3/84] fail: https://dead-link.example.com — connection timeout
  ...
Done — Imported: 81  Skipped: 2  Failed: 1
```

---

### import-pdfs

Bulk-import all PDF files from a directory.

```bash
brainz import-pdfs <dirpath> [--no-recursive]
```

| Argument | Description |
|----------|-------------|
| `dirpath` | Directory to scan (inside the container) |
| `--no-recursive` | Only process the top-level directory, not subdirectories |

Copy PDFs into the container, then import:

```bash
docker cp ~/Documents/research/ brainz-brainz-1:/tmp/research/
brainz import-pdfs /tmp/research
```

Output:
```
Imported: 12  Skipped: 0  Failed: 1
```

---

### import-images

Bulk-import all images from a directory. Each image is analyzed by the vision LLM (or OCR fallback) to generate a text description, then classified and embedded.

Supported formats: JPG, PNG, GIF, WebP.

```bash
brainz import-images <dirpath> [--no-recursive] [--category CATEGORY] [--tags TAGS]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `dirpath` | — | Directory to scan (inside the container) |
| `--no-recursive` | — | Only scan the top-level directory |
| `--category`, `-c` | auto | Force a category for all items; omit to auto-classify |
| `--tags`, `-t` | — | Comma-separated tags to apply to all items |

```bash
docker cp ~/Screenshots/ brainz-brainz-1:/tmp/screenshots/
brainz import-images /tmp/screenshots
brainz import-images /tmp/screenshots -c redteam -t recon,osint
```

Output:
```
Found 24 image(s) in /tmp/screenshots
  [1/24] ok [appsec] Burp Suite Scan Results: SQL Injection
  [2/24] ok [redteam] Nmap Port Scan 10.0.0.0/24
  [3/24] skip: duplicate
  ...
Done — Imported: 22  Skipped: 1  Failed: 1
```

---

### reindex

Rebuild `index.json` by scanning all `metadata.yaml` files on disk. Use this after manually editing or moving files in `data/library/`.

```bash
brainz reindex
```

Output:
```
Reindexed 142 items
```

---

### stats

Show item counts by category.

```bash
brainz stats
```

Output:
```
Total items: 9  Embedded: 9

  appsec               5
  blueteam             1
  hw                   1
  mobile               1
  redteam              1
```

---

### search

Semantic search over the knowledge base. Returns the most relevant chunks with scores.

```bash
brainz search <query> [--category CATEGORY] [--top-k N]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `query` | — | Search query |
| `--category`, `-c` | all | Restrict results to a category |
| `--top-k` | `10` | Number of results to return |

Requires embeddings — run `reembed` first if needed (see [API reference](api-reference.md)).

```bash
brainz search "SSRF via redirect"
brainz search "Kerberos delegation" --category redteam --top-k 5
```

Output:
```
[0.921] Browser-Powered Desync Attacks (appsec)
  Request smuggling enables SSRF by routing requests through...

[0.884] Smashing the State Machine (appsec)
  ...
```

---

### query

RAG query — ask a question and get an answer synthesised from the knowledge base.

```bash
brainz query <question> [--category CATEGORY]
```

| Argument | Description |
|----------|-------------|
| `question` | Natural language question |
| `--category`, `-c` | Restrict context to a category |

Requires embeddings — run `reembed` first if needed.

```bash
brainz query "What are common Kerberoasting mitigations?"
brainz query "How does HTTP request smuggling enable cache poisoning?" --category appsec
```

Output:
```
Kerberoasting mitigations include enforcing AES-only encryption on service
accounts, using long random passwords (>25 chars), and monitoring for
unusual TGS-REQ traffic...

Sources:
  [0.94] Detecting and Mitigating Active Directory Attacks
  [0.87] Universal Privilege Escalation and Persistence
```

---

## Tips

**Mounting a local directory** for bulk imports without `docker cp`:

```yaml
# docker-compose.yaml — add a volume:
volumes:
  - ./data:/data
  - ~/Documents/research:/import:ro
```

Then: `brainz import-pdfs /import`

**Checking logs** if a command fails:

```bash
docker logs brainz-brainz-1 --tail 50
```
