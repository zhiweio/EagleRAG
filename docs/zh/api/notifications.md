# 通知 API

面向运维的轻量应用内通知流（摄入失败、系统事件等）。实现：`eagle_rag/api/notifications.py`，存储：`eagle_rag/notifications/store.py`。

---

## `GET /notifications`

| 查询 | 默认 | 说明 |
|-------|---------|-------------|
| `read` | — | `true` / `false` 过滤 |
| `limit` | 50 | 1–200 |
| `offset` | 0 | 分页 |

### 响应 — `NotificationListResponse`

```json
{
  "items": [
    {
      "notification_id": "notif_abc",
      "title": "Ingest failed",
      "body": "report.pdf — Knowhere timeout",
      "read": false,
      "created_at": "2025-07-05T08:00:00Z",
      "link": "/ingest"
    }
  ],
  "unread_count": 3,
  "limit": 50,
  "offset": 0
}
```

`NotificationOut` 字段可按 schema 包含 `severity`、`category`、`metadata`。

---

## `PATCH /notifications/{notification_id}`

将单条通知标为已读。`NotificationReadResponse`（确认）。**404** 未找到。

---

## `POST /notifications/read-all`

批量标为已读。`NotificationReadAllResponse`：

```json
{ "updated": 12 }
```

---

## 认证

REST 路由无认证 —— 与其他端点相同的内网假设。

---

## 前端状态

通知铃铛 UI 可能尚未完整 —— API 已稳定，供后续 AppBar 集成。轮询模式可使用 TanStack Query 的 `refetchInterval`。

---

## 相关文档

- [会话与通知（后端）](../backend/sessions-notifications.md)
