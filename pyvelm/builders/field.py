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

    def readonly_when(self, domain: Sequence | Callable[..., bool]) -> Field:
        """Read-only when a domain matches or a callable returns true."""
        self._options["readonly_when"] = (
            list(domain) if isinstance(domain, (list, tuple)) else domain
        )
        return self

    def required(self, value: bool | Callable[..., bool] = True) -> Field:
        self._options["required"] = value
        return self

    def required_when(self, domain: Sequence | Callable[..., bool]) -> Field:
        """Required when a domain matches or a callable returns true."""
        self._options["required_when"] = (
            list(domain) if isinstance(domain, (list, tuple)) else domain
        )
        return self

    def visible(self, value: bool | Callable[..., bool] = True) -> Field:
        self._options["visible"] = value
        return self

    def visible_when(self, domain: Sequence | Callable[..., bool]) -> Field:
        """Visible when a domain matches or a callable returns true.

        Domains support nested paths (``company_id.currency_id.code``) on
        live forms — M2O ids from the submitted form are browsed via env.
        """
        self._options["visible_when"] = (
            list(domain) if isinstance(domain, (list, tuple)) else domain
        )
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
        """Re-render the form via HTMX when this field changes (Filament ``live()``).

        ``live()`` — on ``change``; ``live(debounce=200)`` — debounced;
        ``live(on_blur=True)`` — on blur only.
        """
        if on_blur:
            self._options["live"] = "blur"
        elif debounce is not None:
            self._options["live"] = debounce
        else:
            self._options["live"] = True
        return self

    def reactive(
        self,
        *,
        on_blur: bool = False,
        debounce: int | None = None,
    ) -> Field:
        """Alias for :meth:`live` (Filament / Livewire naming)."""
        return self.live(on_blur=on_blur, debounce=debounce)

    def depends_on(self, *fields: str) -> Field:
        """Declare sibling fields whose changes should refresh this field.

        Dependency sources without an explicit ``live()`` still trigger a
        form re-render so ``visible_when``, ``required_when``, and
        ``options_domain`` stay in sync.
        """
        self._options["depends_on"] = list(fields)
        return self

    def options_domain(self, domain_or_fn: Sequence | Callable[..., Sequence]) -> Field:
        """Filter Many2one / Many2many picker options (domain list or callable).

        **Static domain** — compiled to SQL for search; nested paths work::

            .options_domain([("company_id.currency_id.code", "=", "KES")])

        Sibling values: ``"company_id"`` or ``"$company_id"`` (also dotted
        ``$company_id.currency_id.code``).

        **Callable** — module-level named function (view arch serializes it).
        Receives ``(record, env, get)`` or ``(ctx,)`` and returns a domain list.
        Use when empty-state logic is easier in Python than in domain syntax.
        """
        self._options["options_domain"] = (
            list(domain_or_fn)
            if isinstance(domain_or_fn, (list, tuple))
            else domain_or_fn
        )
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
