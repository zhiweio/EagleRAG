# 附件 API

**查询时上下文**的会话级上传 —— 在 `POST /query` 引用时惰性解析，**不**写入 Milvus。

实现：`eagle_rag/api/attachments.py`，存储：`eagle_rag/attachments/`，解析器：`eagle_rag/attachments/parser.py`。

---

## 设计考量

附件遵循对话式 RAG 中常见的*临时上下文*模式（参见 ChatGPT 文件上传）：字节存于对象存储（TTL 友好），查询时再解析，召回的附件 chunk 在 `sources` 中标记 `source: "attachment"`。

| 属性 | 附件 | 已摄入文档 |
|----------|-------------|-------------------|
| Milvus 索引 | **否** | 是 |
| `document_id` | **否** | 是 |
| 范围过滤 | 通过查询上 `attachments[]` | 通过 `scope_filter` / `kb_name` |
| 去重 | 每次上传独立 | `(sha256, kb_name)` |

---

## `POST /attachments`

为即将进行的查询上传文件。

**Content-Type：** `multipart/form-data`

| 字段 | 必填 | 说明 |
|-------|----------|-------------|
| `file` | **是** | 原始字节 |
| `session_id` | 否 | 关联会话（便于归档） |

### 响应 — `AttachmentUploadResponse`（201）

```json
{
  "attachment_id": "att_abc123",
  "file_name": "screenshot.png",
  "mime": "image/png",
  "size_bytes": 204800,
  "session_id": "sess_xyz"
}
```

| HTTP | 条件 |
|------|-----------|
| `201` | 已存储 |
| `422` | 空文件 |

**幂等性：** 即使字节相同，每次上传也创建**新** `attachment_id`。

---

## `GET /attachments/{attachment_id}`

`AttachmentOut` 元数据。未知 **404**。

---

## `GET /attachments/{attachment_id}/content`

以存储的 `mime` 类型返回原始字节。元数据或内容缺失 **404**。

供内部解析器与可选直接下载 —— 非主要问答路径。

---

## `DELETE /attachments/{attachment_id}`

`DeletedResponse`。未找到 **404**。

---

## 查询集成

在 `QueryRequest.attachments` 传入 id：

```json
{
  "query": "Summarize this slide",
  "attachments": ["att_abc123"]
}
```

引擎路径（`router_engine._prepare_attachments`）：

1. 从附件存储加载字节
2. 图像 → VLM 上下文；文档 → 惰性解析（`attachments/parser.py`）
3. SSE 流中可选 yield 解析进度的 `step` 事件
4. 在 KB 检索结果**之前**合并附件节点
5. 在 sources 中标记 `source: "attachment"` 与 `attachment_id`

图像附件出现在 `ImageSource`；文本在 `TextSource`。

---

## 多租户

附件**不**按 KB 划分。可选绑定 `session_id`。KB 隔离仅适用于与附件并行的已索引语料检索。

---

## 前端集成

`Composer.tsx` 经 `uploadAttachment`（`useAttachments.ts`）上传，收集 `attachment_id` 列表，传给 `QAClient.handleSend`。

支持：回形针按钮、图像预览芯片、失败 toast。

见 [问答模块](../frontend/qa-module.md)。

---

## 相关文档

- [查询](query.md) —— `QueryRequest` 上的 `attachments` 字段
- [会话](sessions.md) —— 上传时可选 `session_id`
