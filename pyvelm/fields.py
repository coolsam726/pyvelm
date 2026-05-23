from __future__ import annotations

from datetime import date as _date, datetime as _datetime, time as _time
from typing import Any


def _title_words(snake: str) -> str:
    """``country`` → ``Country``, ``partner_code`` → ``Partner Code``."""
    return " ".join(part.capitalize() for part in snake.split("_") if part)


_IRREGULAR_PLURALS = {
    "child": "children",
    "person": "people",
    "man": "men",
    "woman": "women",
}


def _pluralize_word(word: str) -> str:
    """Light English plural for auto labels (``tag`` → ``Tags``)."""
    if not word:
        return word
    lower = word.lower()
    if lower in _IRREGULAR_PLURALS:
        repl = _IRREGULAR_PLURALS[lower]
        return repl.capitalize() if word[0].isupper() else repl
    if lower.endswith("s"):
        return word
    if lower.endswith("y") and len(lower) > 1 and lower[-2] not in "aeiou":
        return word[:-1] + "ies"
    if lower.endswith(("ch", "sh", "x")):
        return word + "es"
    return word + "s"


def _pluralize_label(label: str) -> str:
    """Pluralize the last word of a multi-word label."""
    if not label:
        return label
    words = label.split()
    words[-1] = _pluralize_word(words[-1])
    return " ".join(words)


