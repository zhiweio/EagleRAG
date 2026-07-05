"""User API models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class UserOut(BaseModel):
    user_id: str
    display_name: str
    avatar_initials: str
    locale: str
    created_at: str | None = None
    updated_at: str | None = None


class UserUpdate(BaseModel):
    display_name: str | None = None
    avatar_initials: str | None = None
    locale: str | None = None


class UserPreferences(BaseModel):
    default_kb_name: str = ""
    notifications_enabled: bool = True
    ingest_poll_interval_ms: int = 5000


class PreferencesUpdate(BaseModel):
    default_kb_name: str | None = None
    notifications_enabled: bool | None = None
    ingest_poll_interval_ms: int | None = None

    def to_patch(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)
