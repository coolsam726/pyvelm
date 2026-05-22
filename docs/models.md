# Declaring models

A pyvelm model is a Python class. You subclass `BaseModel`, set a
dotted `_name`, and declare fields as class attributes. The framework
takes care of the schema (a Postgres table named `<dotted_to_snake>`),
the SQL plumbing, and the recordset machinery.

## A first model

```python
from pyvelm import BaseModel, Char, Integer, Boolean, Many2one


class Partner(BaseModel):
    _name = "res.partner"

    name = Char(required=True, string="Name")
    age = Integer()
    active = Boolean(default=True)
    country_id = Many2one("res.country", ondelete="SET NULL")
```

The class lives inside a module's `models/` package; the loader picks
it up when the module installs. See [Modules](modules.md) for the
packaging story.

Once loaded, you operate on records through the `env`:

```python
# create
alice = env["res.partner"].create({"name": "Alice", "age": 30})

# read — field access through the descriptor
print(alice.name, alice.age)

# write
alice.write({"age": 31})

# search — returns a recordset
adults = env["res.partner"].search([("age", ">=", 18)])
for r in adults:
    print(r.name)
```

For optional Eloquent-style queries (`env.query`, scopes, eager load,
soft deletes), see **[Vellum](vellum.md)**.

Collection search paths support universal quantification with a fourth
leaf element: `("tag_ids.name", "!=", "VIP", {"all": True})` — every
related row must match (see [Architecture](architecture.md#domain-compiler)).

Recordsets behave like Python collections — iteration, `len()`,
`in`, slicing — and they're always tied to a specific `env`.

## Built-in field types

| Field | Stores | Notes |
|---|---|---|
| `Char(size=…, required=, default=, string=)` | `text` | Variable-length string |
| `Text` | `text` | Like `Char` but no size hint |
| `Integer(required=, default=)` | `integer` | |
| `Float(required=, default=)` | `double precision` | |
| `Boolean(default=)` | `boolean` | |
| `Many2one(comodel, ondelete=)` | `integer` (FK) | Relationship to one record |
| `One2many(comodel, inverse_name=)` | — | Reverse side of a Many2one |
| `Many2many(comodel, relation=)` | junction table | Symmetric many-to-many |

Common kwargs across all field types:

- `string` — human label used in views (defaults to the attribute
  name title-cased).
- `required` — declared NOT NULL in the schema; also drives the red
  `*` in form views and server-side validation.
- `default` — value applied on create when the caller doesn't set
  the field. Accepts a literal or a callable.
- `column` — overrides the SQL column name (rarely needed).
- `compute` + `store` — see [Computed fields](#computed-fields).

## Relationships

### Many2one

Pointer to a single record:

```python
class Partner(BaseModel):
    _name = "res.partner"
    country_id = Many2one("res.country", ondelete="SET NULL")
```

The column is an integer FK. `ondelete` matches the SQL options
(`"CASCADE"`, `"SET NULL"`, `"RESTRICT"`).

Reading the field returns a recordset:

```python
alice.country_id              # → res.country recordset (one or empty)
alice.country_id.name         # → "France"
alice.country_id = france     # assign a recordset
alice.write({"country_id": france.id})   # or an id
```

Dotted-path traversal works in search domains too:

```python
env["res.partner"].search([
    ("country_id.region_id.name", "=", "Europe"),
])
```

The compiler LEFT JOINs the necessary tables — no per-record query.

### One2many

The reverse side of a Many2one. No column of its own; just a
declaration that lets you walk the relationship in the other
direction:

```python
class Partner(BaseModel):
    _name = "res.partner"
    parent_id = Many2one("res.partner", ondelete="SET NULL")
    child_ids = One2many("res.partner", inverse_name="parent_id")
```

Read `alice.child_ids` to get the recordset of partners whose
`parent_id` is `alice`. Write through the inverse: setting
`child.parent_id = alice` is the canonical way to add a child.

### Many2many

A symmetric relationship backed by a junction table:

```python
class Partner(BaseModel):
    _name = "res.partner"
    tag_ids = Many2many("res.tag")
```

The framework auto-generates a junction table named
`<model1>_<model2>_rel` with two FK columns. Reading returns a
recordset; writing replaces the set:

```python
alice.tag_ids = vip + wholesale            # replace
alice.write({"tag_ids": [vip.id, wholesale.id]})   # by ids
```

(Incremental add/remove via the Odoo `[(4, id)]` tuple syntax is
not yet shipped; replace-only for now.)

## Related fields

Mirror a value from a dotted path (Odoo-style `related=`). The field
is not stored and reads/writes through the path:

```python
company_currency_id = Many2one(
    "res.currency",
    related="company_id.currency_id",
)
```

Paths must use Many2one hops only (e.g. `company_id.currency_id`). The
related field type must match the leaf. Writes update the leaf record.

## Field `readonly`

Pass `readonly=True` on any field declaration to block `write()` and
form edits (unless the view overrides with `field(..., readonly=False)`).

## Computed fields

A field becomes "computed" when you point it at a method via
`compute=`:

```python
class Partner(BaseModel):
    _name = "res.partner"
    name = Char()
    age = Integer()
    display_name = Char(compute="_compute_display_name")

    @depends("name", "age")
    def _compute_display_name(self):
        for r in self:
            r.display_name = f"{r.name} ({r.age})" if r.age else r.name
```

The `@depends` decorator declares which fields the compute reads.
The framework invalidates `display_name` whenever any of them
changes (across recordsets, across writes, across cache layers).

Two flavors:

- **Read-time compute** (default): the value is recalculated on
  access; not stored. Cheap, no migration when you add one. Fine
  for display strings, simple formatting.
- **Stored compute** (`store=True`): the value persists to a SQL
  column. Cache invalidation triggers a recompute + UPDATE on the
  next read. Use this when the field appears in `domain` clauses or
  needs to participate in indexes.

Dotted-path dependencies work — the same compiler that powers
domain traversal walks back through relations:

```python
@depends("country_id.region_id.name")
def _compute_region_label(self):
    for r in self:
        r.region_label = (
            r.country_id.region_id.name if r.country_id else ""
        )
```

A change to `Europe.name` invalidates `region_label` on every
partner in a European country, two hops back.

## Extending an existing model

`_inherit` lets a downstream module add fields, override methods,
or replace compute implementations on a model someone else owns.
No new table — the existing one gets `ALTER TABLE ADD COLUMN`.

```python
# partners_pro/models/partner.py
from pyvelm import BaseModel, Char, depends


class PartnerPro(BaseModel):
    _inherit = "res.partner"

    vip_note = Char()

    @depends("name", "vip_note")
    def _compute_display_name(self):
        # Override the base implementation but still chain to it
        # via super() so other modules can stack their own logic.
        super()._compute_display_name()
        for r in self:
            if r.vip_note:
                r.display_name = "★ " + r.display_name
```

The metaclass replaces the registry entry with a proper Python
subclass, so `super()` works through the MRO the way you'd expect.
Multiple modules can stack `_inherit` on the same target — each
one becomes another link in the chain.

## Multi-company scoping

Setting `_company_scoped = True` on a model adds an implicit
`company_id` filter to every search:

```python
class Partner(BaseModel):
    _name = "res.partner"
    _company_scoped = True

    company_id = Many2one("res.company", ondelete="SET NULL")
```

When `env.company_id` is set, queries are restricted to records
matching that id. Useful for tenant-style isolation. The
`pyvelm_company` cookie + the company switcher in the topbar drive
the env.

## Currencies

`pyvelm.modules.base` ships two collaborating models for money:

- `res.currency` — `code`, `name`, `symbol`, `rounding`, `active`, and a
  `rate_ids` One2many to its history.
- `res.currency.rate` — `currency_id` (Many2one), `date` (datetime the
  rate becomes effective), and `rate` (units per the implicit reference).
  A computed `name` provides a human-readable label.

The install hook seeds USD / EUR / GBP / JPY with starter rates so a
fresh database can do cross-currency math out of the box. Operators
replace those rates from **Settings → Currencies** (or from a scripted
seed) when accuracy matters.

### Converting amounts

```python
USD = env["res.currency"].search([("code", "=", "USD")], limit=1)
EUR = env["res.currency"].search([("code", "=", "EUR")], limit=1)

eur_amount = USD.convert(100.0, EUR)            # uses today's rate
back_then  = USD.convert(100.0, EUR, date=dt)   # uses the rate effective at dt
```

`convert` resolves the latest `res.currency.rate` row whose `date <=
date` for both the source and target currency, then computes
`amount / from_rate * to_rate`. Both sides ride the same implicit
reference (USD = 1.0 in the seed), so the reference cancels in the
arithmetic and never has to be named explicitly. If no rate is
effective at or before `date`, `convert` raises `ValueError`.

`Currency.convert` and `_rate_at` require `ensure_one()` — call them
on a single-record recordset (e.g. `currency` rather than the
results of a multi-record `search`).

### Refreshing rates from the ECB

`base` seeds an `ECB rate fetcher` server action + `ir.cron` entry
that calls `res.currency.rate.fetch_from_ecb(env)`. It pulls the
European Central Bank's [daily reference rates](https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml)
(XML, no API key) and writes one `res.currency.rate` row per
configured currency, rebased against whichever currency carries
`rate = 1.0` (USD by default).

The cron is seeded **inactive** — fresh installs never make outbound
HTTP requests until an admin flips `active = True` in Settings →
Scheduled Actions. Currencies not in the ECB feed are silently
skipped. Re-running the action on the same ECB publication date is a
no-op (same currency + same `date` is treated as already-present).

For a one-off refresh without enabling the cron, call the classmethod
directly:

```python
env["res.currency.rate"].fetch_from_ecb(env)
```

### Per-company currency

`res.company` carries a `currency_id` Many2one. The install hook
points the seeded "My Company" at USD; the `0_10_to_0_11` migration
backfills existing companies on upgrade. Slice C's `Monetary` field
reads this to decide which currency a record's amount lives in by
default:

```python
class Invoice(BaseModel):
    _name = "account.invoice"
    _company_scoped = True

    company_id  = Many2one("res.company")
    currency_id = Many2one("res.currency")  # falls back to company.currency_id
    amount      = Monetary(currency_field="currency_id")
```

Operators change a company's currency from **Settings → Companies**.

### Monetary amounts

`Monetary` is a `Float` subclass that pairs each amount with a sibling
field naming the relevant currency:

```python
from pyvelm import BaseModel, Char, Many2one, Monetary

class Invoice(BaseModel):
    _name = "account.invoice"

    name        = Char(required=True)
    currency_id = Many2one("res.currency")
    amount      = Monetary(currency_field="currency_id")  # default
```

`currency_field` defaults to `"currency_id"` to match the convention
that `res.company` and most domain records already use. The SQL
column is `double precision` — no rounding is applied on write, the
field stores whatever the caller provides.

Snap an amount to its currency's rounding step (e.g. cents for USD,
whole units for JPY) with the static helper:

```python
amount = Monetary.round_with(12.345, invoice.currency_id)  # → 12.35 for USD
amount = Monetary.round_with(149.7,  jpy)                  # → 150.0
```

The display widget reads the sibling currency from the record, prefixes
the configured symbol, and formats with the precision implied by
`rounding` (0.01 → 2 decimals, 1.0 → 0). The edit widget sets the
HTML `step` attribute from the same value so the browser's number
input matches the currency's granularity.

## Defining a custom field type

The built-ins cover most cases. When you need something specific
(a `Date`, a `Json`, a Decimal with explicit precision, a validated
`Email`), subclass `Field` or one of the existing concrete types.

A `Field` answers five questions:

| Question | Hook |
|---|---|
| What's my SQL column type? | `sql_type` class attr, or override `column_ddl()` |
| Do I have a SQL column at all? | `is_stored` |
| What's my SQL column name? | `column` (defaulted from `name`) |
| How do I normalize for binding / cache? | `to_sql_param(value)` |
| How do I shape values for Python consumers? | `to_python(value)` |

### Example: a `Date` field

```python
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
        # psycopg returns date objects; accept ISO strings for
        # callers that round-trip JSON.
        return date.fromisoformat(value)

    def to_sql_param(self, value):
        if value is None or value is False:
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value)
        raise TypeError(
            f"Date {self.name!r}: cannot bind {type(value).__name__}")
```

That's the whole field. `Field.__init__` already accepts the
common kwargs (`required`, `default`, `column`, `compute`, `store`).

### Example: a validated `Email`

When you want input-side validation without changing the SQL shape,
subclass an existing concrete type and override `to_sql_param`:

```python
import re
from pyvelm.fields import Char

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class Email(Char):
    def to_sql_param(self, value):
        if value is None or value is False:
            return None
        if not isinstance(value, str) or not _EMAIL_RE.match(value):
            raise ValueError(f"{self.name!r}: invalid email: {value!r}")
        return value
```

Every `Char` kwarg keeps working; the validation runs on every
create/write (and on cache seed, so the cache can never hold a
malformed value).

??? note "The cache rule"
    The value in `env.cache` is what `_read` would put there if it
    re-read from the database. `create` and `write` enforce this
    by caching the output of `to_sql_param`, not the user's input.
    If you ever add a write path that bypasses those (don't), apply
    the same normalization.

### Relational fields

Relational types need more than `to_sql_param` / `to_python` — they
also override `__get__` and `__set__` to return recordsets and
accept polymorphic shapes (int, recordset, None, iterables). See
`pyvelm/fields.py` for the three reference implementations.
