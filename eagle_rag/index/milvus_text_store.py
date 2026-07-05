"""Milvus text vector store wrapper (DashScope Qwen text-embedding-v4, with kb_name scalar filter).

Wraps reads/writes to the text collection ``eagle_text`` via
``llama-index-vector-stores-milvus``:
- Embedding model switched from OpenAI to DashScope (Qwen text-embedding-v4,
  dim 1536); configured via ``settings.embedding.text``
  (provider/model/api_key/base_url/dim).
- ``get_text_vector_store``: lazily initializes a ``MilvusVectorStore`` singleton
  with ``similarity_metric=COSINE`` (matches text-embedding-v4 normalized output).
- ``get_text_index``: builds a ``VectorStoreIndex`` over the vector store with
  a lazily-constructed embed_model.
- ``upsert_text_nodes`` / ``delete_text_nodes``: node-level insert/delete.
- ``search_text``: text vector retrieval (hybrid search) supporting scalar
  filters such as ``kb_name`` / ``source_type`` (translated to Milvus ``expr``
  via LlamaIndex ``MetadataFilters``).
- ``ensure_collection``: triggers vector store initialization (Milvus collection
  is auto-created on first write).

Embedding uses asymmetric retrieval: ``text_type=document`` on the write side;
the query side is automatically switched to ``text_type=query`` by the underlying
``_get_query_embedding``. No Milvus/DashScope client connects at import time;
they initialize only on function invocation.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from eagle_rag.config import get_settings
from eagle_rag.telemetry import get_logger

if TYPE_CHECKING:
    from llama_index.core import VectorStoreIndex
    from llama_index.core.schema import TextNode
    from llama_index.vector_stores.milvus import MilvusVectorStore

__all__ = [
    "get_text_vector_store",
    "get_text_index",
    "upsert_text_nodes",
    "delete_text_nodes",
    "ensure_collection",
    "search_text",
    "count_text",
    "delete_text_by_kb",
    "fetch_text_nodes_by_kb",
    "fetch_text_nodes_by_document_id",
]

logger = get_logger(__name__)

_text_vector_store: MilvusVectorStore | None = None
_text_index: VectorStoreIndex | None = None


def _build_embed_model():
    """Lazily build a DashScope embedding model from ``settings.embedding.text``.

    Uses Qwen text-embedding-v4 (DashScope). ``text_type`` defaults to
    ``document`` (write side); query encoding is switched to ``query`` by the
    underlying ``_get_query_embedding`` for asymmetric retrieval. When api_key
    is empty it is omitted and the ``dashscope`` SDK falls back to the
    ``DASHSCOPE_API_KEY`` environment variable (validation deferred to actual
    embed calls).

    ``embed_batch_size`` is capped at 10: DashScope text-embedding-v4 rejects
    batches larger than 10 with a 400 error, which the SDK swallows and returns
    None embeddings — capping avoids silent None vectors.

    ``dimension`` is forwarded to the DashScope API via a thin subclass.
    LlamaIndex's ``DashScopeEmbedding`` (all versions up to 0.5.0) wraps
    ``**kwargs`` into ``kwargs=kwargs`` instead of ``**kwargs`` when calling
    ``dashscope.TextEmbedding.call()``, so ``dimension`` never reaches the
    API and the model falls back to its default 1024. The subclass bypasses
    the broken helper and calls ``dashscope.TextEmbedding.call()`` directly.
    """
    from http import HTTPStatus

    from llama_index.embeddings.dashscope import DashScopeEmbedding

    cfg = get_settings().embedding.text
    dim = cfg.dim or 1536

    class _DimensionalDashScopeEmbedding(DashScopeEmbedding):
        """DashScope embedding with explicit ``dimension`` forwarding.

        Overrides the three embedding methods to call
        ``dashscope.TextEmbedding.call()`` directly (bypassing the broken
        ``get_text_embedding`` helper that wraps kwargs incorrectly).
        """

        def _call_dashscope(self, texts: list[str], text_type: str) -> list[list[float] | None]:
            import dashscope

            resp = dashscope.TextEmbedding.call(
                model=self.model_name,
                input=texts,
                api_key=self._api_key,
                text_type=text_type,
                dimension=dim,
            )
            results: list[list[float] | None] = [None] * len(texts)
            if resp.status_code == HTTPStatus.OK:
                for emb in resp.output["embeddings"]:
                    results[emb["text_index"]] = emb["embedding"]
            else:
                logger.error("DashScope TextEmbedding failed: %s", resp)
            return results

        def _get_query_embedding(self, query: str) -> list[float]:
            results = self._call_dashscope([query], "query")
            return results[0] if results and results[0] is not None else []

        def _get_text_embedding(self, text: str) -> list[float]:
            results = self._call_dashscope([text], self._text_type)
            return results[0] if results and results[0] is not None else []

        def _get_text_embeddings(self, texts: list[str]) -> list[list[float] | None]:
            return self._call_dashscope(texts, self._text_type)

        async def _aget_query_embedding(self, query: str) -> list[float]:
            return self._get_query_embedding(query)

        async def _aget_text_embedding(self, text: str) -> list[float]:
            return self._get_text_embedding(text)

        async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float] | None]:
            return self._get_text_embeddings(texts)

    kwargs: dict[str, object] = {
        "model_name": cfg.model,
        "text_type": "document",
        "embed_batch_size": 10,
    }
    if cfg.api_key:
        kwargs["api_key"] = cfg.api_key
    return _DimensionalDashScopeEmbedding(**kwargs)


def get_text_vector_store() -> MilvusVectorStore:
    """Return the text vector store singleton (lazy, reads ``settings.milvus``).

    Uses collection=text_collection, dim=dim_text, overwrite=False,
    similarity_metric=COSINE (matches DashScope text-embedding-v4 normalized output).
    """
    global _text_vector_store  # noqa: PLW0603
    if _text_vector_store is None:
        try:
            from llama_index.vector_stores.milvus import MilvusVectorStore
        except ImportError:  # pragma: no cover
            from llama_index_vector_stores_milvus import (  # noqa: I001
                MilvusVectorStore,
            )

        cfg = get_settings().milvus
        uri = f"http://{cfg.host}:{cfg.port}"
        logger.info(
            "Initializing Milvus text vector store: uri=%s collection=%s dim=%s metric=COSINE",
            uri,
            cfg.text_collection,
            cfg.dim_text,
        )
        _text_vector_store = MilvusVectorStore(
            uri=uri,
            collection_name=cfg.text_collection,
            dim=cfg.dim_text,
            overwrite=False,
            similarity_metric="COSINE",
        )
    return _text_vector_store


def get_text_index() -> VectorStoreIndex:
    """Return the text ``VectorStoreIndex`` singleton (lazy; embed_model is lazily built)."""
    global _text_index  # noqa: PLW0603
    if _text_index is None:
        from llama_index.core import VectorStoreIndex

        vector_store = get_text_vector_store()
        embed_model = _build_embed_model()
        _text_index = VectorStoreIndex.from_vector_store(vector_store, embed_model=embed_model)
    return _text_index


def upsert_text_nodes(nodes: list[TextNode]) -> list[str]:
    """Insert a list of ``TextNode`` into the text index and return their node_ids."""
    index = get_text_index()
    index.insert_nodes(nodes)
    return [n.node_id for n in nodes]


def delete_text_nodes(node_ids: list[str]) -> None:
    """Delete nodes by node_id from the text index."""
    vector_store = get_text_vector_store()
    for node_id in node_ids:
        vector_store.delete(node_id)


def ensure_collection() -> None:
    """Trigger text vector store initialization.

    The Milvus collection is auto-created on first write.
    """
    get_text_vector_store()


def search_text(
    query: str,
    *,
    top_k: int = 5,
    kb_name: str | None = None,
    source_type: str | None = None,
    filters: list | None = None,
) -> list[dict[str, Any]]:
    """Text vector retrieval (hybrid search) supporting scalar filters such as ``kb_name``.

    Encodes the query with DashScope embedding (underlying ``text_type=query``,
    asymmetric retrieval), then runs ANN search against the Milvus ``eagle_text``
    collection. ``kb_name`` / ``source_type`` are translated to a Milvus scalar
    ``expr`` filter via LlamaIndex ``MetadataFilters`` (multi-tenant isolation +
    source filtering).

    Args:
        query: Query text.
        top_k: Number of top results to return.
        kb_name: Knowledge-base identifier filter (multi-tenant isolation).
        source_type: Source type filter (policy/financial/...).
        filters: Extra ``MetadataFilter`` list, merged with ``kb_name``/``source_type``.

    Returns:
        List of ``{"node_id":..., "text":..., "score":..., "metadata":{...}}``
        ordered by similarity descending.
    """
    from llama_index.core.vector_stores import (
        FilterOperator,
        MetadataFilter,
        MetadataFilters,
        VectorStoreQuery,
    )

    embed_model = _build_embed_model()
    query_embedding = embed_model.get_query_embedding(query)

    # Assemble scalar filters: kb_name / source_type / extra filters.
    filter_list: list[MetadataFilter] = []
    if kb_name is not None:
        filter_list.append(MetadataFilter(key="kb_name", value=kb_name, operator=FilterOperator.EQ))
    if source_type is not None:
        filter_list.append(
            MetadataFilter(key="source_type", value=source_type, operator=FilterOperator.EQ)
        )
    if filters:
        filter_list.extend(filters)
    metadata_filters = MetadataFilters(filters=filter_list) if filter_list else None

    vs_query = VectorStoreQuery(
        query_embedding=query_embedding,
        similarity_top_k=top_k,
        filters=metadata_filters,
    )
    result = get_text_vector_store().query(vs_query)

    out: list[dict[str, Any]] = []
    if result is None:
        return out
    nodes = result.nodes or []
    similarities = result.similarities or []
    for idx, node in enumerate(nodes):
        score = similarities[idx] if idx < len(similarities) else None
        out.append(
            {
                "node_id": node.node_id,
                "text": node.get_content(),
                "score": score,
                "metadata": node.metadata or {},
            }
        )
    return out


def _get_text_milvus_client():
    """Get a MilvusClient for management ops (count / delete).

    Returns ``(client, collection_name)``; returns ``(None, None)`` if the
    collection does not exist. The caller is responsible for ``client.close()``
    after use.
    """
    from pymilvus import MilvusClient

    cfg = get_settings().milvus
    client = MilvusClient(uri=f"http://{cfg.host}:{cfg.port}")
    if not client.has_collection(cfg.text_collection):
        client.close()
        return None, None
    return client, cfg.text_collection


def count_text(*, kb_name: str | None = None) -> int:
    """Count text vector entities by kb_name (metadata dynamic field)."""
    client, coll_name = _get_text_milvus_client()
    if client is None:
        return 0
    try:
        if kb_name is None:
            stats = client.get_collection_stats(coll_name)
            return int(stats.get("row_count", 0))
        expr = f'kb_name == "{kb_name}"'
        try:
            rows = client.query(coll_name, filter=expr, output_fields=["count(*)"])
            if rows:
                return int(rows[0].get("count(*)", 0))
            return 0
        except Exception:  # noqa: BLE001
            # fallback: query all ids without limit (accurate but memory-heavy)
            try:
                rows = client.query(coll_name, filter=expr, output_fields=["id"], limit=-1)
                return len(rows)
            except Exception:  # noqa: BLE001
                logger.warning("count_text query failed kb=%s", kb_name)
                return 0
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


# Metadata fields stored in Milvus dynamic field (must match chunks_to_text_nodes).
_REINDEX_OUTPUT_FIELDS = [
    "id",
    "text",
    "path",
    "level",
    "summary",
    "type",
    "file_path",
    "page_nums",
    "keywords",
    "connect_to",
    "document_top_summary",
    "document_id",
    "source_type",
    "kb_name",
]

# Batch size for querying Milvus (avoid OOM on large KBs).
_REINDEX_QUERY_BATCH = 1000


def fetch_text_nodes_by_kb(kb_name: str) -> list[Any]:
    """Fetch all TextNode data from Milvus for a given KB (for reindex).

    Returns a list of dicts with ``id``, ``text``, and ``metadata`` keys,
    suitable for rebuilding TextNodes with fresh embeddings. Reads existing
    text + metadata from Milvus (no Knowhere re-parse needed).

    Uses pagination (``_REINDEX_QUERY_BATCH``) to avoid loading everything
    into memory at once for large KBs.
    """
    client, coll_name = _get_text_milvus_client()
    if client is None:
        return []

    nodes_data: list[dict[str, Any]] = []
    try:
        expr = f'kb_name == "{kb_name}"'
        offset = 0
        while True:
            rows = client.query(
                coll_name,
                filter=expr,
                output_fields=_REINDEX_OUTPUT_FIELDS,
                limit=_REINDEX_QUERY_BATCH,
                offset=offset,
            )
            if not rows:
                break
            for row in rows:
                nodes_data.append(
                    {
                        "id": row.get("id"),
                        "text": row.get("text") or "",
                        "metadata": {
                            k: row.get(k)
                            for k in _REINDEX_OUTPUT_FIELDS
                            if k not in ("id", "text") and k in row
                        },
                    }
                )
            if len(rows) < _REINDEX_QUERY_BATCH:
                break
            offset += _REINDEX_QUERY_BATCH
        logger.info("fetch_text_nodes_by_kb: kb=%s fetched %d nodes", kb_name, len(nodes_data))
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_text_nodes_by_kb failed kb=%s: %s", kb_name, exc)
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

    return nodes_data


# Fields fetched when reconstructing a document's semantic tree.
_STRUCTURE_OUTPUT_FIELDS = [
    "id",
    "text",
    "path",
    "level",
    "summary",
    "type",
    "page_nums",
    "document_id",
    "chunk_count",
]
_NODE_CONTENT_FIELD = "_node_content"
_STRUCTURE_QUERY_OUTPUT_FIELDS = list(
    dict.fromkeys([*_STRUCTURE_OUTPUT_FIELDS, _NODE_CONTENT_FIELD])
)


def _escape_milvus_str(value: str) -> str:
    return value.replace('"', '\\"')


def _row_to_node_dict(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a Milvus row to ``{id, text, metadata}``."""
    raw_nc = row.get(_NODE_CONTENT_FIELD)
    if raw_nc:
        try:
            payload = json.loads(raw_nc) if isinstance(raw_nc, str) else raw_nc
            meta = dict(payload.get("metadata") or {})
            node_id = row.get("id") or payload.get("id_")
            text = row.get("text")
            if text is None:
                text = payload.get("text") or ""
            return {"id": node_id, "text": text or "", "metadata": meta}
        except (json.JSONDecodeError, TypeError):
            logger.debug("skip row with invalid _node_content", exc_info=True)

    meta = {
        k: row.get(k)
        for k in _STRUCTURE_OUTPUT_FIELDS
        if k not in ("id", "text") and row.get(k) is not None
    }
    if not meta:
        return None
    return {"id": row.get("id"), "text": row.get("text") or "", "metadata": meta}


