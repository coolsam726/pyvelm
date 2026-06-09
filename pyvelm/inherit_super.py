"""Odoo-style ``super()`` for ``_inherit`` model stacks.

Python's built-in :func:`super` already walks the merged model MRO when
extensions subclass the registry class.  This module adds:

* ``_inherit_chain`` metadata on each model class (root → latest extension).
* :meth:`~pyvelm.model.BaseModel.super` — explicit recordset super proxy that
  auto-detects the calling class when ``origin`` is omitted.
* :meth:`~pyvelm.registry.Registry.inherit_chain` for introspection.
"""
from __future__ import annotations

from typing import Any


def bind_inherit_chain(cls: type, parent: type | None) -> None:
    """Attach ``_inherit_chain`` on *cls* (root model or extension)."""
    if parent is None:
        cls._inherit_chain = (cls,)  # type: ignore[attr-defined]
        return
    parent_chain = getattr(parent, "_inherit_chain", (parent,))
    cls._inherit_chain = parent_chain + (cls,)  # type: ignore[attr-defined]


def defining_class(record_cls: type, method_name: str) -> type:
    """Return the class in *record_cls*'s MRO that defines *method_name*."""
    for cls in record_cls.__mro__:
        if method_name in cls.__dict__:
            return cls
    return record_cls


def defining_class_for_frame(record_cls: type, frame) -> type:
    """Return the class whose method body is currently executing in *frame*."""
    code = frame.f_code
    for cls in record_cls.__mro__:
        func = cls.__dict__.get(code.co_name)
        if func is not None and getattr(func, "__code__", None) is code:
            return cls
    return defining_class(record_cls, code.co_name)


class InheritSuper:
    """Proxy to call the next implementation in a model's ``_inherit`` MRO."""

    __slots__ = ("_origin", "_record")

    def __init__(self, record, origin_cls: type) -> None:
        self._record = record
        self._origin = origin_cls

    def __getattr__(self, name: str) -> Any:
        # Delegate to Python's super — the MRO is already correct after
        # MetaModel._build_extension merges extension classes.
        return getattr(super(self._origin, self._record), name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError(
            "Call a method on the super proxy, e.g. self.super().write(vals)"
        )


def make_super_proxy(record, origin_cls: type) -> InheritSuper:
    """Build an :class:`InheritSuper` for *record* at *origin_cls*."""
    return InheritSuper(record, origin_cls)
