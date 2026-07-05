"""Users and preferences API (static stub, no persistence).

Endpoints are kept to satisfy the frontend contract; current product scope does
not require user profile or preference persistence, so all responses return
static defaults and PATCH is a no-op.
"""

from __future__ import annotations

from fastapi import APIRouter

from eagle_rag.api.schemas.users import PreferencesUpdate, UserOut, UserPreferences, UserUpdate

router = APIRouter(tags=["users"])

_DEFAULT_USER = UserOut(
    user_id="default",
    display_name="Eagle User",
    avatar_initials="EU",
    locale="zh",
)

_DEFAULT_PREFERENCES = UserPreferences(
    default_kb_name="",
    notifications_enabled=True,
    ingest_poll_interval_ms=5000,
)


@router.get("/users/me", response_model=UserOut)
async def get_me() -> UserOut:
    return _DEFAULT_USER


@router.patch("/users/me", response_model=UserOut)
async def patch_me(body: UserUpdate) -> UserOut:
    return _DEFAULT_USER


@router.get("/users/me/preferences", response_model=UserPreferences)
async def get_my_preferences() -> UserPreferences:
    return _DEFAULT_PREFERENCES


@router.patch("/users/me/preferences", response_model=UserPreferences)
async def patch_my_preferences(body: PreferencesUpdate) -> UserPreferences:
    return _DEFAULT_PREFERENCES