def _matches_document(node: dict[str, Any], document_id: str) -> bool:
    return (node.get("metadata") or {}).get("document_id") == document_id


def _matches_types(node: dict[str, Any], types: list[str] | None) -> bool:
    if not types:
        return True
    return (node.get("metadata") or {}).get("type") in types


def _query_nodes_by_expr(
    client: Any,
    coll_name: str,
    expr: str,
    *,
    document_id: str,
    types: list[str] | None,
    limit: int | None,
    filter_by_node_content: bool,
) -> list[dict[str, Any]]:
    """Run a paginated Milvus query and map rows to node dicts."""
    nodes_data: list[dict[str, Any]] = []
    offset = 0
    while True:
        rows = client.query(
            coll_name,
            filter=expr,
            output_fields=_STRUCTURE_QUERY_OUTPUT_FIELDS,
            limit=_REINDEX_QUERY_BATCH,
            offset=offset,
        )
        if not rows:
            break
        for row in rows:
            node = _row_to_node_dict(row)
            if node is None:
                continue
            if filter_by_node_content and not _matches_document(node, document_id):
                continue
            if not _matches_types(node, types):
                continue
            nodes_data.append(node)
            if limit is not None and len(nodes_data) >= limit:
                return nodes_data[:limit]
        if len(rows) < _REINDEX_QUERY_BATCH:
            break
        offset += _REINDEX_QUERY_BATCH
    return nodes_data