class Field:
    """Descriptor that routes attribute access through env.cache.

    A Field is declared on a model class. At class-creation time the
    metaclass calls bind() so the field knows its name and owning model.
    Reads route through the cache (loading from SQL on miss); writes
    update the cache and persist immediately (Stage 1 has no transaction
    batching — see CONTEXT.md).
    """

    sql_type: str = "text"
    python_type: type = object
    is_stored: bool = True  # False = no SQL column, value derived on demand
    compute: str | None = None  # name of compute method on the model
    depends_on: tuple[str, ...] = ()  # set by metaclass from @depends
    # When True, the field is excluded from default `.read()` field sets
    # and from JSON serialization. Programmatic access via the descriptor
    # (``user.password``) still works — the flag only affects bulk-shape
    # APIs that would otherwise hand the value to a renderer or client.
    # Used by ``Password`` to keep bcrypt hashes from ever leaving the
    # process.
    private: bool = False

    def __init__(
        self,
        string: str | None = None,
        required: bool = False,
        default: Any = None,
        column: str | None = None,
        compute: str | None = None,
        store: bool | None = None,
        related: str | None = None,
        readonly: bool = False,
    ) -> None:
        self.string = string
        self.required = required
        self.default = default
        self.name: str | None = None
        self.model_name: str | None = None
        self._column_override = column
        self.column: str | None = None
        self.compute = compute
        self.related = related
        self.readonly = bool(readonly)
        # Computed fields are non-stored unless `store=True` is explicit.
        # When `compute` is None, fall back to the class-level `is_stored`
        # (True for scalars, False for One2many/Many2many).
        if compute is not None:
            self.is_stored = bool(store)
        self.depends_on = ()
        self._related_path = None

    def bind(self, model_name: str, name: str) -> None:
        self.model_name = model_name
        self.name = name
        if self.string is None:
            self.string = self._default_string(name)
        if self.related:
            self.is_stored = False
            self.column = None
        else:
            self.column = self._column_override or self._default_column(name)

    def _default_string(self, name: str) -> str:
        return _title_words(name)

    def _default_column(self, name: str) -> str:
        return name

    def default_value(self) -> Any:
        return self.default

    def to_python(self, value: Any) -> Any:
        return value

    def to_sql_param(self, value: Any) -> Any:
        return value

    def column_ddl(self) -> str:
        null = "NOT NULL" if self.required else ""
        return f'"{self.column}" {self.sql_type} {null}'.strip()

    def __get__(self, record, owner):
        if record is None:
            return self
        if self.related:
            return self._get_related(record)
        if not record._ids:
            return self.default_value()
        record.ensure_one()
        rid = record._ids[0]
        cache = record.env.cache
        if not cache.contains(record._name, rid, self.name):
            # Non-stored compute: run the method on cache miss.
            # Stored compute or plain field: read from SQL (the column holds it).
            if self.compute and not self.is_stored:
                record.env.compute_field(record, self)
            else:
                record._read([self.name])
        return self.to_python(cache.get(record._name, rid, self.name))

    def __set__(self, record, value) -> None:
        if not record._ids:
            return
        if self.readonly:
            raise ValueError(
                f"{record._name}.{self.name} is readonly and cannot be written."
            )
        if self.related:
            self._set_related(record, value)
            return
        if self.compute:
            if not getattr(record.env, "_in_compute", False):
                raise ValueError(
                    f"{record._name}.{self.name} is computed; "
                    f"assign through its dependencies instead."
                )
            # Inside a compute pass: cache only. For stored computes, the
            # runner flushes to SQL after the method returns.
            for rid in record._ids:
                record.env.cache.set(
                    record._name, rid, self.name, self.to_sql_param(value)
                )
            return
        record.write({self.name: value})

    def _get_related(self, record):
        """Read through ``self.related`` (e.g. ``company_id.currency_id``)."""
        if not record._ids:
            return self._related_empty(record)
        record.ensure_one()
        rid = record._ids[0]
        cache = record.env.cache
        if cache.contains(record._name, rid, self.name):
            cached = cache.get(record._name, rid, self.name)
            return self._related_from_cache(record, cached)
        value = self._read_related_value(record)
        cache.set(record._name, rid, self.name, self._related_cache_value(value))
        return value

    def _set_related(self, record, value) -> None:
        """Write through ``self.related`` onto the leaf field."""
        tokens = self.related.split(".")
        for rid in record._ids:
            rec = record.__class__(record.env, (rid,))
            target = rec
            for attr in tokens[:-1]:
                target = getattr(target, attr)
                if hasattr(target, "_ids") and not target._ids:
                    raise ValueError(
                        f"Cannot set {record._name}.{self.name}: "
                        f"no related record at {attr!r}"
                    )
                if hasattr(target, "_ids"):
                    target.ensure_one()
            leaf = tokens[-1]
            leaf_field = type(target)._fields[leaf]
            if leaf_field.readonly:
                raise ValueError(
                    f"Cannot set {record._name}.{self.name}: "
                    f"leaf field {target._name}.{leaf} is readonly"
                )
            setattr(target, leaf, value)
            record.env.cache.invalidate(
                model_name=record._name, ids=[rid], fields=[self.name]
            )

    def _read_related_value(self, record):
        tokens = self.related.split(".")
        target = record
        for attr in tokens[:-1]:
            target = getattr(target, attr)
            if hasattr(target, "_ids") and not target._ids:
                return self._related_empty(record)
            if hasattr(target, "_ids"):
                target.ensure_one()
        return getattr(target, tokens[-1])

    def _related_empty(self, record):
        if isinstance(self, Many2one):
            return record.env.registry[self.comodel_name](record.env, ())
        if isinstance(self, One2many):
            return record.env.registry[self.comodel_name](record.env, ())
        if isinstance(self, Many2many):
            return record.env.registry[self.comodel_name](record.env, ())
        return self.default_value()

    def _related_cache_value(self, value):
        """Normalize a related value for the source model's cache slot."""
        if isinstance(self, Many2one):
            if value is None or value is False:
                return None
            if hasattr(value, "_ids"):
                return value._ids[0] if value._ids else None
            return int(value)
        if isinstance(self, (One2many, Many2many)):
            return None
        if hasattr(value, "_ids"):
            return None
        return self.to_sql_param(value)

    def _related_from_cache(self, record, cached):
        if isinstance(self, Many2one):
            Model = record.env.registry[self.comodel_name]
            return Model(record.env, ()) if cached is None else Model(record.env, (cached,))
        return self.to_python(cached)


