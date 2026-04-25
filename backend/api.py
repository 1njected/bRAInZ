"""FastAPI application — routes and middleware."""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from auth import APIKeyMiddleware, get_api_keys
from config import (get_config, get_categories, get_tags, get_tags_for_category,
                    add_tag_to_category, DATA_DIR)
from models import (
    IngestURLRequest, IngestSnapshotRequest, IngestTextRequest, BulkURLRequest,
    IngestResponse, BulkIngestResponse,
    ItemMetadata, ItemDetail, ItemListResponse, UpdateItemRequest,
    CategoryInfo, TagInfo,
    QueryRequest, SearchRequest, QueryResponse, SearchResponse,
    GenerateSkillRequest, SkillInfo,
    GeneratePlanRequest, PlanInfo, PlanResponse,
    GenerateDigestPageRequest, DigestPageInfo, DigestPageDetail, UpdateDigestPageRequest,
    FetchRepoRequest, ImportDigestPagesRequest, ImportDigestPagesResponse, UploadDigestPageResponse,
    HealthResponse, LLMConfigResponse,
    FeedInfo, AddFeedRequest, UpdateFeedRequest, FeedPreviewResponse,
    ToolInfo, AddToolRequest, UpdateToolRequest, StarredRepo, ToolPreviewResponse,
)

app = FastAPI(title="bRAInZ", version="0.1.0")

_cors_origins = get_config().get("server", {}).get("cors_origins", ["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(APIKeyMiddleware)

# ---------------------------------------------------------------------------
# Tools refresh state
# ---------------------------------------------------------------------------
# Maps tool_id -> username for accounts currently being fetched
_tools_refreshing: dict[str, str] = {}

log = logging.getLogger(__name__)


def _clean_llm_error(e: Exception) -> str:
    """Return a concise, human-readable message from LLM API exceptions.

    Strips the raw JSON/dict repr that SDKs append to HTTP error strings so
    the UI sees e.g. "429 RESOURCE_EXHAUSTED: You exceeded your quota" rather
    than a 400-char Python dict.
    """
    import re
    msg = str(e)
    status_m = re.match(r'^(\d{3}\s+\S+)', msg)
    inner_m  = re.search(r"""['"]message['"]\s*:\s*['"]([^'"\\]+)""", msg)
    if status_m:
        status = status_m.group(1)
        if inner_m:
            detail = inner_m.group(1).split('\n')[0].split('\\n')[0]
            return f"{status}: {detail}"
        return status
    return msg

# Route llm.* logs to stderr alongside uvicorn output
_llm_log = logging.getLogger("llm")
_llm_log.setLevel(logging.INFO)
if not _llm_log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    _llm_log.addHandler(_h)


def _get_refresh_interval(section: str, default: int) -> int:
    return get_config().get(section, {}).get("refresh_interval_minutes", default)


def _set_refresh_interval(section: str, default: int, body: dict) -> dict:
    """Read config.yaml, update refresh_interval_minutes for section, write back. Returns response dict."""
    import yaml as _yaml
    config_path = DATA_DIR / "config.yaml"
    raw = _yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    raw = raw or {}
    if section not in raw:
        raw[section] = {}
    if "refresh_interval_minutes" in body:
        val = int(body["refresh_interval_minutes"])
        if val < 1:
            raise HTTPException(400, "refresh_interval_minutes must be >= 1")
        raw[section]["refresh_interval_minutes"] = val
    config_path.write_text(_yaml.dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"refresh_interval_minutes": raw[section].get("refresh_interval_minutes", default)}


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

# Paths that are not worth logging (noise)
_LOG_SKIP_PREFIXES = ("/static", "/api/items/")
_LOG_SKIP_SUFFIXES = ("/assets/", "/snapshot", "/original")
_LOG_SKIP_EXACT    = ("/", "/api/health", "/api/config/categories",
                      "/api/config/tags", "/api/config/llm",
                      "/api/categories", "/api/tags")


def _setup_logger() -> logging.Logger:
    log_dir = Path(os.environ.get("DATA_DIR", "/data")) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("brainz.access")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_dir / "access.log",
            when="midnight",
            interval=1,
            backupCount=90,
            encoding="utf-8",
            utc=True,
        )
        handler.suffix = "%Y-%m-%d"
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
    return logger


_access_log: logging.Logger | None = None


def _should_log(path: str) -> bool:
    if path in _LOG_SKIP_EXACT:
        return False
    for p in _LOG_SKIP_PREFIXES:
        if path.startswith(p):
            # Still log item-level CRUD (PATCH/DELETE) even under /api/items/
            return False
    for s in _LOG_SKIP_SUFFIXES:
        if path.endswith(s):
            return False
    return True


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    global _access_log
    if _access_log is None:
        _access_log = _setup_logger()

    t0 = time.monotonic()
    response = await call_next(request)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    path = request.url.path
    method = request.method

    # Always log mutating requests; skip noisy read-only endpoints
    if method in ("POST", "PUT", "PATCH", "DELETE") or _should_log(path):
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        client = request.client.host if request.client else "-"
        qs = f"?{request.url.query}" if request.url.query else ""
        _access_log.info(
            '%s %s %s%s %s %dms',
            ts, method, path, qs, response.status_code, elapsed_ms,
        )

    return response

# Lazy-loaded singletons (set during startup)
_llm = None
_index = None
_vector_index = None


@app.on_event("startup")
async def startup():
    global _llm, _index, _vector_index
    import concurrent.futures
    loop = asyncio.get_event_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=20))

    from llm.router import create_provider
    from storage.index import ItemIndex
    from rag.search import VectorIndex

    config = get_config()
    _llm = create_provider(config)
    _index = ItemIndex(DATA_DIR)
    await _index.load()

    _vector_index = VectorIndex(DATA_DIR)
    _vector_index.load()

    if not get_api_keys():
        log.warning(
            "⚠ API_KEYS is not set — bRAInZ is running in OPEN ACCESS mode. "
            "Anyone who can reach this server has full access. "
            "Set the API_KEYS environment variable to enable authentication."
        )

    asyncio.create_task(_feed_refresh_loop())


async def _feed_refresh_loop():
    """Background task: refresh all enabled feeds at the configured interval."""
    import datetime
    from rssfeeds.store import load_feeds, update_feed as _update_feed, set_latest_urls
    from rssfeeds.fetcher import fetch_feed, save_feed_cache

    while True:
        interval_minutes = get_config().get("feeds", {}).get("refresh_interval_minutes", 60)
        await asyncio.sleep(max(1, interval_minutes) * 60)
        feeds = load_feeds(DATA_DIR)
        for feed in feeds:
            if not feed.get("enabled", True):
                continue
            try:
                data = await fetch_feed(feed["url"])
                save_feed_cache(DATA_DIR, feed["id"], data)
                urls = [e["url"] for e in data["entries"][:50] if e.get("url")]
                set_latest_urls(DATA_DIR, feed["id"], urls)
                now = datetime.datetime.utcnow().isoformat() + "Z"
                updates: dict = {"last_fetched": now, "last_error": None}
                if data.get("title"):
                    updates["title"] = data["title"]
                _update_feed(DATA_DIR, feed["id"], updates)
            except Exception as exc:
                _update_feed(DATA_DIR, feed["id"], {"last_error": str(exc)})


def get_llm():
    if _llm is None:
        raise HTTPException(503, "LLM provider not initialised")
    return _llm


def get_index():
    if _index is None:
        raise HTTPException(503, "Index not initialised")
    return _index


def get_vector_index():
    return _vector_index  # May be None if no embeddings yet


def _llm_with_model(llm, model: str):
    """Return a thin wrapper around llm that overrides the query model for complete()."""
    import copy
    wrapped = copy.copy(llm)
    wrapped._query_model = model
    return wrapped