def fetch_text_nodes_by_document_id(
    document_id: str,
    *,
    types: list[str] | None = None,
    limit: int | None = None,
    kb_name: str | None = None,
    path_prefix: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch a document's text nodes from Milvus for structure reconstruction.

    LlamaIndex stores the authoritative ``metadata.document_id`` inside
    ``_node_content``; the Milvus ``doc_id`` / ``document_id`` scalar fields are
    often empty for legacy rows. This helper tries scalar filters first, then
    falls back to a scoped scan (``kb_name`` or ``path_prefix``) with
    ``_node_content`` client-side filtering.

    Args:
        document_id: The document to scan.
        types: Optional chunk-type allow-list (e.g. ``["section_summary"]``).
        limit: Optional cap on the number of nodes returned.
        kb_name: KB scope for the ``_node_content`` fallback scan.
        path_prefix: Path prefix scope (typically the document filename).

    Returns:
        A list of ``{"id", "text", "metadata": {...}}`` dicts. ``metadata``
        carries ``path`` / ``level`` / ``summary`` / ``type`` / ``chunk_count``,
        enough to rebuild the section tree without a Knowhere re-parse.
    """
    client, coll_name = _get_text_milvus_client()
    if client is None:
        return []

    safe_id = _escape_milvus_str(document_id)
    nodes_data: list[dict[str, Any]] = []
    try:
        for field in ("document_id", "doc_id"):
            expr = f'{field} == "{safe_id}"'
            if types:
                joined = ", ".join(f'"{_escape_milvus_str(t)}"' for t in types)
                expr += f" and type in [{joined}]"
            nodes_data = _query_nodes_by_expr(
                client,
                coll_name,
                expr,
                document_id=document_id,
                types=types,
                limit=limit,
                filter_by_node_content=False,
            )
            if nodes_data:
                return nodes_data

        scope_expr: str | None = None
        if kb_name:
            scope_expr = f'kb_name == "{_escape_milvus_str(kb_name)}"'
        elif path_prefix:
            scope_expr = f'path like "{_escape_milvus_str(path_prefix)}%"'

        if scope_expr is None:
            logger.warning(
                "fetch_text_nodes_by_document_id: scalar miss, no kb_name/path_prefix for doc=%s",
                document_id,
            )
            return []

        nodes_data = _query_nodes_by_expr(
            client,
            coll_name,
            scope_expr,
            document_id=document_id,
            types=types,
            limit=limit,
            filter_by_node_content=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_text_nodes_by_document_id failed doc=%s: %s", document_id, exc)
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass

    return nodes_data


def reindex_kb_text(kb_name: str) -> int:
    """Re-embed and re-write all text nodes for a KB without re-parsing.

    Flow:
        1. Fetch all text + metadata from Milvus (``fetch_text_nodes_by_kb``).
        2. Delete old vectors for this KB (``delete_text_by_kb``).
        3. Rebuild TextNodes from fetched data.
        4. Re-embed with current embed_model and write back (``upsert_text_nodes``).

    Returns the number of re-indexed nodes.
    """
    from llama_index.core.schema import TextNode

    # 1. Fetch existing text + metadata from Milvus.
    nodes_data = fetch_text_nodes_by_kb(kb_name)
    if not nodes_data:
        logger.info("reindex_kb_text: kb=%s no nodes to reindex", kb_name)
        return 0

    # 2. Delete old vectors.
    deleted = delete_text_by_kb(kb_name)
    logger.info("reindex_kb_text: kb=%s deleted %d old vectors", kb_name, deleted)

    # 3. Rebuild TextNodes (preserving original id, text, metadata).
    nodes: list[TextNode] = []
    for nd in nodes_data:
        node = TextNode(
            text=nd["text"],
            id_=nd["id"],
        )
        node.metadata = nd["metadata"] or {}
        nodes.append(node)

    # 4. Re-embed and write back (embed_model is built from current settings).
    upsert_text_nodes(nodes)
    logger.info("reindex_kb_text: kb=%s re-indexed %d nodes", kb_name, len(nodes))
    return len(nodes)


def delete_text_by_kb(kb_name: str) -> int:
    """Delete text vectors by kb_name."""
    client, coll_name = _get_text_milvus_client()
    if client is None:
        return 0
    try:
        expr = f'kb_name == "{kb_name}"'
        try:
            rows = client.query(coll_name, filter=expr, output_fields=["id"], limit=16384)
            if not rows:
                rows = client.query(coll_name, filter=expr, output_fields=["node_id"], limit=16384)
            if not rows:
                return 0
            client.delete(coll_name, filter=expr)
            return len(rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning("delete_text_by_kb failed kb=%s: %s", kb_name, exc)
            return 0
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