class Char(Field):
    sql_type = "text"
    python_type = str

    def __init__(
        self,
        string=None,
        required=False,
        default=None,
        column=None,
        compute=None,
        store=None,
        size: int | None = None,
        choices: list | None = None,
        related: str | None = None,
        readonly: bool = False,
    ):
        super().__init__(
            string=string,
            required=required,
            default=default,
            column=column,
            compute=compute,
            store=store,
            related=related,
            readonly=readonly,
        )
        self.size = size
        # `choices` constrains the value to a small enumeration. Items
        # are either plain strings (label == value) or ``(value, label)``
        # tuples. When set, edit widgets render a ``<select>`` instead
        # of a text input. No DB-level CHECK is added — the constraint
        # is UI-only by design (operators may still write programmatic
        # values that bypass the form layer).
        self.choices: list[tuple[str, str]] | None = (
            [(c, c) if isinstance(c, str) else (c[0], c[1]) for c in choices]
            if choices
            else None
        )

    def to_python(self, value):
        return None if value is None else str(value)


class Text(Char):
    pass


class Integer(Field):
    sql_type = "integer"
    python_type = int

    def to_python(self, value):
        return None if value is None else int(value)


class Float(Field):
    sql_type = "double precision"
    python_type = float

    def to_python(self, value):
        return None if value is None else float(value)