# ---------------------------------------------------------------------------
# Health / System
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse)
async def health():
    config = get_config()
    index = get_index()
    provider_name = config["llm"]["provider"]
    items = index.all_items()
    cat_counts: dict[str, int] = {}
    embedded = 0
    for m in items.values():
        cat_counts[m.get("category", "misc")] = cat_counts.get(m.get("category", "misc"), 0) + 1
        if m.get("embedded"):
            embedded += 1
    return HealthResponse(
        status="ok",
        total_items=len(items),
        categories=cat_counts,
        llm_provider=provider_name,
        embedded_items=embedded,
        open_access=not bool(get_api_keys()),
    )


@app.post("/api/reindex")
async def reindex():
    index = get_index()
    count = await index.rebuild()
    return {"rebuilt": count}


@app.post("/api/reembed")
async def reembed():
    from rag.embedder import embed_all
    index = get_index()
    llm = get_llm()
    count = await embed_all(DATA_DIR, llm, index, vector_index=_vector_index)
    return {"embedded": count}


@app.get("/api/config/categories")
async def config_categories():
    return get_categories()


@app.get("/api/config/tags/{category}")
async def config_tags_for_category(category: str):
    return get_tags_for_category(category)


@app.post("/api/config/tags/{category}")
async def add_tag_to_category_endpoint(category: str, body: dict):
    tag = (body.get("tag") or "").strip().lower()
    if not tag:
        raise HTTPException(400, "tag is required")
    added = add_tag_to_category(category, tag)
    return {"added": added, "tag": tag, "category": category}


@app.post("/api/items/{item_id}/suggest-tags")
async def suggest_tags_for_item(item_id: str, body: dict):
    """Suggest tags for an item given a chosen category, using the item's own content."""
    import re as _re, json as _json
    from storage.filesystem import load_item
    from config import get_category_descriptions

    category = (body.get("category") or "").strip().lower()
    if not category:
        raise HTTPException(400, "category is required")

    item = load_item(item_id, get_index(), DATA_DIR)
    if not item:
        raise HTTPException(404, "Item not found")

    # Tags already on the item in the editor — don't repeat these
    current_tags: list[str] = [str(t).lower().strip() for t in (body.get("existing_tags") or [])]
    allowed_tags = get_tags_for_category(category)
    description = get_category_descriptions().get(category, "")

    # Use title + summary + short content excerpt as document signal
    cfg = get_config().get("ingestion", {})
    body_words = cfg.get("classifier_body_words", 100)
    content = item.get("content", "")
    excerpt = " ".join(content.split()[:body_words])

    system = (
        "You are an IT security content tagger.\n"
        "Given a document and a target category, suggest specific tags that accurately describe "
        "the techniques, tools, protocols, or concepts present in this document.\n"
        "Rules:\n"
        "- Return ONLY a JSON array of strings, nothing else.\n"
        "- 3–8 tags, most relevant first.\n"
        "- Use lowercase, hyphenated format (e.g. 'heap-overflow', 'rop-chain').\n"
        "- Only suggest tags that are directly supported by the document content.\n"
        "- Do NOT include any tag from the 'Already assigned' list.\n"
        "- Prefer specific terms over generic ones."
    )

    allowed_str = ", ".join(allowed_tags) if allowed_tags else "none"
    current_str = ", ".join(current_tags) if current_tags else "none"
    user = (
        f"TITLE: {item.get('title', '')}\n"
        f"SUMMARY: {item.get('summary', '')}\n"
        f"BODY (first {body_words} words):\n{excerpt}\n\n"
        f"Target category: {category} — {description}\n"
        f"Allowed tags for this category (prefer these if they fit): {allowed_str}\n"
        f"Already assigned (do NOT repeat): {current_str}\n\n"
        "Suggest additional tags as a JSON array."
    )

    llm = get_llm()
    if hasattr(llm, "complete_classify"):
        raw = await llm.complete_classify(system, user)
    else:
        raw = await llm.complete(system, user, max_tokens=256)

    raw = raw.strip()
    m = _re.search(r"\[.*?\]", raw, _re.S)
    try:
        tags = _json.loads(m.group()) if m else []
        tags = [str(t).lower().strip() for t in tags if t]
    except Exception:
        tags = []

    # Hard-exclude tags already assigned
    current_set = set(current_tags)
    tags = [t for t in tags if t not in current_set]

    return {"category": category, "suggested": tags}


@app.get("/api/config/models")
async def config_models():
    """Return available query models for the current provider."""
    cfg = get_config()
    provider = cfg["llm"]["provider"]
    pc = cfg["llm"].get(provider, {})
    default_model = pc.get("query_model", "")

    if provider == "ollama":
        import httpx
        base_url = pc.get("base_url", "http://host.docker.internal:11434").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base_url}/api/tags")
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            models = [default_model] if default_model else []
    else:
        # For Anthropic/OpenAI return only the configured model — dynamic listing not supported
        models = [default_model] if default_model else []

    return {"provider": provider, "default": default_model, "models": models}



@app.get("/api/config/llm", response_model=LLMConfigResponse)
async def config_llm():
    config = get_config()
    provider = config["llm"]["provider"]
    pc = config["llm"].get(provider, {})
    return LLMConfigResponse(
        provider=provider,
        classification_model=pc.get("classification_model", ""),
        query_model=pc.get("query_model", ""),
        embedding_model=pc.get("embedding_model", ""),
    )


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

@app.post("/api/ingest/url", response_model=IngestResponse)
async def ingest_url(req: IngestURLRequest):
    from pipeline import ingest_url_pipeline
    global _access_log
    if _access_log is None:
        _access_log = _setup_logger()
    t0 = time.monotonic()
    try:
        result = await ingest_url_pipeline(
            url=req.url,
            category=req.category,
            tags=req.tags,
            llm=get_llm(),
            index=get_index(),
            data_dir=DATA_DIR,
            vector_index=_vector_index,
        )
        elapsed = int((time.monotonic() - t0) * 1000)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        status = "duplicate" if result.get("duplicate") else "ok"
        _access_log.info('%s INGEST %s status=%s title=%r category=%s %dms',
            ts, req.url, status, result.get("title",""), result.get("category",""), elapsed)
        return IngestResponse(**result)
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _access_log.error('%s INGEST %s status=error error=%r %dms', ts, req.url, str(e), elapsed)
        raise HTTPException(status_code=500, detail=_clean_llm_error(e))


@app.post("/api/ingest/snapshot", response_model=IngestResponse)
async def ingest_snapshot(req: IngestSnapshotRequest):
    from pipeline import ingest_snapshot_pipeline
    global _access_log
    if _access_log is None:
        _access_log = _setup_logger()
    t0 = time.monotonic()
    try:
        result = await ingest_snapshot_pipeline(
            url=req.url,
            title=req.title,
            html=req.html,
            category=req.category,
            tags=req.tags,
            llm=get_llm(),
            index=get_index(),
            data_dir=DATA_DIR,
            vector_index=_vector_index,
        )
        elapsed = int((time.monotonic() - t0) * 1000)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        status = "duplicate" if result.get("duplicate") else "ok"
        _access_log.info('%s SNAPSHOT %s status=%s title=%r category=%s %dms',
            ts, req.url, status, result.get("title",""), result.get("category",""), elapsed)
        return IngestResponse(**result)
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _access_log.error('%s SNAPSHOT %s status=error error=%r %dms', ts, req.url, str(e), elapsed)
        raise HTTPException(status_code=500, detail=_clean_llm_error(e))


@app.post("/api/ingest/pdf", response_model=IngestResponse)
async def ingest_pdf(
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
):
    import tempfile, shutil
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        from pipeline import ingest_pdf_pipeline
        result = await ingest_pdf_pipeline(
            file_path=tmp_path,
            original_filename=file.filename,
            category=category,
            tags=tag_list,
            llm=get_llm(),
            index=get_index(),
            data_dir=DATA_DIR,
            vector_index=_vector_index,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=_clean_llm_error(e))
    finally:
        os.unlink(tmp_path)
    return IngestResponse(**result)


