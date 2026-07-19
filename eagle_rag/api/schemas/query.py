"""Query API models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QueryFilters(BaseModel):
    source_type: str | None = Field(
        default=None, description="Scalar filter on document source_type"
    )
    pipeline: str | None = Field(default=None, description="knowhere | pixelrag")
    year: int | None = Field(default=None, description="Scalar filter on document year")


class ScopeSelection(BaseModel):
    """Advanced scope filter: union (OR) of knowledge bases, documents and tags.

    When any list is non-empty, retrieval is scoped to the union of the selected
    knowledge bases, the selected documents, and the documents matching any
    selected tag. Empty selection falls back to the legacy single ``kb_name`` /
    ``scope`` behavior.
    """

    kb_names: list[str] = Field(
        default_factory=list, description="Selected knowledge base identifiers"
    )
    document_ids: list[str] = Field(default_factory=list, description="Selected document_id values")
    tags: list[str] = Field(default_factory=list, description="Selected tags (keywords)")

    def is_empty(self) -> bool:
        """Whether no scope dimension has been selected."""
        return not (self.kb_names or self.document_ids or self.tags)


class QueryRequest(BaseModel):
    plugin_namespace: str | None = Field(
        default=None,
        description="Ignored in production; must match instance namespace or returns 403",
    )
    session_id: str | None = Field(default=None, description="Auto-create a session when omitted")
    query: str = ""
    mode: str | None = Field(default=None, description="auto | text | visual | hybrid")
    kb_name: str | None = Field(
        default=None, description="Knowledge base identifier (multi-tenant)"
    )
    attachments: list[str] | None = Field(default=None, description="List of attachment_id values")
    scope: list[str] | None = Field(
        default=None, description="Restrict to these document_id values"
    )
    filters: QueryFilters | None = None
    scope_filter: ScopeSelection | None = Field(
        default=None,
        description="Advanced scope filter (knowledge bases / documents / tags, union)",
    )

    @model_validator(mode="after")
    def _validate_query_or_attachments(self) -> QueryRequest:
        from eagle_rag.api.deps import validate_request_namespace

        validate_request_namespace(self.plugin_namespace)
        has_query = bool(self.query.strip())
        has_attachments = bool(self.attachments)
        if not has_query and not has_attachments:
            raise ValueError("query or attachments is required")
        if self.attachments and len(self.attachments) > 1:
            raise ValueError("at most one attachment is allowed")
        return self


class TextSource(BaseModel):
    """A retrieved text chunk exposed to clients.

    Beyond the citation coordinates (``path`` / ``document_id`` / ``score``) the
    chunk body (``content``) and its semantic metadata are surfaced so the UI can
    render the retrieved evidence in full instead of a bare reference.
    """

    type: str = Field(default="text", description="text | table | image | section_summary")
    path: str | None = None
    level: int | str | None = None
    document_id: str | None = None
    score: float | None = None
    source: str | None = Field(default=None, description="kb | attachment")
    attachment_id: str | None = None
    file_name: str | None = None
    content: str | None = Field(default=None, description="Chunk body (table chunks carry HTML)")
    summary: str | None = None
    keywords: list[str] = Field(default_factory=list)
    page_nums: list[int] = Field(default_factory=list)
    file_path: str | None = None
    document_top_summary: str | None = None
    chunk_count: int | None = Field(default=None, description="section_summary child chunk count")
    kb_name: str | None = None
    source_type: str | None = None


class ImageSource(BaseModel):
    """A retrieved visual tile exposed to clients.

    Carries the four semantic-tree anchor fields (``chunk_type`` /
    ``parent_section`` / ``content_summary`` / ``source_chunk_id``) so the UI can
    place the tile back onto the document's parsed structure.
    """

    type: str = Field(default="image")
    image_id: str | None = None
    image_path: str | None = None
    page: int | str | None = None
    position: str | None = None
    document_id: str | None = None
    score: float | None = None
    source: str | None = Field(default=None, description="kb | attachment")
    attachment_id: str | None = None
    file_name: str | None = None
    chunk_type: str | None = Field(default=None, description="tile | image | table")
    parent_section: str | None = Field(default=None, description="Enclosing text chunk path")
    content_summary: str | None = None
    source_chunk_id: str | None = None
    kb_name: str | None = None
    source_type: str | None = None
    year: int | None = None


class QuerySources(BaseModel):
    text: list[TextSource] = Field(default_factory=list)
    image: list[ImageSource] = Field(default_factory=list)


class RouteInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: str | None = None
    selected: list[str] | None = None
    reason: str | None = None
    kb_name: str | None = None


class QueryStep(BaseModel):
    """Query execution step (route / recall / rerank / generate / warning, etc.)."""

    model_config = ConfigDict(extra="allow")

    name: str
    detail: str | None = None


class QueryResponse(BaseModel):
    session_id: str
    message_id: str
    answer: str
    sources: QuerySources = Field(default_factory=QuerySources)
    route: RouteInfo = Field(default_factory=RouteInfo)
    steps: list[QueryStep] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str = ""
    plugin_namespace: str | None = Field(
        default=None,
        description="Ignored in production; must match instance namespace or returns 403",
    )
    mode: str | None = Field(default=None, description="auto | text | visual | hybrid")
    scope: list[str] | None = Field(
        default=None, description="Restrict to these document_id values"
    )
    kb_name: str | None = Field(
        default=None, description="Knowledge base identifier (multi-tenant)"
    )
    attachments: list[str] | None = Field(default=None, description="List of attachment_id values")
    filters: QueryFilters | None = None
    scope_filter: ScopeSelection | None = Field(
        default=None,
        description="Advanced scope filter (knowledge bases / documents / tags, union)",
    )

    @model_validator(mode="after")
    def _validate_query_or_attachments(self) -> SearchRequest:
        from eagle_rag.api.deps import validate_request_namespace

        validate_request_namespace(self.plugin_namespace)
        has_query = bool(self.query.strip())
        has_attachments = bool(self.attachments)
        if not has_query and not has_attachments:
            raise ValueError("query or attachments is required")
        if self.attachments and len(self.attachments) > 1:
            raise ValueError("at most one attachment is allowed")
        return self


class SearchResponse(BaseModel):
    sources: QuerySources = Field(default_factory=QuerySources)
    route: RouteInfo = Field(default_factory=RouteInfo)
    steps: list[QueryStep] = Field(default_factory=list)
