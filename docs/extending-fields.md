# Extending fields

This guide is for when you need a field type that doesn't ship with pyvelm —
a `Date`, a `Json`, a serialized blob, a Decimal with explicit precision,
etc. The mechanics for each are mostly the same; what changes is which hooks
you override and what cache shape you commit to.

This guide assumes you've read [architecture.md](architecture.md), in
particular the section on the cache contract and the field-descriptor
lifecycle.

## The Field contract

Every field must answer five questions:

| Question | Hook |
|----------|------|
| What's my SQL column type? | `sql_type` class attr, or override `column_ddl()` |
| Do I have a SQL column at all? | `is_stored` (class attr) |
| What's my SQL column *name*? | `column` (defaulted from `name` by `bind`) |
| How do I normalize values for binding & cache? | `to_sql_param(value)` |
| How do I shape values for Python consumers? | `to_python(value)` |

The default `Field.__get__` and `Field.__set__` cover most field types; you
only need to override them for relational fields or special semantics.

## Walkthrough: a `Date` field

Goal: store ISO-format date strings in a `date` column, accept either
`datetime.date` objects or ISO strings as input, return `datetime.date` from
reads.

```python
# pyvelm/fields_extra.py
from __future__ import annotations
from datetime import date

from pyvelm.fields import Field


class Date(Field):
    sql_type = "date"
    python_type = date

    def to_python(self, value):
        if value is None:
            return None
        if isinstance(value, date):
            return value
        # psycopg returns datetime.date for `date` columns, but if a caller
        # seeded the cache from a string we still want to round-trip.
        return date.fromisoformat(value)

    def to_sql_param(self, value):
        if value is None or value is False:
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value)
        raise TypeError(f"Date {self.name!r}: cannot bind {type(value).__name__}")
```

That's the whole field. The base `Field.__init__` already accepts `column=`,
`compute=`, `store=`, etc., so consumers can write `birthday = Date(required=True)`
or `birthday = Date(compute="_compute_birthday")` and everything works.

### Why these specific hooks

- **`sql_type = "date"`** is what `Field.column_ddl()` interpolates into the
  `CREATE TABLE` statement. If you need a non-trivial DDL (e.g.
  `NUMERIC(10,2)`), override `column_ddl()` entirely.
- **`to_sql_param`** is the single normalizer for *both* binding to psycopg
  *and* seeding the cache from a `create`/`write` call. If you skip cache
  seeding (return raw values), the next read returns whatever you passed in —
  not what's in the database. Always normalize.
- **`to_python`** runs on every descriptor read, so it must be cheap and
  idempotent (calling it twice on its own output should not change anything).

## Walkthrough: a stricter `Email` field

Goal: a `Char` that validates its input on write. No SQL changes; pure
input-side validation.

```python
import re
from pyvelm.fields import Char

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class Email(Char):
    def to_sql_param(self, value):
        if value is None or value is False:
            return None
        if not isinstance(value, str) or not _EMAIL_RE.match(value):
            raise ValueError(f"{self.name!r}: not a valid email: {value!r}")
        return value
```

That's it. Subclassing `Char` reuses every existing kwarg (`required`,
`default`, `size`, `column`, `compute`, `store`). The validation runs on
every `create`/`write` (and on cache seed, so the cache can never hold a
malformed value) but not on read — read values are already known to be
valid.

## When you need a relational field

Relational fields are the only ones that need to override `__get__` and
`__set__`. The contract is bigger:

1. **Tell the registry your comodel.** Store `self.comodel_name` so
   `_validate_relations` can confirm it exists.
2. **Choose your storage model.** If you have a real FK column, set
   `is_stored = True` (default) and let `column_ddl` emit it. If you're
   derived from somewhere else (One2many) or backed by a junction
   (Many2many), set `is_stored = False`.
3. **Wire init passes.** If you need FK constraints, contribute to
   `_setup_foreign_keys`. If you need a side table, add a
   `_setup_relation_tables`-style step.
4. **Override `__get__`** to return a recordset, not a raw value.
5. **Override `__set__`** to accept the polymorphic shapes (int, recordset,
   None, iterable thereof) and route through `record.write({attr: value})`
   so the dep graph notification still fires.
6. **Implement `to_sql_param`** to normalize whatever the user passed to
   the actual storage shape. For Many2one that's an int; for Many2many
   that raises (it has no column to bind to — `create`/`write` reach into
   `_apply_m2m` instead).

Look at `pyvelm/fields.py` for the three reference implementations.

## What you must not break

The cache invariant is the brittle one. If you accept polymorphic inputs
(int, recordset, None) but cache the raw input instead of the normalized
form, subsequent reads will return whatever was last assigned, which may
not match what `_read` would load from SQL. The rule:

> The value in `env.cache` is what `_read` would put there if we re-read
> from the database.

`create` and `write` already enforce this for you — they cache
`to_sql_param(value)`. If you're adding a new write path that bypasses
those (don't), apply the same normalization.

## Hooking into computed fields

Custom fields work with `compute=` and `@depends` for free, as long as
they're `is_stored`-correct and the `__set__` accepts whatever the compute
method produces. Test this once: write a compute that sets your field and
confirm the value survives a cache invalidation.

## Hooking into the domain compiler

Today's domain compiler emits SQL based on the column name and routes
values through `to_sql_param`. New scalar fields get correct domain support
for free. If you want custom operators (e.g. `~` for regex) you'd need to
extend `pyvelm/domain.py`'s operator table — a deliberate change since
adding operators is a language change, not a field change.

## Anti-patterns

- **Caching the unnormalized user value.** Already covered. The rule of
  thumb: if your `to_sql_param` is non-trivial, your cache must hold the
  result of `to_sql_param`, not the original.
- **Bypassing `__set__` to set instance attributes.** There are no instance
  attributes for field values — only cache entries. `self.x = y` inside a
  `BaseModel` subclass method on a real attribute name will shadow the
  descriptor on that one record and confuse everyone.
- **Calling `record.write(...)` from inside a non-computed field's
  `__get__`.** Reads should never mutate observable state. Compute methods
  are the exception, and they have their own gating flag.
- **Forgetting to validate at registry init.** If your field has cross-model
  invariants (Many2many's column-name collision check, for instance), put
  the check in `_validate_relations` so it fires once at boot, not at first
  use.