@app.post("/api/ingest/image", response_model=IngestResponse)
async def ingest_image(
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
):
    import tempfile, shutil
    suffix = Path(file.filename).suffix.lower() if file.filename else ".png"
    if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        raise HTTPException(status_code=400, detail="Unsupported image format. Use JPG, PNG, GIF, or WebP.")
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        from pipeline import ingest_image_pipeline
        result = await ingest_image_pipeline(
            file_path=tmp_path,
            original_filename=file.filename,
            category=category,
            tags=tag_list,
            llm=get_llm(),
            index=get_index(),
            data_dir=DATA_DIR,
            vector_index=_vector_index,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=_clean_llm_error(e))
    finally:
        os.unlink(tmp_path)
    return IngestResponse(**result)


@app.post("/api/ingest/text", response_model=IngestResponse)
async def ingest_text(req: IngestTextRequest):
    from pipeline import ingest_text_pipeline
    try:
        result = await ingest_text_pipeline(
            title=req.title,
            body=req.body,
            category=req.category,
            tags=req.tags,
            llm=get_llm(),
            index=get_index(),
            data_dir=DATA_DIR,
            vector_index=_vector_index,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=_clean_llm_error(e))
    return IngestResponse(**result)


@app.post("/api/ingest/bulk-urls", response_model=BulkIngestResponse)
async def ingest_bulk_urls(req: BulkURLRequest):
    from pipeline import ingest_url_pipeline
    imported, skipped, failed, ids = 0, 0, 0, []
    for item in req.urls:
        try:
            result = await ingest_url_pipeline(
                url=item.url,
                category=item.category,
                tags=item.tags,
                llm=get_llm(),
                index=get_index(),
                data_dir=DATA_DIR,
                vector_index=_vector_index,
            )
            if result.get("duplicate"):
                skipped += 1
            else:
                imported += 1
                ids.append(result["item_id"])
        except Exception as e:
            failed += 1
            from storage.failures import record_failure
            record_failure(DATA_DIR, "url", item.url, e, item.category)
        await asyncio.sleep(get_config()["ingestion"]["bulk_rate_limit"])
    return BulkIngestResponse(imported=imported, skipped=skipped, failed=failed, item_ids=ids)


# ---------------------------------------------------------------------------
# Library CRUD
# ---------------------------------------------------------------------------

_LIBRARY_EXCLUDE = {"wiki_page", "starred_repo"}


