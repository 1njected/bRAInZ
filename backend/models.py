"""Pydantic models for API request/response validation."""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, HttpUrl


# --- Ingestion ---

class IngestURLRequest(BaseModel):
    url: str
    category: Optional[str] = None
    tags: Optional[list[str]] = None


class IngestSnapshotRequest(BaseModel):
    url: str
    title: str = ""
    html: str
    category: Optional[str] = None
    tags: Optional[list[str]] = None


class IngestTextRequest(BaseModel):
    title: str
    body: str
    category: Optional[str] = None
    tags: Optional[list[str]] = None


class BulkURLItem(BaseModel):
    url: str
    category: Optional[str] = None
    tags: Optional[list[str]] = None


class BulkURLRequest(BaseModel):
    urls: list[BulkURLItem]


class IngestResponse(BaseModel):
    item_id: str
    title: str
    category: str
    tags: list[str]
    duplicate: bool = False


class BulkIngestResponse(BaseModel):
    imported: int
    skipped: int
    failed: int
    item_ids: list[str]


# --- Items ---

class ItemMetadata(BaseModel):
    id: str
    title: str
    url: Optional[str] = None
    category: str
    tags: list[str]
    added: str
    updated: str
    source: str
    content_type: str
    content_hash: str
    word_count: int
    summary: str
    classified_by: str
    pub_date: Optional[str] = None
    has_snapshot: bool = False
    has_original: bool = False
    embedded: bool
    verified: bool = False


class ItemDetail(ItemMetadata):
    content: Optional[str] = None


class ItemListResponse(BaseModel):
    items: list[ItemMetadata]
    total: int
    limit: int
    offset: int


class UpdateItemRequest(BaseModel):
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    title: Optional[str] = None


class CategoryInfo(BaseModel):
    name: str
    count: int


class TagInfo(BaseModel):
    name: str
    count: int


# --- RAG ---

class QueryRequest(BaseModel):
    question: str
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    top_k: int = 8
    model: Optional[str] = None  # override query model for this request


class SearchRequest(BaseModel):
    query: str
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    top_k: int = 10


class SourceRef(BaseModel):
    item_id: str
    title: str
    url: Optional[str] = None
    relevance_score: float


class ToolRef(BaseModel):
    item_id: str
    title: str       # owner/repo
    url: str         # GitHub URL
    relevance_score: float


class QueryResponse(BaseModel):
    answer: str
    thinking: str = ""
    sources: list[SourceRef]
    tools: list[ToolRef] = []


class SearchResult(BaseModel):
    item_id: str
    score: float
    title: str
    url: Optional[str] = None
    category: str
    content: Optional[str] = None
    content_type: str = "text"


class SearchResponse(BaseModel):
    results: list[SearchResult]


# --- Skills ---

class GenerateSkillRequest(BaseModel):
    topic: str
    categories: Optional[list[str]] = None
    description: Optional[str] = None


class SkillInfo(BaseModel):
    topic: str
    path: str
    generated: str


# --- Planner ---

class GeneratePlanRequest(BaseModel):
    description: str


class PlanInfo(BaseModel):
    slug: str
    title: str
    generated: str


class PlanResponse(BaseModel):
    slug: str
    title: str
    content: str
    generated: str


# --- System ---

class HealthResponse(BaseModel):
    status: str
    total_items: int
    categories: dict[str, int]
    llm_provider: str
    embedded_items: int
    open_access: bool = False


class LLMConfigResponse(BaseModel):
    provider: str
    classification_model: str
    query_model: str
    embedding_model: str


# --- Digest ---

class GenerateDigestPageRequest(BaseModel):
    item_id: str
    tags: list[str] = []

class DigestPageInfo(BaseModel):
    page_id: str
    title: str
    category: str
    tags: list[str] = []
    suggested_path: str
    source_item_id: str | None = None
    source_url: str | None = None
    created: str
    updated: str
    word_count: int

class DigestPageDetail(DigestPageInfo):
    content: str

class UpdateDigestPageRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    category: str | None = None

class FetchRepoRequest(BaseModel):
    url: str

class ImportDigestPageItem(BaseModel):
    rel_path: str
    title: str

class ImportDigestPagesRequest(BaseModel):
    url: str
    pages: list[ImportDigestPageItem]

class ImportDigestPagesResponse(BaseModel):
    imported: int
    skipped: int
    failed: int
    page_ids: list[str]

class UploadDigestPageResponse(BaseModel):
    page_id: str
    title: str
    category: str
    tags: list[str]


# --- Feeds ---

class FeedInfo(BaseModel):
    id: str
    url: str
    title: str
    enabled: bool
    last_fetched: Optional[str] = None
    last_error: Optional[str] = None
    unread_count: Optional[int] = None  # set on preview, not stored


class AddFeedRequest(BaseModel):
    url: str
    title: Optional[str] = None


class UpdateFeedRequest(BaseModel):
    title: Optional[str] = None
    enabled: Optional[bool] = None


class FeedEntry(BaseModel):
    title: str
    url: str
    summary: str
    content: str = ""   # full article body if provided by feed
    published: str
    seen: bool = False   # True if in the feed's seen_urls
    comments_url: Optional[str] = None  # Reddit comments link


class FeedPreviewResponse(BaseModel):
    feed_title: str
    entries: list[FeedEntry]
    unread_count: int = 0


# --- Tools (GitHub Stars) ---

class ToolInfo(BaseModel):
    id: str
    username: str
    title: str
    enabled: bool
    auto_ingest: bool = False
    last_fetched: Optional[str] = None
    last_error: Optional[str] = None
    new_count: Optional[int] = None


class AddToolRequest(BaseModel):
    username: str
    title: Optional[str] = None


class UpdateToolRequest(BaseModel):
    title: Optional[str] = None
    enabled: Optional[bool] = None
    auto_ingest: Optional[bool] = None


class StarredRepo(BaseModel):
    node_id: str
    full_name: str
    html_url: str
    description: Optional[str] = None
    topics: list[str] = []
    language: Optional[str] = None
    stars: int = 0
    seen: bool = False
    readme_path: Optional[str] = None


class ToolPreviewResponse(BaseModel):
    title: str
    repos: list[StarredRepo]
    new_count: int = 0
