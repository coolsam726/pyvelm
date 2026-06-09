"""Fluent field spec builder (``Field.make('active').toggle()``)."""
from __future__ import annotations

from typing import Any

from pyvelm.types import FieldRef, WidgetHint


class Field:
    """Build a single field entry inside list / form / kanban archs."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._options: dict[str, Any] = {}

    @classmethod
    def make(cls, name: str) -> Field:
        return cls(name)

    def widget(self, widget: WidgetHint) -> Field:
        self._options["widget"] = widget
        return self

    def toggle(self) -> Field:
        return self.widget("toggle")

    def label(self, label: str) -> Field:
        self._options["label"] = label
        return self

    def readonly(self, readonly: bool = True) -> Field:
        self._options["readonly"] = readonly
        return self

    def required(self, required: bool = True) -> Field:
        self._options["required"] = required
        return self

    def colspan(self, colspan: int | str) -> Field:
        self._options["colspan"] = colspan  # type: ignore[typeddict-item]
        return self

    def set(self, **extra: Any) -> Field:
        self._options.update(extra)
        return self

    def to_dict(self) -> FieldRef:
        from ._normalize import field_specs

        opts = dict(self._options)
        if isinstance(opts.get("columns"), list):
            opts["columns"] = field_specs(opts["columns"])
        return {"name": self._name, **opts}  # type: ignore[typeddict-item]
