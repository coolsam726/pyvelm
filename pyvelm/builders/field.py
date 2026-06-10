"""Fluent field spec builder (``Field.make('active').toggle()``)."""
from __future__ import annotations

from collections.abc import Callable, Sequence
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

    def readonly(self, value: bool | Callable[..., bool] = True) -> Field:
        self._options["readonly"] = value
        return self

    def readonly_when(self, domain: Sequence) -> Field:
        self._options["readonly_when"] = list(domain)
        return self

    def required(self, value: bool | Callable[..., bool] = True) -> Field:
        self._options["required"] = value
        return self

    def required_when(self, domain: Sequence) -> Field:
        self._options["required_when"] = list(domain)
        return self

    def visible(self, value: bool | Callable[..., bool] = True) -> Field:
        self._options["visible"] = value
        return self

    def visible_when(self, domain: Sequence) -> Field:
        self._options["visible_when"] = list(domain)
        return self

    def hidden(self, value: bool | Callable[..., bool] = True) -> Field:
        self._options["hidden"] = value
        return self

    def visible_js(self, expr: str) -> Field:
        self._options["visible_js"] = expr
        return self

    def live(
        self,
        *,
        on_blur: bool = False,
        debounce: int | None = None,
    ) -> Field:
        if on_blur:
            self._options["live"] = "blur"
        elif debounce is not None:
            self._options["live"] = debounce
        else:
            self._options["live"] = True
        return self

    def depends_on(self, *fields: str) -> Field:
        self._options["depends_on"] = list(fields)
        return self

    def options_domain(self, domain_or_fn: Sequence | Callable[..., Sequence]) -> Field:
        self._options["options_domain"] = domain_or_fn
        return self

    def default(self, fn: Callable[..., Any]) -> Field:
        self._options["default"] = fn
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
