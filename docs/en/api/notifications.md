# Notifications API

Lightweight in-app notification feed for operator alerts (ingest failures, system events). Implementation: `eagle_rag/api/notifications.py`, store: `eagle_rag/notifications/store.py`.

---

## `GET /notifications`

| Query | Default | Description |
|-------|---------|-------------|
| `read` | — | `true` / `false` filter |
| `limit` | 50 | 1–200 |
| `offset` | 0 | Pagination |

### Response — `NotificationListResponse`

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

`NotificationOut` fields may include `severity`, `category`, `metadata` per schema.

---

## `PATCH /notifications/{notification_id}`

Mark single notification read. `NotificationReadResponse` (ack). **404** if not found.

---

## `POST /notifications/read-all`

Bulk mark read. `NotificationReadAllResponse`:

```json
{ "updated": 12 }
```

---

## Authentication

No auth on REST routes — same intranet assumption as other endpoints.

---

## Frontend status

Notification bell UI may be partial — API is stable for future AppBar integration. Polling pattern would use TanStack Query with `refetchInterval`.

---

## Related documentation

- [Sessions & notifications (backend)](../backend/sessions-notifications.md)