class Monetary(Float):
    """A Float that carries a sibling-field reference to its currency.

    ``currency_field`` names a Many2one(``res.currency``) on the same
    record. Widgets read it to format the amount (symbol + rounding);
    the model layer treats Monetary identically to Float — the value
    is just a double in the column.

    `round_with(amount, currency)` snaps an amount to the currency's
    rounding step using banker's rounding via Python's built-in
    ``round()``. Use it from application code when you want stored
    values normalised; the field itself does not auto-round on write
    (consistent with Float — explicit is better than magic)."""

    def __init__(self, *args, currency_field: str = "currency_id", **kwargs):
        super().__init__(*args, **kwargs)
        self.currency_field = currency_field

    @staticmethod
    def round_with(amount: float, currency) -> float:
        """Round ``amount`` to ``currency.rounding``.

        Tolerates an empty-recordset currency (no rounding info) by
        returning the amount unchanged. Uses ``decimal.Decimal`` to
        avoid the binary-float ``round(12.345 / 0.01) * 0.01 ==
        12.34`` trap."""
        if amount is None:
            return None
        if not currency:
            return float(amount)
        step = getattr(currency, "rounding", None) or 0.01
        if step <= 0:
            return float(amount)
        from decimal import Decimal, ROUND_HALF_UP
        d_amount = Decimal(str(amount))
        d_step = Decimal(str(step))
        quotient = (d_amount / d_step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return float(quotient * d_step)


class Datetime(Field):
    """A naive (no-tzinfo) datetime, stored as ``timestamp``.

    Accepts datetime, ISO 8601 strings, or HTML ``datetime-local``
    submissions (``YYYY-MM-DDTHH:MM``) on write."""

    sql_type = "timestamp"
    python_type = _datetime

    def column_ddl(self) -> str:
        null = "" if self.required else " NULL"
        return f'"{self.column}" timestamp{null}'

    def to_sql_param(self, value):
        if value is None or value is False or value == "":
            return None
        if isinstance(value, _datetime):
            return value
        if isinstance(value, _date):
            return _datetime(value.year, value.month, value.day)
        return _datetime.fromisoformat(str(value))

    def to_python(self, value):
        return value  # psycopg returns datetime already


class Date(Field):
    """A calendar date, stored as ``date``.

    Accepts ``date``, ``datetime`` (truncated to day), or
    ``YYYY-MM-DD`` strings (Flowbite datepicker / ISO)."""

    sql_type = "date"
    python_type = _date

    def column_ddl(self) -> str:
        null = "" if self.required else " NULL"
        return f'"{self.column}" date{null}'

    def to_sql_param(self, value):
        if value is None or value is False or value == "":
            return None
        if isinstance(value, _datetime):
            return value.date()
        if isinstance(value, _date):
            return value
        return _date.fromisoformat(str(value))

    def to_python(self, value):
        return value


class Time(Field):
    """Time of day, stored as ``time without time zone``.

    Accepts ``time``, ``datetime`` (truncated), or ``HH:MM`` strings."""

    sql_type = "time"
    python_type = _time

    def column_ddl(self) -> str:
        null = "" if self.required else " NULL"
        return f'"{self.column}" time{null}'

    def to_sql_param(self, value):
        if value is None or value is False or value == "":
            return None
        if isinstance(value, _time):
            return value
        if isinstance(value, _datetime):
            return value.time()
        text = str(value).strip()
        if len(text) == 5 and text[2] == ":":
            return _time.fromisoformat(text)
        return _time.fromisoformat(text)

    def to_python(self, value):
        return value


class Boolean(Field):
    sql_type = "boolean"
    python_type = bool

    def to_python(self, value):
        return None if value is None else bool(value)


class Many2one(Field):
    """Stores an int FK column; exposes a singleton (or empty) recordset.

    The cache holds the raw int (or None). The descriptor wraps reads in
    `env[comodel_name].browse(id)`, and writes accept an int, a recordset,
    or None/False. Traversal (`partner.country_id.name`) works because the
    wrapped recordset is just another view over env.cache.
    """

    sql_type = "integer"

    def __init__(
        self,
        comodel_name: str,
        string: str | None = None,
        required: bool = False,
        ondelete: str = "SET NULL",
        column: str | None = None,
        related: str | None = None,
        readonly: bool = False,
    ) -> None:
        super().__init__(
            string=string,
            required=required,
            default=None,
            column=column,
            related=related,
            readonly=readonly,
        )
        self.comodel_name = comodel_name
        self.ondelete = ondelete.upper()

    def _default_string(self, name: str) -> str:
        if name.endswith("_id") and len(name) > 3:
            return _title_words(name[:-3])
        return super()._default_string(name)

    def to_sql_param(self, value):
        if value is None or value is False:
            return None
        if hasattr(value, "_ids"):
            if not value._ids:
                return None
            if len(value._ids) > 1:
                raise ValueError(
                    f"Cannot assign multi-record recordset to Many2one {self.name!r}"
                )
            return value._ids[0]
        return int(value)

    def __get__(self, record, owner):
        if record is None:
            return self
        if self.related:
            return super().__get__(record, owner)
        comodel_cls = record.env.registry[self.comodel_name]
        if not record._ids:
            return comodel_cls(record.env, ())
        record.ensure_one()
        rid = record._ids[0]
        cache = record.env.cache
        if not cache.contains(record._name, rid, self.name):
            record._read([self.name])
        raw = cache.get(record._name, rid, self.name)
        if raw is None:
            return comodel_cls(record.env, ())
        return comodel_cls(record.env, (raw,))


def _collection_ids_from_cache(cache, model_name: str, rid: int, field_name: str):
    """Return a tuple of ids if this O2M/M2M field is cached, else ``None``."""
    if not cache.contains(model_name, rid, field_name):
        return None
    cached = cache.get(model_name, rid, field_name)
    if not isinstance(cached, tuple):
        return None
    return cached


def _store_collection_cache(
    cache, model_name: str, rid: int, field_name: str, ids: tuple[int, ...]
) -> None:
    cache.set(model_name, rid, field_name, ids)


class One2many(Field):
    """Inverse of a Many2one. Not stored; resolves by querying the comodel.

    Reads consult ``env.cache`` when a ``tuple`` of child ids is present
    (populated by a prior read or eager prefetch). Otherwise queries SQL
    and stores the result in the cache for the rest of the request.
    """

    is_stored = False

    def __init__(
        self,
        comodel_name: str,
        inverse_name: str,
        string: str | None = None,
        related: str | None = None,
        readonly: bool = False,
    ) -> None:
        super().__init__(
            string=string,
            required=False,
            default=None,
            related=related,
            readonly=readonly,
        )
        self.comodel_name = comodel_name
        self.inverse_name = inverse_name

    def _default_string(self, name: str) -> str:
        if name.endswith("_ids") and len(name) > 4:
            return _pluralize_label(_title_words(name[:-4]))
        return super()._default_string(name)

    def column_ddl(self) -> str:
        raise RuntimeError("One2many has no column")

    def to_sql_param(self, value):
        raise NotImplementedError(
            f"Cannot assign to One2many {self.name!r} directly; "
            f"set the inverse Many2one ({self.comodel_name}.{self.inverse_name})."
        )

    def __get__(self, record, owner):
        if record is None:
            return self
        comodel_cls = record.env.registry[self.comodel_name]
        if not record._ids:
            return comodel_cls(record.env, ())
        record.ensure_one()
        rid = record._ids[0]
        cache = record.env.cache
        cached_ids = _collection_ids_from_cache(
            cache, record._name, rid, self.name
        )
        if cached_ids is not None:
            return comodel_cls(record.env, cached_ids)
        inverse = comodel_cls._fields[self.inverse_name]
        sql = (
            f'SELECT "id" FROM "{comodel_cls._table}" '
            f'WHERE "{inverse.column}" = %s ORDER BY "id"'
        )
        rows = record.env.conn.execute(sql, [rid]).fetchall()
        child_ids = tuple(r[0] for r in rows)
        _store_collection_cache(cache, record._name, rid, self.name, child_ids)
        return comodel_cls(record.env, child_ids)

    def __set__(self, record, value) -> None:
        raise NotImplementedError(
            f"Cannot assign to One2many {self.name!r} directly; "
            f"set the inverse Many2one ({self.comodel_name}.{self.inverse_name})."
        )


class Many2many(Field):
    """N:N relation backed by an auto-created junction table.

    Default `relation` is the two table names joined alphabetically with
    `_rel`, so both sides of a symmetric pair compute the same name and
    only one CREATE TABLE is emitted. Self-referential M2M must supply
    `relation`, `column1`, `column2` explicitly.

    Reads use the same tuple-of-ids cache convention as :class:`One2many`.
    Writes via create/write are full replacements: DELETE then INSERT.
    """

    is_stored = False  # no column on the owning table

    def __init__(
        self,
        comodel_name: str,
        string: str | None = None,
        relation: str | None = None,
        column1: str | None = None,
        column2: str | None = None,
        related: str | None = None,
        readonly: bool = False,
    ) -> None:
        super().__init__(
            string=string,
            required=False,
            default=None,
            related=related,
            readonly=readonly,
        )
        self.comodel_name = comodel_name
        self._relation_override = relation
        self._column1_override = column1
        self._column2_override = column2

    def _default_string(self, name: str) -> str:
        if name.endswith("_ids") and len(name) > 4:
            return _pluralize_label(_title_words(name[:-4]))
        return super()._default_string(name)

    def resolve_spec(self, model_cls, registry) -> tuple[str, str, str, str, str]:
        """Return (relation, col1, col2, this_table, target_table)."""
        target = registry[self.comodel_name]
        this_table = model_cls._table
        other_table = target._table

        if self.comodel_name == model_cls._name:
            # Self-M2M: defaults would collide. Require explicit config.
            if not (self._relation_override and self._column1_override and self._column2_override):
                raise ValueError(
                    f"{model_cls._name}.{self.name}: self-referential Many2many "
                    f"requires explicit relation, column1, column2."
                )
            return (
                self._relation_override,
                self._column1_override,
                self._column2_override,
                this_table,
                other_table,
            )

        relation = self._relation_override or "_".join(
            sorted([this_table, other_table])
        ) + "_rel"
        col1 = self._column1_override or f"{this_table}_id"
        col2 = self._column2_override or f"{other_table}_id"
        return relation, col1, col2, this_table, other_table

    def to_sql_param(self, value):
        raise NotImplementedError(
            f"Many2many {self.name!r} is not a scalar; pass a list of ids "
            f"or a recordset via create/write."
        )

    def __get__(self, record, owner):
        if record is None:
            return self
        comodel_cls = record.env.registry[self.comodel_name]
        if not record._ids:
            return comodel_cls(record.env, ())
        record.ensure_one()
        rid = record._ids[0]
        cache = record.env.cache
        cached_ids = _collection_ids_from_cache(
            cache, record._name, rid, self.name
        )
        if cached_ids is not None:
            return comodel_cls(record.env, cached_ids)
        relation, col1, col2, _, _ = self.resolve_spec(
            type(record), record.env.registry
        )
        sql = (
            f'SELECT "{col2}" FROM "{relation}" WHERE "{col1}" = %s '
            f'ORDER BY "{col2}"'
        )
        rows = record.env.conn.execute(sql, [rid]).fetchall()
        target_ids = tuple(r[0] for r in rows)
        _store_collection_cache(cache, record._name, rid, self.name, target_ids)
        return comodel_cls(record.env, target_ids)

    def __set__(self, record, value) -> None:
        if not record._ids:
            return
        record.write({self.name: value})

    @staticmethod
    def normalize_ids(value) -> list[int]:
        """Accept None/False, an int, a recordset, or an iterable of either."""
        if value is None or value is False:
            return []
        if hasattr(value, "_ids"):
            return list(value._ids)
        if isinstance(value, int):
            return [value]
        out: list[int] = []
        for v in value:
            if v is None or v is False:
                continue
            if hasattr(v, "_ids"):
                if not v._ids:
                    continue
                if len(v._ids) > 1:
                    raise ValueError(
                        "Many2many value list cannot contain multi-record recordsets"
                    )
                out.append(v._ids[0])
            else:
                out.append(int(v))
        return out


def finalize_related_field(model_cls, field: Field) -> None:
    """Validate and wire a ``related=`` field after ``bind()``.

    Related fields mirror a dotted path (``company_id.currency_id``):
    non-stored, no SQL column, cache-invalidated when the path changes.
    Writes propagate to the leaf field on the related record.
    """
    from .paths import parse_path
    from .registry import active_registry

    if not field.related:
        return
    if field.compute:
        raise ValueError(
            f"{model_cls._name}.{field.name}: cannot combine related and compute"
        )
    reg = active_registry()
    path = parse_path(model_cls, field.related, reg)
    if not path.is_m2o_only():
        raise ValueError(
            f"{model_cls._name}.{field.name}: related path {field.related!r} "
            "must use only Many2one hops (One2many/Many2many not supported yet)"
        )
    field.depends_on = (field.related,)
    field.is_stored = False
    field.column = None
    field._related_path = path
    leaf_cls = reg[path.leaf_model]
    leaf_field = leaf_cls._fields[path.leaf_attr]
    if not isinstance(field, type(leaf_field)) and not isinstance(
        leaf_field, type(field)
    ):
        raise ValueError(
            f"{model_cls._name}.{field.name}: related leaf "
            f"{path.leaf_model}.{path.leaf_attr} is {type(leaf_field).__name__}, "
            f"expected {type(field).__name__}"
        )
    if isinstance(field, Many2one) and isinstance(leaf_field, Many2one):
        if field.comodel_name != leaf_field.comodel_name:
            raise ValueError(
                f"{model_cls._name}.{field.name}: comodel {field.comodel_name!r} "
                f"does not match related leaf comodel {leaf_field.comodel_name!r}"
            )


def spec_readonly(spec: dict, field: Field) -> bool:
    """View-level ``readonly`` on the spec wins; else the field flag."""
    if spec.get("readonly") is not None:
        return bool(spec["readonly"])
    return bool(getattr(field, "readonly", False))
