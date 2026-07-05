"""PostgreSQL ORM model package (SQLModel + Alembic metadata).

Table definitions are split by functional domain; Alembic uses ``metadata`` to
generate and compare migrations.
"""

from __future__ import annotations

from eagle_rag.db.models.attachments import Attachment
from eagle_rag.db.models.base import metadata
from eagle_rag.db.models.dedup import DocumentDedup
from eagle_rag.db.models.document_keywords import DocumentKeyword
from eagle_rag.db.models.documents import Document
from eagle_rag.db.models.images import Image
from eagle_rag.db.models.knowledge_bases import KnowledgeBase
from eagle_rag.db.models.mcp_call_log import McpCallLog
from eagle_rag.db.models.metric_sample import MetricSample
from eagle_rag.db.models.notifications import Notification
from eagle_rag.db.models.sessions import Message, Session
from eagle_rag.db.models.system_setting import SystemSetting
from eagle_rag.db.models.tasks import TaskAudit

__all__ = [
    "metadata",
    "Document",
    "DocumentKeyword",
    "Image",
    "Session",
    "Message",
    "DocumentDedup",
    "TaskAudit",
    "KnowledgeBase",
    "Attachment",
    "Notification",
    "McpCallLog",
    "SystemSetting",
    "MetricSample",
]
