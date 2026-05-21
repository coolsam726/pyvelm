from __future__ import annotations

from datetime import date as _date, datetime as _datetime
from typing import Any


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

    def __init__(
        self,
        string: str | None = None,
        required: bool = False,
        default: Any = None,
        column: str | None = None,
        compute: str | None = None,
        store: bool | None = None,
    ) -> None:
        self.string = string
        self.required = required
        self.default = default
        self.name: str | None = None
        self.model_name: str | None = None
        self._column_override = column
        self.column: str | None = None
        self.compute = compute
        # Computed fields are non-stored unless `store=True` is explicit.
        # When `compute` is None, fall back to the class-level `is_stored`
        # (True for scalars, False for One2many/Many2many).
        if compute is not None:
            self.is_stored = bool(store)
        self.depends_on = ()

    def bind(self, model_name: str, name: str) -> None:
        self.model_name = model_name
        self.name = name
        if self.string is None:
            self.string = name.replace("_", " ").capitalize()
        self.column = self._column_override or self._default_column(name)

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
    ):
        super().__init__(
            string=string,
            required=required,
            default=default,
            column=column,
            compute=compute,
            store=store,
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
    ``YYYY-MM-DD`` strings (HTML ``<input type=\"date\">``)."""

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
    ) -> None:
        super().__init__(string=string, required=required, default=None, column=column)
        self.comodel_name = comodel_name
        self.ondelete = ondelete.upper()

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


class One2many(Field):
    """Inverse of a Many2one. Not stored; resolves by querying the comodel.

    No SQL column, no DDL, no cache (Stage 2). Each access runs
    `SELECT id FROM <comodel> WHERE <inverse_column> = <parent_id>`.
    Aggressive caching needs an invalidation graph (deferred per CONTEXT.md).
    """

    is_stored = False

    def __init__(
        self,
        comodel_name: str,
        inverse_name: str,
        string: str | None = None,
    ) -> None:
        super().__init__(string=string, required=False, default=None)
        self.comodel_name = comodel_name
        self.inverse_name = inverse_name

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
        inverse = comodel_cls._fields[self.inverse_name]
        sql = (
            f'SELECT "id" FROM "{comodel_cls._table}" '
            f'WHERE "{inverse.column}" = %s ORDER BY "id"'
        )
        rows = record.env.conn.execute(sql, [rid]).fetchall()
        return comodel_cls(record.env, tuple(r[0] for r in rows))

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

    Reads re-query the junction (no cache yet, like One2many). Writes
    via create/write are full replacements: DELETE then INSERT.
    """

    is_stored = False  # no column on the owning table

    def __init__(
        self,
        comodel_name: str,
        string: str | None = None,
        relation: str | None = None,
        column1: str | None = None,
        column2: str | None = None,
    ) -> None:
        super().__init__(string=string, required=False, default=None)
        self.comodel_name = comodel_name
        self._relation_override = relation
        self._column1_override = column1
        self._column2_override = column2

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
        relation, col1, col2, _, _ = self.resolve_spec(
            type(record), record.env.registry
        )
        sql = (
            f'SELECT "{col2}" FROM "{relation}" WHERE "{col1}" = %s '
            f'ORDER BY "{col2}"'
        )
        rows = record.env.conn.execute(sql, [rid]).fetchall()
        return comodel_cls(record.env, tuple(r[0] for r in rows))

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
