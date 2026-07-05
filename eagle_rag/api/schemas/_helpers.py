"""Schema helpers: dict → Pydantic and datetime serialization."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def iso_datetime(value: Any) -> str | None:
    """Convert ``datetime`` to an ISO string; return as-is if already a string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def model_from_row(model: type[T], row: dict[str, Any]) -> T:
    """Build a response model from a store row dict (auto-serializes datetime fields)."""
    data = dict(row)
    for key, val in list(data.items()):
        if isinstance(val, datetime):
            data[key] = val.isoformat()
    return model.model_validate(data)