@app.get("/api/library", response_model=ItemListResponse)
async def list_library(
    category: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    index = get_index()
    results = index.search(category=category, tag=tag, text_query=q)
    results = [r for r in results if r.get("content_type", "text") not in _LIBRARY_EXCLUDE]
    total = len(results)
    page = results[offset: offset + limit]
    return ItemListResponse(items=[ItemMetadata(**m) for m in page], total=total, limit=limit, offset=offset)


@app.get("/api/items", response_model=ItemListResponse)
async def list_items(
    category: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    exclude_content_types: Optional[str] = Query(None),
):
    index = get_index()
    results = index.search(category=category, tag=tag, text_query=q)
    if exclude_content_types:
        excluded = {t.strip() for t in exclude_content_types.split(",")}
        results = [r for r in results if r.get("content_type", "text") not in excluded]
    total = len(results)
    page = results[offset: offset + limit]
    return ItemListResponse(items=[ItemMetadata(**m) for m in page], total=total, limit=limit, offset=offset)


@app.get("/api/items/{item_id}", response_model=ItemDetail)
async def get_item(item_id: str):
    from storage.filesystem import load_item
    item = load_item(item_id, get_index(), DATA_DIR)
    if not item:
        raise HTTPException(404, "Item not found")
    return ItemDetail(**item)


@app.get("/api/items/{item_id}/content", response_class=PlainTextResponse)
async def get_item_content(item_id: str):
    from storage.filesystem import load_item
    item = load_item(item_id, get_index(), DATA_DIR)
    if not item:
        raise HTTPException(404, "Item not found")
    return item.get("content", "")


@app.get("/api/items/{item_id}/snapshot", response_class=HTMLResponse)
async def get_item_snapshot(item_id: str):
    entry = get_index().get(item_id)
    if not entry:
        raise HTTPException(404, "Item not found")
    snapshot_file = DATA_DIR / entry["path"] / "snapshot.html"
    if not snapshot_file.exists():
        raise HTTPException(404, "No snapshot available for this item")
    return snapshot_file.read_text(encoding="utf-8")


@app.get("/api/items/{item_id}/assets/{filename}")
async def get_item_asset(item_id: str, filename: str):
    entry = get_index().get(item_id)
    if not entry:
        raise HTTPException(404, "Item not found")
    # Prevent path traversal
    asset_file = (DATA_DIR / entry["path"] / "assets" / filename).resolve()
    allowed_root = (DATA_DIR / entry["path"] / "assets").resolve()
    if not str(asset_file).startswith(str(allowed_root)):
        raise HTTPException(400, "Invalid asset path")
    if not asset_file.exists():
        raise HTTPException(404, "Asset not found")
    return FileResponse(asset_file)


@app.get("/api/items/{item_id}/original")
async def get_item_original(item_id: str):
    entry = get_index().get(item_id)
    if not entry:
        raise HTTPException(404, "Item not found")
    item_dir = DATA_DIR / entry["path"]
    for ext, mime in [
        (".pdf",  "application/pdf"),
        (".png",  "image/png"),
        (".jpg",  "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".gif",  "image/gif"),
        (".webp", "image/webp"),
        (".bin",  "application/octet-stream"),
    ]:
        f = item_dir / f"original{ext}"
        if f.exists():
            return FileResponse(str(f), media_type=mime)
    raise HTTPException(404, "No original file for this item")


@app.patch("/api/items/{item_id}", response_model=ItemMetadata)
async def update_item(item_id: str, req: UpdateItemRequest):
    from storage.filesystem import update_item as fs_update
    updates = req.model_dump(exclude_none=True)
    # Mark as verified and trigger re-embed whenever user manually saves category or tags
    if "category" in updates or "tags" in updates:
        updates["verified"] = True
    updated = await fs_update(item_id, updates, get_index(), DATA_DIR)
    if not updated:
        raise HTTPException(404, "Item not found")
    if updates.get("verified"):
        from rag.embedder import embed_item
        await embed_item(item_id, get_llm(), get_index(), DATA_DIR, vector_index=_vector_index)
    return ItemMetadata(**updated)


_FOLLOWUP_TAG = "followup"


@app.get("/api/followup", response_model=ItemListResponse)
async def list_followup(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return all library items and ingested tool/wiki items tagged 'followup'."""
    index = get_index()
    results = [
        {**m, "id": item_id}
        for item_id, m in index.all_items().items()
        if _FOLLOWUP_TAG in m.get("tags", [])
    ]
    results.sort(key=lambda m: m.get("updated", ""), reverse=True)
    total = len(results)
    page = results[offset: offset + limit]
    return ItemListResponse(items=[ItemMetadata(**m) for m in page], total=total, limit=limit, offset=offset)


@app.post("/api/items/{item_id}/followup", response_model=ItemMetadata)
async def add_followup(item_id: str):
    from storage.filesystem import update_item as fs_update
    entry = get_index().get(item_id)
    if not entry:
        raise HTTPException(404, "Item not found")
    tags = list(entry.get("tags") or [])
    if _FOLLOWUP_TAG not in tags:
        tags.append(_FOLLOWUP_TAG)
    updated = await fs_update(item_id, {"tags": tags}, get_index(), DATA_DIR)
    if not updated:
        raise HTTPException(404, "Item not found")
    return ItemMetadata(**updated)


@app.delete("/api/items/{item_id}/followup", response_model=ItemMetadata)
async def remove_followup(item_id: str):
    from storage.filesystem import update_item as fs_update
    entry = get_index().get(item_id)
    if not entry:
        raise HTTPException(404, "Item not found")
    tags = [t for t in (entry.get("tags") or []) if t != _FOLLOWUP_TAG]
    updated = await fs_update(item_id, {"tags": tags}, get_index(), DATA_DIR)
    if not updated:
        raise HTTPException(404, "Item not found")
    return ItemMetadata(**updated)


@app.delete("/api/items/{item_id}")
async def delete_item(item_id: str):
    from storage.filesystem import delete_item as fs_delete
    ok = await fs_delete(item_id, get_index(), DATA_DIR)
    if not ok:
        raise HTTPException(404, "Item not found")
    return {"deleted": item_id}


@app.post("/api/items/{item_id}/reclassify", response_model=ItemMetadata)
async def reclassify_item(item_id: str):
    from storage.filesystem import load_item, update_item as fs_update
    from classifier.classify import classify_content
    item = load_item(item_id, get_index(), DATA_DIR)
    if not item:
        raise HTTPException(404, "Item not found")

    result = await classify_content(
        item["title"], item.get("content", ""), get_llm(),
        data_dir=DATA_DIR, index=get_index(), exclude_item_id=item_id,
    )
    updates = {
        "category": result["category"],
        "tags": result["tags"],
        "summary": result["summary"],
        "classified_by": result["classified_by"],
    }
    updated = await fs_update(item_id, updates, get_index(), DATA_DIR)
    return ItemMetadata(**updated)


@app.get("/api/categories", response_model=list[CategoryInfo])
async def list_categories():
    index = get_index()
    counts: dict[str, int] = {}
    for m in index.all_items().values():
        if m.get("content_type", "text") in _LIBRARY_EXCLUDE:
            continue
        cat = m.get("category", "misc")
        counts[cat] = counts.get(cat, 0) + 1
    return [CategoryInfo(name=k, count=v) for k, v in sorted(counts.items())]


@app.get("/api/tags", response_model=list[TagInfo])
async def list_tags():
    index = get_index()
    counts: dict[str, int] = {}
    # Dynamic tags from ingested items (library only)
    for m in index.all_items().values():
        if m.get("content_type", "text") in _LIBRARY_EXCLUDE:
            continue
        for tag in m.get("tags", []):
            counts[tag] = counts.get(tag, 0) + 1
    # Curated tags from tags.yaml — include with count 0 if not yet seen
    for tag in get_tags():
        if tag not in counts:
            counts[tag] = 0
    return [TagInfo(name=k, count=v) for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


# ---------------------------------------------------------------------------
# RAG / Query
# ---------------------------------------------------------------------------

@app.post("/api/query", response_model=QueryResponse)
async def query(req: QueryRequest):
    from rag.query import rag_query
    vi = get_vector_index()
    if not vi:
        raise HTTPException(503, "Vector index not loaded — run /api/reembed first")
    llm = get_llm()
    if req.model and req.model != getattr(llm, "_query_model", None):
        llm = _llm_with_model(llm, req.model)
    result = await rag_query(
        question=req.question,
        llm=llm,
        vector_index=vi,
        index=get_index(),
        category=req.category,
        tags=req.tags,
        top_k=req.top_k,
    )
    return QueryResponse(**result)


@app.post("/api/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    import asyncio as _asyncio
    from rag.search import semantic_search
    vi = get_vector_index()
    if not vi:
        raise HTTPException(503, "Vector index not loaded — run /api/reembed first")
    llm = get_llm()
    idx = get_index()

    # Embed once, then run three parallel searches — one per content group —
    # so each gets its own top_k budget and low-scoring wiki/tool hits aren't
    # pushed out by high-scoring library hits.
    embeddings = await llm.embed([req.query])
    query_embedding = embeddings[0]

    library_types = [ct for ct in (
        set(m.get("content_type") for m in idx.all_items().values())
    ) if ct not in ("wiki_page", "starred_repo")]

    lib_results, wiki_results, tool_results = await _asyncio.gather(
        semantic_search(req.query, llm, vi, idx, DATA_DIR,
                        category=req.category, tags=req.tags,
                        top_k=req.top_k, content_types=library_types,
                        query_embedding=query_embedding),
        semantic_search(req.query, llm, vi, idx, DATA_DIR,
                        top_k=10, content_types=["wiki_page"],
                        query_embedding=query_embedding),
        semantic_search(req.query, llm, vi, idx, DATA_DIR,
                        top_k=10, content_types=["starred_repo"],
                        query_embedding=query_embedding),
    )

    results = lib_results + wiki_results + tool_results
    return SearchResponse(results=results)


@app.post("/api/library/search", response_model=SearchResponse)
async def search_library(req: SearchRequest):
    from rag.search import semantic_search
    vi = get_vector_index()
    if not vi:
        raise HTTPException(503, "Vector index not loaded — run /api/reembed first")
    llm = get_llm()
    idx = get_index()
    embeddings = await llm.embed([req.query])
    query_embedding = embeddings[0]
    library_types = [ct for ct in (
        set(m.get("content_type") for m in idx.all_items().values())
    ) if ct not in _LIBRARY_EXCLUDE]
    results = await semantic_search(req.query, llm, vi, idx, DATA_DIR,
                                    category=req.category, tags=req.tags,
                                    top_k=req.top_k, content_types=library_types,
                                    query_embedding=query_embedding)
    return SearchResponse(results=results)


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

@app.post("/api/skills/generate")
async def generate_skill(req: GenerateSkillRequest):
    from rag.skills import generate_skill as gen
    vi = get_vector_index()
    if not vi:
        raise HTTPException(503, "Vector index not loaded — run /api/reembed first")
    content = await gen(
        topic=req.topic,
        llm=get_llm(),
        vector_index=vi,
        index=get_index(),
        data_dir=DATA_DIR,
        categories=req.categories,
        description=req.description,
    )
    return {"topic": req.topic, "content": content}


@app.get("/api/skills", response_model=list[SkillInfo])
async def list_skills():
    skills_dir = DATA_DIR / "skills"
    if not skills_dir.exists():
        return []
    result = []
    for skill_file in sorted(skills_dir.rglob("SKILL.md")):
        topic = skill_file.parent.name
        stat = skill_file.stat()
        import datetime
        result.append(SkillInfo(
            topic=topic,
            path=str(skill_file.relative_to(DATA_DIR)),
            generated=datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        ))
    return result


@app.get("/api/skills/{topic}", response_class=PlainTextResponse)
async def get_skill(topic: str):
    skill_file = DATA_DIR / "skills" / topic / "SKILL.md"
    if not skill_file.exists():
        raise HTTPException(404, f"Skill '{topic}' not found")
    return skill_file.read_text()


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

@app.post("/api/planner/generate", response_model=PlanResponse)
async def generate_plan_endpoint(req: GeneratePlanRequest):
    from rag.planner import generate_plan
    vi = get_vector_index()
    if not vi:
        raise HTTPException(503, "Vector index not loaded — run /api/reembed first")
    result = await generate_plan(
        description=req.description,
        llm=get_llm(),
        vector_index=vi,
        index=get_index(),
        data_dir=DATA_DIR,
    )
    return PlanResponse(**result)


@app.get("/api/planner", response_model=list[PlanInfo])
async def list_plans():
    plans_dir = DATA_DIR / "plans"
    result = []
    if not plans_dir.exists():
        return result
    for meta_file in sorted(plans_dir.glob("*/.meta.json"), reverse=True):
        try:
            import json as _json
            meta = _json.loads(meta_file.read_text(encoding="utf-8"))
            result.append(PlanInfo(
                slug=meta_file.parent.name,
                title=meta.get("title", meta_file.parent.name),
                generated=meta.get("generated", ""),
            ))
        except Exception:
            pass
    return result


@app.get("/api/planner/{plan_slug}", response_model=PlanResponse)
async def get_plan(plan_slug: str):
    import json as _json
    plan_dir = DATA_DIR / "plans" / plan_slug
    plan_file = plan_dir / "PLAN.md"
    meta_file = plan_dir / ".meta.json"
    if not plan_file.exists():
        raise HTTPException(404, "Plan not found")
    meta = {}
    if meta_file.exists():
        try:
            meta = _json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return PlanResponse(
        slug=plan_slug,
        title=meta.get("title", plan_slug),
        content=plan_file.read_text(encoding="utf-8"),
        generated=meta.get("generated", ""),
    )


@app.delete("/api/planner/{plan_slug}")
async def delete_plan(plan_slug: str):
    import shutil
    plan_dir = DATA_DIR / "plans" / plan_slug
    if not plan_dir.exists():
        raise HTTPException(404, "Plan not found")
    shutil.rmtree(plan_dir)
    return {"deleted": plan_slug}


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

@app.post("/api/digest/generate", response_model=DigestPageDetail)
async def generate_digest_page_endpoint(req: GenerateDigestPageRequest):
    from rag.digest import generate_digest_page
    from storage.filesystem import load_item
    item = load_item(req.item_id, get_index(), DATA_DIR)
    if not item:
        raise HTTPException(404, "Item not found")
    content = item.get("content", "")
    if not content.strip():
        raise HTTPException(422, "Item has no text content to generate a digest page from")
    try:
        result = await generate_digest_page(
            item_id=req.item_id,
            item_title=item.get("title", "Untitled"),
            item_content=content,
            item_category=item.get("category", "misc"),
            item_url=item.get("url"),
            initial_tags=list(dict.fromkeys((req.tags or []) + (item.get("tags") or []))),
            llm=get_llm(),
            data_dir=DATA_DIR,
        )
    except Exception as exc:
        raise HTTPException(500, f"Digest page generation failed: {exc}") from exc
    return DigestPageDetail(**result)


@app.post("/api/digest/save-markdown", response_model=DigestPageDetail)
async def save_digest_page_markdown_endpoint(req: GenerateDigestPageRequest):
    from rag.digest import save_digest_page_from_item
    from storage.filesystem import load_item
    item = load_item(req.item_id, get_index(), DATA_DIR)
    if not item:
        raise HTTPException(404, "Item not found")
    content = item.get("content", "")
    if not content.strip():
        raise HTTPException(422, "Item has no text content")
    result = save_digest_page_from_item(
        item_id=req.item_id,
        item_title=item.get("title", "Untitled"),
        item_content=content,
        item_category=item.get("category", "misc"),
        item_url=item.get("url"),
        data_dir=DATA_DIR,
    )
    return DigestPageDetail(**result)


@app.get("/api/digest/pages", response_model=list[DigestPageInfo])
async def list_digest_pages_endpoint():
    from rag.digest import list_digest_pages
    pages = list_digest_pages(DATA_DIR)
    return [DigestPageInfo(**p) for p in pages]


@app.get("/api/digest/pages/{page_id:path}", response_model=DigestPageDetail)
async def get_digest_page_endpoint(page_id: str):
    from rag.digest import get_digest_page
    page = get_digest_page(DATA_DIR, page_id)
    if not page:
        raise HTTPException(404, "Digest page not found")
    return DigestPageDetail(**page)


@app.patch("/api/digest/pages/{page_id:path}", response_model=DigestPageDetail)
async def update_digest_page_endpoint(page_id: str, req: UpdateDigestPageRequest):
    from rag.digest import update_digest_page
    page = update_digest_page(DATA_DIR, page_id, title=req.title, content=req.content, tags=req.tags, category=req.category)
    if not page:
        raise HTTPException(404, "Digest page not found")
    return DigestPageDetail(**page)


@app.delete("/api/digest/pages/{page_id:path}")
async def delete_digest_page_endpoint(page_id: str):
    from rag.digest import delete_digest_page
    deleted = delete_digest_page(DATA_DIR, page_id)
    if not deleted:
        raise HTTPException(404, "Digest page not found")
    return {"deleted": page_id}


@app.post("/api/digest/fetch-repo")
async def fetch_repo_for_digest(req: FetchRepoRequest):
    """Clone/pull a git repo and return its TOC for the import UI."""
    import hashlib
    from git_fetcher import fetch_repo
    repo_id = "import-" + hashlib.sha1(req.url.encode()).hexdigest()[:8]
    try:
        data = await fetch_repo(repo_id, req.url, DATA_DIR)
    except Exception as exc:
        raise HTTPException(400, f"Failed to fetch repo: {exc}") from exc
    return data


@app.post("/api/digest/import", response_model=ImportDigestPagesResponse)
async def import_digest_pages(req: ImportDigestPagesRequest):
    """Import selected markdown pages from a previously fetched repo into the digest."""
    import hashlib
    from rag.digest import import_digest_page
    repo_id = "import-" + hashlib.sha1(req.url.encode()).hexdigest()[:8]
    repo_dir = DATA_DIR / "wikis" / repo_id

    if not repo_dir.exists():
        raise HTTPException(400, "Repo not fetched — call fetch-repo first")

    imported, skipped, failed = 0, 0, 0
    page_ids: list[str] = []

    for item in req.pages:
        md_path = repo_dir / item.rel_path.replace("/", os.sep)
        # Security: ensure path stays within repo_dir
        try:
            md_path.resolve().relative_to(repo_dir.resolve())
        except ValueError:
            failed += 1
            continue
        if not md_path.exists() or not md_path.suffix.lower() == ".md":
            skipped += 1
            continue
        content = md_path.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            skipped += 1
            continue
        try:
            result = await import_digest_page(
                title=item.title,
                content=content,
                source_url=req.url,
                llm=get_llm(),
                data_dir=DATA_DIR,
            )
            page_ids.append(result["page_id"])
            imported += 1
        except Exception:
            failed += 1

    return ImportDigestPagesResponse(
        imported=imported,
        skipped=skipped,
        failed=failed,
        page_ids=page_ids,
    )


@app.post("/api/digest/upload", response_model=UploadDigestPageResponse)
async def upload_digest_page(file: UploadFile = File(...)):
    """Upload a single markdown file directly into the digest."""
    from rag.digest import import_digest_page
    if not file.filename or not file.filename.lower().endswith(".md"):
        raise HTTPException(400, "Only .md files are supported")
    content = (await file.read()).decode("utf-8", errors="replace")
    if not content.strip():
        raise HTTPException(422, "File is empty")
    title = Path(file.filename).stem.replace("-", " ").replace("_", " ")
    try:
        result = await import_digest_page(
            title=title,
            content=content,
            source_url=None,
            llm=get_llm(),
            data_dir=DATA_DIR,
        )
    except Exception as exc:
        raise HTTPException(500, f"Upload failed: {exc}") from exc
    return UploadDigestPageResponse(
        page_id=result["page_id"],
        title=result["title"],
        category=result["category"],
        tags=result["tags"],
    )


# ---------------------------------------------------------------------------
# Feeds / RSS
# ---------------------------------------------------------------------------

@app.get("/api/feeds", response_model=list[FeedInfo])
async def list_feeds():
    from rssfeeds.store import load_feeds
    result = []
    for f in load_feeds(DATA_DIR):
        latest = set(f.get("latest_urls") or [])
        seen   = set(f.get("seen_urls")   or [])
        unread = len(latest - seen)
        result.append(FeedInfo(**{k: v for k, v in f.items()
                                  if k in FeedInfo.model_fields},
                               unread_count=unread))
    return result


@app.post("/api/feeds", response_model=FeedInfo)
async def add_feed(req: AddFeedRequest):
    from rssfeeds.store import add_feed as _add_feed, set_latest_urls
    from rssfeeds.fetcher import fetch_feed, save_feed_cache
    import datetime

    # Always fetch feed to get real title and prime the cache
    data: dict | None = None
    try:
        data = await fetch_feed(req.url)
        title = req.title or data["title"] or req.url
    except Exception:
        title = req.title or req.url

    feed = _add_feed(DATA_DIR, url=req.url, title=title)

    if data is not None:
        save_feed_cache(DATA_DIR, feed["id"], data)
        urls = [e["url"] for e in data["entries"][:50] if e.get("url")]
        set_latest_urls(DATA_DIR, feed["id"], urls)
        from rssfeeds.store import update_feed as _update_feed
        now = datetime.datetime.utcnow().isoformat() + "Z"
        _update_feed(DATA_DIR, feed["id"], {"last_fetched": now, "last_error": None})
        feed = _update_feed(DATA_DIR, feed["id"], {}) or feed  # reload

    return FeedInfo(**feed)


@app.post("/api/feeds/refresh")
async def refresh_all_feeds():
    """Immediately fetch all enabled feeds and update cache / latest_urls / last_fetched."""
    import datetime
    from rssfeeds.store import load_feeds, update_feed as _update_feed, set_latest_urls
    from rssfeeds.fetcher import fetch_feed, save_feed_cache

    feeds = load_feeds(DATA_DIR)
    refreshed = 0
    errors = 0
    for feed in feeds:
        if not feed.get("enabled", True):
            continue
        try:
            data = await fetch_feed(feed["url"])
            save_feed_cache(DATA_DIR, feed["id"], data)
            urls = [e["url"] for e in data["entries"][:50] if e.get("url")]
            set_latest_urls(DATA_DIR, feed["id"], urls)
            now = datetime.datetime.utcnow().isoformat() + "Z"
            updates: dict = {"last_fetched": now, "last_error": None}
            if data.get("title") and data["title"] != feed["url"]:
                updates["title"] = data["title"]
            _update_feed(DATA_DIR, feed["id"], updates)
            refreshed += 1
        except Exception as exc:
            _update_feed(DATA_DIR, feed["id"], {"last_error": str(exc)})
            errors += 1

    return {"refreshed": refreshed, "errors": errors}


@app.get("/api/feeds/config")
async def get_feeds_config():
    return {"refresh_interval_minutes": _get_refresh_interval("feeds", 60)}


@app.patch("/api/feeds/config")
async def update_feeds_config(body: dict):
    return _set_refresh_interval("feeds", 60, body)


@app.delete("/api/feeds/{feed_id}")
async def delete_feed(feed_id: str):
    from rssfeeds.store import remove_feed
    ok = remove_feed(DATA_DIR, feed_id)
    if not ok:
        raise HTTPException(404, "Feed not found")
    return {"deleted": feed_id}


@app.patch("/api/feeds/{feed_id}", response_model=FeedInfo)
async def update_feed(feed_id: str, req: UpdateFeedRequest):
    from rssfeeds.store import update_feed as _update_feed
    updates = req.model_dump(exclude_none=True)
    updated = _update_feed(DATA_DIR, feed_id, updates)
    if not updated:
        raise HTTPException(404, "Feed not found")
    return FeedInfo(**updated)


@app.get("/api/feeds/{feed_id}/preview", response_model=FeedPreviewResponse)
async def preview_feed(feed_id: str):
    from rssfeeds.store import get_feed, set_latest_urls, update_feed as _update_feed
    from rssfeeds.fetcher import fetch_feed, load_feed_cache, save_feed_cache
    from models import FeedEntry
    import datetime

    feed = get_feed(DATA_DIR, feed_id)
    if not feed:
        raise HTTPException(404, "Feed not found")

    # Serve from cache if available; otherwise fetch live and save cache
    data = load_feed_cache(DATA_DIR, feed_id)
    if data is None:
        try:
            data = await fetch_feed(feed["url"])
            save_feed_cache(DATA_DIR, feed_id, data)
            urls = [e["url"] for e in data["entries"][:50] if e.get("url")]
            set_latest_urls(DATA_DIR, feed_id, urls)
            now = datetime.datetime.utcnow().isoformat() + "Z"
            updates: dict = {"last_fetched": now, "last_error": None}
            if data.get("title") and data["title"] != feed["url"]:
                updates["title"] = data["title"]
            _update_feed(DATA_DIR, feed_id, updates)
        except Exception as e:
            raise HTTPException(502, f"Failed to fetch feed: {e}")

    seen_set = set(feed.get("seen_urls") or [])
    raw_entries = data["entries"][:50]

    entries = []
    for e in raw_entries:
        url = e.get("url", "")
        entries.append(FeedEntry(
            title=e.get("title", ""),
            url=url,
            summary=e.get("summary", ""),
            content=e.get("content", ""),
            published=e.get("published", ""),
            seen=url in seen_set,
            comments_url=e.get("comments_url"),
        ))

    unread = sum(1 for en in entries if not en.seen)
    return FeedPreviewResponse(feed_title=data["title"], entries=entries, unread_count=unread)


@app.post("/api/feeds/{feed_id}/mark-read")
async def mark_feed_read(feed_id: str, body: dict = {}):
    """Mark all (or specific) entries as read. Body: {"urls": [...]} or {} for all current."""
    from rssfeeds.store import get_feed, mark_all_read
    from rssfeeds.fetcher import load_feed_cache

    feed = get_feed(DATA_DIR, feed_id)
    if not feed:
        raise HTTPException(404, "Feed not found")

    urls: list[str] | None = body.get("urls") if body else None
    if urls is None:
        # Use cache if available, fall back to latest_urls
        cached = load_feed_cache(DATA_DIR, feed_id)
        if cached:
            urls = [e["url"] for e in cached["entries"][:50] if e.get("url")]
        else:
            urls = list(feed.get("latest_urls") or [])

    mark_all_read(DATA_DIR, feed_id, urls)
    return {"marked": len(urls)}


@app.post("/api/feeds/{feed_id}/ingest")
async def ingest_feed_entries(feed_id: str, body: dict = {}):
    """Ingest feed entries into the library. Pass {"entry_urls": [...]} or omit to ingest all."""
    from rssfeeds.store import get_feed, update_feed as _update_feed
    from rssfeeds.fetcher import fetch_feed
    from pipeline import ingest_url_pipeline
    import datetime

    feed = get_feed(DATA_DIR, feed_id)
    if not feed:
        raise HTTPException(404, "Feed not found")

    entry_urls: list[str] | None = body.get("entry_urls") if body else None

    if entry_urls is None:
        # Use cache if available, otherwise fetch live
        from rssfeeds.fetcher import load_feed_cache, save_feed_cache
        from rssfeeds.store import set_latest_urls
        cached = load_feed_cache(DATA_DIR, feed_id)
        if cached:
            data = cached
        else:
            try:
                data = await fetch_feed(feed["url"])
                save_feed_cache(DATA_DIR, feed_id, data)
                urls = [e["url"] for e in data["entries"][:50] if e.get("url")]
                set_latest_urls(DATA_DIR, feed_id, urls)
            except Exception as e:
                raise HTTPException(502, f"Failed to fetch feed: {e}")
        entry_urls = [e["url"] for e in data["entries"] if e.get("url")]

    results = {"imported": 0, "skipped": 0, "failed": 0, "item_ids": []}
    llm = get_llm()
    index = get_index()

    async def _ingest_one(url: str):
        try:
            r = await ingest_url_pipeline(
                url=url,
                category=None,
                tags=None,
                llm=llm,
                index=index,
                data_dir=DATA_DIR,
                vector_index=_vector_index,
            )
            if r.get("duplicate"):
                results["skipped"] += 1
            else:
                results["imported"] += 1
                results["item_ids"].append(r["item_id"])
        except Exception as e:
            results["failed"] += 1
            results.setdefault("errors", []).append(_clean_llm_error(e))

    await asyncio.gather(*[_ingest_one(u) for u in entry_urls])

    if results["failed"] and not results["imported"] and not results["skipped"]:
        raise HTTPException(500, results["errors"][0] if results.get("errors") else "Ingest failed")

    now = datetime.datetime.utcnow().isoformat() + "Z"
    _update_feed(DATA_DIR, feed_id, {"last_fetched": now})

    return results


@app.get("/api/feeds/opml")
async def export_opml():
    from rssfeeds.store import load_feeds
    from rssfeeds.opml import generate_opml
    from fastapi.responses import Response

    feeds = load_feeds(DATA_DIR)
    xml_bytes = generate_opml(feeds)
    return Response(
        content=xml_bytes,
        media_type="application/xml",
        headers={"Content-Disposition": "attachment; filename=brainz-feeds.opml"},
    )


@app.post("/api/feeds/opml")
async def import_opml(file: UploadFile = File(...)):
    from rssfeeds.opml import parse_opml
    from rssfeeds.store import load_feeds, save_feeds
    import uuid as _uuid

    xml_bytes = await file.read()
    try:
        parsed = parse_opml(xml_bytes)
    except Exception as e:
        raise HTTPException(400, f"Invalid OPML: {e}")

    feeds = load_feeds(DATA_DIR)
    existing_urls = {f["url"] for f in feeds}
    added = []
    skipped = 0

    for entry in parsed:
        url = entry.get("url", "")
        if not url or url in existing_urls:
            skipped += 1
            continue
        # Use title from OPML — real title fetched lazily on first preview
        title = entry.get("title") or url
        feed = {
            "id": _uuid.uuid4().hex[:8],
            "url": url,
            "title": title,
            "enabled": True,
            "last_fetched": None,
            "last_error": None,
            "seen_urls": [],
            "latest_urls": [],
        }
        feeds.append(feed)
        added.append(feed["id"])
        existing_urls.add(url)

    # Single write for all new feeds
    if added:
        save_feeds(DATA_DIR, feeds)

    return {"added": len(added), "skipped": skipped, "feed_ids": added}


# ---------------------------------------------------------------------------
# Tools (GitHub Stars)
# ---------------------------------------------------------------------------

def _get_github_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN", "")
    return token.strip() or None


async def _auto_ingest_tool(tool: dict) -> None:
    """Ingest all latest repos for a tool account that haven't been ingested yet."""
    from pipeline import ingest_text_pipeline, ingest_url_pipeline
    from tools.fetcher import load_repos_cache

    tool_id = tool["id"]
    repos = load_repos_cache(DATA_DIR, tool_id) or []
    if not repos:
        return

    idx = get_index()
    all_indexed_urls = {m.get("url") for m in idx.all_items().values() if m.get("url")}
    all_indexed_titles = {m.get("title") for m in idx.all_items().values() if m.get("title")}
    new_repos = [r for r in repos if r["html_url"] not in all_indexed_urls and r["full_name"] not in all_indexed_titles]
    if not new_repos:
        return

    llm = get_llm()
    index = get_index()

    sem = asyncio.Semaphore(4)  # limit concurrent LLM calls to avoid overwhelming Ollama

    async def _ingest_one(repo: dict) -> None:
        async with sem:
            try:
                title = repo["full_name"]
                if repo.get("readme_path"):
                    readme = Path(repo["readme_path"]).read_text(encoding="utf-8", errors="ignore")
                    body = f"# {title}\n\n{repo.get('description','')}\n\n{readme}"
                else:
                    topics = ", ".join(repo.get("topics") or [])
                    body = (
                        f"# {title}\n\n"
                        f"{repo.get('description','')}\n\n"
                        f"Language: {repo.get('language','')}\n"
                        f"Topics: {topics}\n"
                        f"Stars: {repo.get('stargazers_count', 0)}\n"
                        f"URL: {repo['html_url']}"
                    )
                await ingest_text_pipeline(
                    title=title, body=body,
                    category="tools", tags=repo.get("topics") or ["tool"],
                    llm=llm, index=index, data_dir=DATA_DIR,
                    vector_index=_vector_index,
                    url=repo["html_url"],
                    content_type="starred_repo",
                )
            except Exception as e:
                log.warning("Tool ingest failed for %s: %s", repo.get("full_name"), e)

    await asyncio.gather(*[_ingest_one(r) for r in new_repos])


async def _refresh_one_tool(tool: dict) -> None:
    """Fetch starred repos for a single tool account and update storage."""
    import datetime
    from tools.store import update_tool as _update_tool, set_latest_ids, get_tool as _get_tool
    from tools.fetcher import fetch_starred, save_repos_cache

    tool_id = tool["id"]
    _tools_refreshing[tool_id] = tool["username"]
    try:
        repos = await fetch_starred(tool["username"], _get_github_token(), DATA_DIR)
        save_repos_cache(DATA_DIR, tool_id, repos)
        ids = [r["node_id"] for r in repos]
        set_latest_ids(DATA_DIR, tool_id, ids)
        now = datetime.datetime.utcnow().isoformat() + "Z"
        _update_tool(DATA_DIR, tool_id, {"last_fetched": now, "last_error": None})
        updated = _get_tool(DATA_DIR, tool_id)
        if updated and updated.get("auto_ingest"):
            await _auto_ingest_tool(updated)
    except Exception as exc:
        _update_tool(DATA_DIR, tool_id, {"last_error": str(exc)})
        raise
    finally:
        _tools_refreshing.pop(tool_id, None)


async def _tools_refresh_loop() -> None:
    """Background task: refresh all enabled tool accounts on a schedule."""
    from tools.store import load_tools

    while True:
        cfg = get_config()
        interval_minutes = cfg.get("tools", {}).get("refresh_interval_minutes", 1440)
        await asyncio.sleep(max(1, interval_minutes) * 60)
        tools = load_tools(DATA_DIR)
        for tool in tools:
            if not tool.get("enabled", True):
                continue
            try:
                await _refresh_one_tool(tool)
            except Exception:
                pass


@app.on_event("startup")
async def start_tools_refresh_loop() -> None:
    asyncio.create_task(_tools_refresh_loop())


@app.get("/api/tools", response_model=list[ToolInfo])
async def list_tools():
    from tools.store import load_tools
    tools = load_tools(DATA_DIR)
    result = []
    for t in tools:
        new_count = len(set(t.get("latest_ids") or []) - set(t.get("seen_ids") or []))
        result.append(ToolInfo(
            id=t["id"], username=t["username"], title=t.get("title", t["username"]),
            enabled=t.get("enabled", True), auto_ingest=t.get("auto_ingest", False),
            last_fetched=t.get("last_fetched"), last_error=t.get("last_error"),
            new_count=new_count,
        ))
    return result


@app.post("/api/tools", response_model=ToolInfo)
async def add_tool_endpoint(req: AddToolRequest):
    import datetime
    from tools.store import add_tool as _add_tool, update_tool as _update_tool, set_latest_ids
    from tools.fetcher import fetch_starred, save_repos_cache

    tool = _add_tool(DATA_DIR, req.username, req.title or req.username)
    try:
        repos = await fetch_starred(tool["username"], _get_github_token(), DATA_DIR)
        save_repos_cache(DATA_DIR, tool["id"], repos)
        ids = [r["node_id"] for r in repos]
        set_latest_ids(DATA_DIR, tool["id"], ids)
        now = datetime.datetime.utcnow().isoformat() + "Z"
        tool = _update_tool(DATA_DIR, tool["id"], {"last_fetched": now, "last_error": None}) or tool
        if tool.get("auto_ingest"):
            await _auto_ingest_tool(tool)
    except Exception as exc:
        _update_tool(DATA_DIR, tool["id"], {"last_error": str(exc)})

    new_count = len(set(tool.get("latest_ids") or []) - set(tool.get("seen_ids") or []))
    return ToolInfo(
        id=tool["id"], username=tool["username"], title=tool.get("title", tool["username"]),
        enabled=tool.get("enabled", True), auto_ingest=tool.get("auto_ingest", False),
        last_fetched=tool.get("last_fetched"), last_error=tool.get("last_error"),
        new_count=new_count,
    )


# Fixed-path routes MUST come before /{tool_id} to avoid being swallowed as a path param

@app.get("/api/tools/status")
async def get_tools_status():
    """Return which tool accounts are currently being refreshed."""
    return {"refreshing": _tools_refreshing}


@app.get("/api/tools/search")
async def search_tools(q: str = Query(...)):
    """Search starred repo caches by name, description, topics, language."""
    from tools.store import load_tools
    from tools.fetcher import load_repos_cache

    q_lower = q.lower()
    results = []
    for tool in load_tools(DATA_DIR):
        repos = load_repos_cache(DATA_DIR, tool["id"]) or []
        for r in repos:
            if (
                q_lower in r.get("full_name", "").lower()
                or q_lower in (r.get("description") or "").lower()
                or q_lower in (r.get("language") or "").lower()
                or any(q_lower in t.lower() for t in r.get("topics", []))
            ):
                results.append({
                    "full_name": r["full_name"],
                    "url": r["html_url"],
                    "description": r.get("description") or "",
                    "language": r.get("language") or "",
                    "stars": r.get("stargazers_count", 0),
                    "topics": r.get("topics", []),
                })
    results.sort(key=lambda x: -x["stars"])
    return {"results": results[:50]}


@app.post("/api/tools/refresh")
async def refresh_all_tools():
    """Immediately pull all enabled tool accounts."""
    from tools.store import load_tools

    tools = load_tools(DATA_DIR)
    refreshed = errors = 0
    for tool in tools:
        if not tool.get("enabled", True):
            continue
        try:
            await _refresh_one_tool(tool)
            refreshed += 1
        except Exception:
            errors += 1
    return {"refreshed": refreshed, "errors": errors}


@app.get("/api/tools/config")
async def get_tools_config():
    return {
        "refresh_interval_minutes": _get_refresh_interval("tools", 1440),
        "github_token_set": bool(os.environ.get("GITHUB_TOKEN", "").strip()),
    }


@app.patch("/api/tools/config")
async def update_tools_config(body: dict):
    result = _set_refresh_interval("tools", 1440, body)
    result["github_token_set"] = bool(os.environ.get("GITHUB_TOKEN", "").strip())
    return result


@app.delete("/api/tools/{tool_id}")
async def delete_tool(tool_id: str):
    from tools.store import remove_tool
    if not remove_tool(DATA_DIR, tool_id):
        raise HTTPException(404, "Tool not found")
    return {"ok": True}


@app.patch("/api/tools/{tool_id}", response_model=ToolInfo)
async def update_tool_endpoint(tool_id: str, req: UpdateToolRequest):
    from tools.store import update_tool as _update_tool
    updates = req.model_dump(exclude_none=True)
    tool = _update_tool(DATA_DIR, tool_id, updates)
    if not tool:
        raise HTTPException(404, "Tool not found")
    new_count = len(set(tool.get("latest_ids") or []) - set(tool.get("seen_ids") or []))
    return ToolInfo(
        id=tool["id"], username=tool["username"], title=tool.get("title", tool["username"]),
        enabled=tool.get("enabled", True), auto_ingest=tool.get("auto_ingest", False),
        last_fetched=tool.get("last_fetched"), last_error=tool.get("last_error"),
        new_count=new_count,
    )


@app.get("/api/tools/{tool_id}/preview", response_model=ToolPreviewResponse)
async def preview_tool(tool_id: str):
    from tools.store import get_tool
    from tools.fetcher import load_repos_cache

    tool = get_tool(DATA_DIR, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")

    repos = load_repos_cache(DATA_DIR, tool_id) or []

    # Determine ingested repos by checking the library index (ground truth).
    # Match by URL (current) or by title (legacy items ingested without a URL).
    idx = get_index()
    all_indexed_urls = {m.get("url") for m in idx.all_items().values() if m.get("url")}
    all_indexed_titles = {m.get("title") for m in idx.all_items().values() if m.get("title")}

    repo_models = [
        StarredRepo(
            node_id=r["node_id"], full_name=r["full_name"], html_url=r["html_url"],
            description=r.get("description") or "",
            topics=r.get("topics") or [], language=r.get("language") or "",
            stars=r.get("stargazers_count", 0),
            seen=r["html_url"] in all_indexed_urls or r["full_name"] in all_indexed_titles,
            readme_path=r.get("readme_path"),
        )
        for r in repos
    ]
    new_count = sum(1 for r in repo_models if not r.seen)
    return ToolPreviewResponse(title=tool["title"], repos=repo_models, new_count=new_count)


@app.get("/api/tools/{tool_id}/readme")
async def get_tool_readme(tool_id: str, full_name: str = Query(...)):
    """Return the raw markdown README for a starred repo."""
    readme_file = DATA_DIR / "tools" / full_name / "README.md"
    if not readme_file.exists():
        raise HTTPException(404, "README not available")
    return PlainTextResponse(readme_file.read_text(encoding="utf-8", errors="ignore"))


@app.post("/api/tools/{tool_id}/ingest")
async def ingest_tool_repos(tool_id: str, body: Optional[dict] = None):
    """Ingest starred repos. Pass {"node_ids": [...]} or omit for all unseen."""
    from tools.store import get_tool
    from pipeline import ingest_text_pipeline, ingest_url_pipeline

    tool = get_tool(DATA_DIR, tool_id)
    if not tool:
        raise HTTPException(404, "Tool not found")

    from tools.fetcher import load_repos_cache
    repos = load_repos_cache(DATA_DIR, tool_id) or []
    node_ids_filter: list[str] | None = (body or {}).get("node_ids")

    idx = get_index()
    all_indexed_urls = {m.get("url") for m in idx.all_items().values() if m.get("url")}
    all_indexed_titles = {m.get("title") for m in idx.all_items().values() if m.get("title")}

    if node_ids_filter is not None:
        to_ingest = [r for r in repos if r["node_id"] in node_ids_filter]
    else:
        to_ingest = [r for r in repos if r["html_url"] not in all_indexed_urls and r["full_name"] not in all_indexed_titles]

    llm = get_llm()
    index = get_index()
    imported = skipped = failed = 0
    item_ids: list[str] = []
    sem = asyncio.Semaphore(4)  # limit concurrent LLM calls

    async def _ingest_one(repo: dict) -> None:
        nonlocal imported, skipped, failed
        async with sem:
            try:
                title = repo["full_name"]
                if repo.get("readme_path"):
                    readme = Path(repo["readme_path"]).read_text(encoding="utf-8", errors="ignore")
                    body_text = f"# {title}\n\n{repo.get('description','')}\n\n{readme}"
                else:
                    # No README — build a minimal body from available metadata
                    topics = ", ".join(repo.get("topics") or [])
                    body_text = (
                        f"# {title}\n\n"
                        f"{repo.get('description','')}\n\n"
                        f"Language: {repo.get('language','')}\n"
                        f"Topics: {topics}\n"
                        f"Stars: {repo.get('stargazers_count', 0)}\n"
                        f"URL: {repo['html_url']}"
                    )
                result = await ingest_text_pipeline(
                    title=title, body=body_text,
                    category="tools", tags=repo.get("topics") or ["tool"],
                    llm=llm, index=index, data_dir=DATA_DIR,
                    vector_index=_vector_index,
                    url=repo["html_url"],
                    content_type="starred_repo",
                )
                if result.get("duplicate"):
                    skipped += 1
                else:
                    imported += 1
                    item_ids.append(result["item_id"])
            except Exception as e:
                log.warning("Tool ingest failed for %s: %s", repo.get("full_name"), e)
                failed += 1

    await asyncio.gather(*[_ingest_one(r) for r in to_ingest])
    return {"imported": imported, "skipped": skipped, "failed": failed, "item_ids": item_ids}


# ---------------------------------------------------------------------------
# Static / Dashboard
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent.parent / "frontend" / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/") and request.url.path.endswith((".js", ".css")):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    index_file = STATIC_DIR / "index.html"
    content = index_file.read_text() if index_file.exists() else "<h1>bRAInZ</h1><p>Dashboard not built yet.</p>"
    return HTMLResponse(content, headers={"Cache-Control": "no-store"})
