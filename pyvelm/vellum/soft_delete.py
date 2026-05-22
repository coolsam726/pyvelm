"""Optional soft-delete mixin (``deleted_at`` or ``active`` column)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pyvelm import Boolean, Datetime


def uses_soft_deletes(model_cls) -> bool:
    return bool(getattr(model_cls, "_vellum_soft_deletes", False))


def soft_delete_column(model_cls) -> str | None:
    if not uses_soft_deletes(model_cls):
        return None
    return getattr(model_cls, "_soft_delete_column", "deleted_at")


def soft_delete_domain_leaves(
    model_cls, mode: str
) -> tuple[tuple[str, str, Any], ...]:
    """Extra domain leaves for ``default`` / ``only`` trashed modes."""
    if mode == "with" or not uses_soft_deletes(model_cls):
        return ()
    col = soft_delete_column(model_cls)
    if not col or col not in model_cls._fields:
        return ()
    field = model_cls._fields[col]
    if mode == "only":
        if isinstance(field, Boolean):
            return ((col, "=", False),)
        return ((col, "!=", None),)
    # default: hide trashed
    if isinstance(field, Boolean):
        return ((col, "=", True),)
    return ((col, "=", None),)


class SoftDeletes:
    """Mixin: ``delete()`` soft-deletes; ``force_delete()`` hard-deletes.

    List after ``BaseModel``::

        class Post(Vellum, BaseModel, SoftDeletes):
            _name = "blog.post"

    Default column is ``deleted_at`` (Datetime). Set
    ``_soft_delete_column = "active"`` to reuse a Boolean ``active`` field.
    """

    _vellum_soft_deletes = True
    _soft_delete_column = "deleted_at"
    deleted_at = Datetime(string="Deleted At")

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "_name", None):
            return
        col = getattr(cls, "_soft_delete_column", "deleted_at")
        if col not in cls._fields:
            if col == "deleted_at":
                field = Datetime(string="Deleted At")
                field.bind(cls._name, col)
                merged = dict(cls._fields)
                merged[col] = field
                cls._fields = merged
            else:
                raise TypeError(
                    f"{cls._name}: soft-delete column {col!r} is not a field "
                    f"on this model — declare it (e.g. active = Boolean())."
                )

    def _soft_delete_value(self):
        col = soft_delete_column(type(self))
        field = self._fields[col]
        if isinstance(field, Boolean):
            return False
        return datetime.now(timezone.utc)

    def _soft_restore_value(self):
        col = soft_delete_column(type(self))
        field = self._fields[col]
        if isinstance(field, Boolean):
            return True
        return None

    def delete(self) -> None:
        """Soft-delete (sets ``deleted_at`` or ``active=False``)."""
        if not self._ids:
            return
        col = soft_delete_column(self.__class__)
        self.write({col: self._soft_delete_value()})

    def restore(self) -> None:
        """Undo a soft delete."""
        if not self._ids:
            return
        col = soft_delete_column(self.__class__)
        self.write({col: self._soft_restore_value()})

    def force_delete(self) -> None:
        """Hard delete (real ``unlink`` via :class:`Vellum`)."""
        from .mixin import Vellum

        Vellum.unlink(self)
