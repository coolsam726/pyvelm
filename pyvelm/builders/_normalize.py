"""Shared normalization for view authoring builders."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyvelm.types import FieldRef, FieldRefLike

if TYPE_CHECKING:
    from .field import Field


def field_spec(field: FieldRefLike | Field | Any) -> FieldRef:
    from .field import Field

    if isinstance(field, Field):
        return field.to_dict()
    if isinstance(field, str):
        return {"name": field}
    return field


def field_specs(fields: list[FieldRefLike | Field | Any]) -> list[FieldRef]:
    return [field_spec(f) for f in fields]
