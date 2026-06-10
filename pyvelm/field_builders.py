"""Fluent builders for ORM field declarations on model classes.

Use constructor kwargs (existing) or chain after a zero-arg call::

    name = Char(required=True)
    name = Char().required().string("Name").tracking()

``Many2one("res.partner").required()`` and ``One2many("a", "b").list_view(...)``
also chain; the metaclass materializes builders when the model class is created.

View arch field specs use ``pyvelm.builders.Field`` — not this module.
"""
from __future__ import annotations

from typing import Any

from .fields import Field


class OrmFieldBuilder:
    """Deferred construction of a :class:`~pyvelm.fields.Field` subclass."""

    __slots__ = ("_field_cls", "_args", "_kwargs")

    def __init__(
        self,
        field_cls: type[Field],
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        self._field_cls = field_cls
        self._args = args
        self._kwargs = dict(kwargs or {})

    def build(self) -> Field:
        """Materialize without re-entering fluent ``__new__``."""
        field = object.__new__(self._field_cls)
        self._field_cls.__init__(field, *self._args, **self._kwargs)
        return field

    def _set(self, key: str, value: Any) -> OrmFieldBuilder:
        self._kwargs[key] = value
        return self

    # --- shared scalar / relation kwargs (match ``Field.__init__``) ---

    def string(self, value: str) -> OrmFieldBuilder:
        return self._set("string", value)

    def required(self, value: bool = True) -> OrmFieldBuilder:
        return self._set("required", value)

    def default(self, value: Any) -> OrmFieldBuilder:
        return self._set("default", value)

    def column(self, value: str) -> OrmFieldBuilder:
        return self._set("column", value)

    def compute(self, method: str) -> OrmFieldBuilder:
        return self._set("compute", method)

    def store(self, value: bool = True) -> OrmFieldBuilder:
        return self._set("store", value)

    def related(self, path: str) -> OrmFieldBuilder:
        return self._set("related", path)

    def readonly(self, value: bool = True) -> OrmFieldBuilder:
        return self._set("readonly", value)

    def tracking(self, value: bool = True) -> OrmFieldBuilder:
        return self._set("tracking", value)

    # --- ``Char`` / ``Text`` ---

    def size(self, value: int) -> OrmFieldBuilder:
        return self._set("size", value)

    def choices(self, value: list) -> OrmFieldBuilder:
        return self._set("choices", value)

    # --- ``Code`` ---

    def language(self, value: str) -> OrmFieldBuilder:
        return self._set("language", value)

    # --- ``Monetary`` ---

    def currency_field(self, value: str) -> OrmFieldBuilder:
        return self._set("currency_field", value)

    # --- ``Many2one`` ---

    def comodel(self, name: str) -> OrmFieldBuilder:
        self._args = (name,)
        return self

    def ondelete(self, policy: str) -> OrmFieldBuilder:
        return self._set("ondelete", policy)

    # --- ``One2many`` ---

    def inverse(self, inverse_name: str) -> OrmFieldBuilder:
        if self._args:
            self._args = (self._args[0], inverse_name)
        else:
            self._kwargs["inverse_name"] = inverse_name
        return self

    def list_view(self, ref: str | tuple[str, str]) -> OrmFieldBuilder:
        return self._set("list_view", ref)

    def form_view(self, ref: str | tuple[str, str]) -> OrmFieldBuilder:
        return self._set("form_view", ref)

    # --- ``Many2many`` ---

    def relation(self, table: str) -> OrmFieldBuilder:
        return self._set("relation", table)

    def column1(self, value: str) -> OrmFieldBuilder:
        return self._set("column1", value)

    def column2(self, value: str) -> OrmFieldBuilder:
        return self._set("column2", value)


def materialize_field(value: Any) -> Any:
    """Return a concrete :class:`Field` when *value* is a builder."""
    if isinstance(value, OrmFieldBuilder):
        return value.build()
    return value


def materialize_namespace_fields(namespace: dict) -> None:
    """Replace fluent builders in a class namespace with concrete fields."""
    for attr_name, attr_value in list(namespace.items()):
        if isinstance(attr_value, OrmFieldBuilder):
            namespace[attr_name] = attr_value.build()


def field_new(cls: type[Field], *args: Any, **kwargs: Any) -> Field | OrmFieldBuilder:
    """``Field`` subclass ``__new__``: kwargs → instance; else → builder."""
    if kwargs:
        instance: Field = super(Field, cls).__new__(cls)
        return instance
    if not args:
        return OrmFieldBuilder(cls)
    return OrmFieldBuilder(cls, args=args)


__all__ = ["OrmFieldBuilder", "field_new", "materialize_field"]
