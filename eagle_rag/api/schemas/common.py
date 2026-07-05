"""Common API models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DeletedResponse(BaseModel):
    deleted: bool = Field(description="Whether the delete succeeded")


class OkResponse(BaseModel):
    ok: bool = Field(description="Whether the operation succeeded")


class RootResponse(BaseModel):
    app: str
    version: str
    docs: str


class PaginatedMeta(BaseModel):
    limit: int = Field(ge=1, description="Page size")
    offset: int = Field(ge=0, description="Page offset")
