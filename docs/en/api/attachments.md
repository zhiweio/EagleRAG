# Attachments API

Session-scoped uploads for **query-time context** — parsed lazily when referenced in `POST /query`, never written to Milvus.

Implementation: `eagle_rag/api/attachments.py`, store in `eagle_rag/attachments/`, parser in `eagle_rag/attachments/parser.py`.

---

## Design rationale

Attachments follow the *ephemeral context* pattern common in conversational RAG (cf. ChatGPT file uploads): bytes live in object storage with a TTL-friendly store, parsing runs at query time, and retrieved attachment chunks appear in `sources` with `source: "attachment"`.

| Property | Attachments | Ingested documents |
|----------|-------------|-------------------|
| Milvus index | **No** | Yes |
| `document_id` | **No** | Yes |
| Scope filter | Via `attachments[]` on query | Via `scope_filter` / `kb_name` |
| Dedup | Per upload | `(sha256, kb_name)` |

---

## `POST /attachments`

Upload file for upcoming query.

**Content-Type:** `multipart/form-data`

| Field | Required | Description |
|-------|----------|-------------|
| `file` | **Yes** | Raw bytes |
| `session_id` | No | Associate with session (housekeeping) |

### Response — `AttachmentUploadResponse` (201)

```json
{
  "attachment_id": "att_abc123",
  "file_name": "screenshot.png",
  "mime": "image/png",
  "size_bytes": 204800,
  "session_id": "sess_xyz"
}
```

| HTTP | Condition |
|------|-----------|
| `201` | Stored |
| `422` | Empty file |

**Idempotency:** Each upload creates a **new** `attachment_id` even for identical bytes.

---

## `GET /attachments/{attachment_id}`

`AttachmentOut` metadata. **404** if unknown.

---

## `GET /attachments/{attachment_id}/content`

Raw bytes with stored `mime` type. **404** if meta or content missing.

Used by internal parser and optional direct download — not primary Q&A path.

---

## `DELETE /attachments/{attachment_id}`

`DeletedResponse`. **404** if not found.

---

## Query integration

Pass ids on `QueryRequest.attachments`:

```json
{
  "query": "Summarize this slide",
  "attachments": ["att_abc123"]
}
```

Engine path (`router_engine._prepare_attachments`):

1. Load bytes from attachment store
2. Route images → VLM context; documents → lazy parse (`attachments/parser.py`)
3. Yield optional `step` event for parse progress in SSE stream
4. Merge attachment nodes **before** KB retrieval results
5. Mark sources with `source: "attachment"` and `attachment_id`

Image attachments surface in `ImageSource`; text in `TextSource`.

---

## Multi-tenancy

Attachments are **not** KB-scoped. They bind to `session_id` optionally. KB isolation applies only to indexed corpus retrieval alongside attachments.

---

## Frontend integration

`Composer.tsx` uploads via `uploadAttachment` (`useAttachments.ts`), collects `attachment_id` list, passes to `QAClient.handleSend`.

Supported UX: paperclip button, image preview chips, error toasts on failure.

See [Q&A module](../frontend/qa-module.md).

---

## Related documentation

- [Query](query.md) — `attachments` field on `QueryRequest`
- [Sessions](sessions.md) — optional `session_id` on upload
