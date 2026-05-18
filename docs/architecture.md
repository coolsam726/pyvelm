# Architecture

This document explains the design decisions that shape pyvelm, not the public
API. For per-module details, see [modules.md](modules.md). For implementing
new field types, see [extending-fields.md](extending-fields.md).

## Core abstractions

### Recordset-is-the-model

A `BaseModel` instance carries an `Environment` and a tuple of ids. Length 0
is an empty recordset, 1 is a singleton, more than 1 is a multi-record set.
There is no separate "record" type — every operation, including `create`,
returns a recordset. Singleton invariants are enforced explicitly at the
boundaries where they matter:

```python
def ensure_one(self) -> None:
    if len(self._ids) != 1:
        raise ValueError(...)
```

Field descriptors call `ensure_one()` on read because returning "the field of
one of two records" has no useful meaning.

### Environment

The `Environment` is the only thing recordsets carry around besides their
ids. It bundles:

- `conn` — the psycopg connection (in autocommit mode for Stage 2)
- `uid` — the acting user id (placeholder until ACLs land in Stage 5)
- `context` — an ad-hoc dict (multi-company, locale, etc.)
- `registry` — the global model registry
- `cache` — the field-value cache (see below)
- `_in_compute` — a flag the compute-field orchestrator flips

Every recordset constructor takes an `Environment`. New environments share
the same cache if forked via `with_context` — cache invalidation is
env-scoped, not per-recordset.

### Cache keyed by (model, id, field)

Field values do **not** live on instances. They live in `env.cache` under
keys of shape `(model_name, record_id, attr_name)`. This is the single most
important design decision in pyvelm and it pays off in three ways:

1. **Recordsets become cheap views.** Creating `Partner.browse([1, 2, 3])` is
   a tuple-of-ids assignment — no field data is touched.
2. **Computed-field invalidation is tractable.** Dropping a field value is
   `del cache[(model, id, field)]`. Cascading through a dependency graph is
   a series of key deletions; there is no graph walk over instance state.
3. **Multi-environment is natural.** A fresh `Environment` starts with a
   fresh cache. State doesn't leak between requests/test runs unless you
   deliberately share the env.

The cache is a plain dict today. No LRU, no eviction. That's a deferred item
— see CONTEXT.md.

### Field descriptors

Every field is a descriptor on its model class. The class attribute *is*
the field instance:

```python
class Partner(BaseModel):
    name = Char(required=True)        # descriptor lives on Partner.__dict__
```

`__get__` routes to `env.cache`, loads from SQL on miss, and wraps the value
through `to_python`. `__set__` routes to `record.write({attr: value})` for
plain fields, or special-cases for relational/computed fields. The
descriptor protocol is what makes `alice.name` look like attribute access
while doing cache-aware reads under the hood.

Field instances also carry their `column` (the SQL column name, defaulted to
`name`). The two can diverge — see the `column=` kwarg on `Field.__init__` —
but Odoo-style projects keep them equal.

## Multi-pass database init

`registry.init_db(conn)` runs four passes, in order:

1. **CREATE TABLE for each model.** Stored fields contribute columns;
   non-stored fields (One2many, Many2many, non-stored computes) don't.
2. **ALTER TABLE ADD CONSTRAINT for Many2one FKs.** Done in a second pass
   so target tables exist and self-referential FKs work.
3. **CREATE TABLE for Many2many junction tables.** Symmetric M2M pairs
   dedupe via a `created` set keyed by relation name.
4. **Validate non-stored relational fields and build the compute graph.**
   One2many inverses are checked, Many2many comodels are checked, then the
   `@depends` paths are parsed into `_direct_deps` and `_m2o_deps`, cycles
   are detected, and `_stored_compute_order` is computed per model.

`reset_db` drops M2M relation tables explicitly *before* dropping model
tables. This protects against stale schema where the junction exists
without FK constraints — `CREATE TABLE IF NOT EXISTS` would otherwise
silently skip recreation.

## Domain compiler

`domain_to_sql(domain, model_cls)` translates a list of `(attr, op, value)`
leaves into a `WHERE` clause. Three notable behaviors:

- **Attr names are validated against `model_cls._fields`.** Typos raise
  `ValueError: Unknown field 'contry_id' on res.partner in domain` instead
  of hitting Postgres as `column does not exist`.
- **`id` is a pseudo-field** — not in `_fields`, but always queryable.
- **Values flow through `field.to_sql_param`.** A `Many2one` leaf accepts
  a recordset as its value; the compiler coerces it to the id.

Operators supported: `=`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`,
`like`, `ilike`. AND-only — no polish notation, no relational traversal.
Traversal lands together with multi-hop `@depends` since both need the
same dotted-path parser.

## Computed fields with `@depends`

A computed field is a method whose result is cached under
`(model, id, field)`. Read paths cache-miss into the compute method; the
method writes via `__set__`, which detects `env._in_compute` and routes
to cache only.

### Field declaration

```python
display_name = Char(compute="_compute_display_name")          # non-stored
age_bucket   = Char(compute="_compute_age_bucket", store=True)  # stored

@depends("name", "country_id.code")
def _compute_display_name(self):
    for r in self:
        r.display_name = f"{r.name} [{r.country_id.code or '-'}]"
```

- `compute=` names a method on the same class.
- `store=False` (default for compute fields) means no SQL column; cache
  is the only home.
- `store=True` adds a real SQL column. Cached values are flushed to SQL
  after the compute method returns.
- `@depends` is required on the compute method. The metaclass copies the
  paths onto `field.depends_on`. A method with `@depends` but no field
  referencing it raises at class-creation time.

### The dependency graph

Built once at `registry.init_db()`. Two index shapes:

```
_direct_deps[(model, attr)]    -> [(dep_model, dep_field), ...]
_m2o_deps[(comodel, attr)]     -> [(dep_model, m2o_attr, dep_field), ...]
```

A `@depends("name")` on `res.partner.display_name` adds:

```
_direct_deps[("res.partner", "name")].append(("res.partner", "display_name"))
```

A `@depends("country_id.code")` on `res.partner.display_name` adds *both*:

```
_direct_deps[("res.partner", "country_id")]   .append(("res.partner", "display_name"))
_m2o_deps[("res.country", "code")]            .append(("res.partner", "country_id", "display_name"))
```

The first edge handles "the FK itself changed"; the second handles "a field
on the comodel changed, find all records that point at it." Both edges fire
their dependent on invalidation.

### Cycle detection

A separate read-edge map is built only for compute-field nodes
`(model, field)`. DFS coloring detects cycles; the error message names the
cycle path.

### Topological order for stored compute fields

After cycle detection, per-model topological order of stored compute fields
is computed and cached on `_stored_compute_order`. `create()` runs them in
that order so dependent computes see their inputs already populated.

### `notify_changed` propagation

After `create()` or `write()`, the model calls
`env.notify_changed(model_name, ids, fields)`. The algorithm is BFS over
the dep graph:

```
queue = direct + m2o-traversal dependents of (model, fields)
while queue:
    (m, f, idset) = pop
    if (m, f) already processed: merge idset; continue if empty
    invalidate cache for (m, idset, f)
    if f is stored: recompute via compute_field and UPDATE the column
    enqueue dependents of (m, f)
```

The reason recomputation is eager for stored fields and lazy for non-stored
is correctness across sessions: a stored field's SQL column is queried by
other sessions, so it must be up-to-date. A non-stored field's cache is
session-local — the next read in this session will recompute it on miss.

### Rejecting external writes

`__set__` on a compute field raises `ValueError` unless
`env._in_compute` is truthy. This forces the data flow to be: deps change
→ invalidation → recompute. There is no "set it directly and hope for the
best" path.

## Deliberately deferred

Each of these is a known gap; the trade-off is documented to keep the gap
visible.

| Gap | Why deferred |
|-----|---|
| LRU / eviction on `env.cache` | Single env per request, ids are bounded by the working set. Premature optimization until proven a problem. |
| Relational traversal in domains | Needs a dotted-path parser shared with multi-hop `@depends`. Land them together. |
| Multi-hop `@depends` | Same parser dependency. Single-hop covers the common cases. |
| O2m/M2m caching | Re-querying each access is correct; perf gap is acceptable. Adding cache requires inverse-side invalidation, which falls out of the same parser. |
| Stale FK cache on comodel unlink | The DB sets the FK to NULL via `ON DELETE SET NULL`, but `env.cache` still holds the old int. Fix needs a reverse-FK index. Bundled with O2m caching. |
| M2M command tuples | Replace-only writes work for everything in the example; `[(0,_,vals), (4,id)]` are an API ergonomics layer, not a capability layer. |
| Transaction boundaries beyond autocommit | Adds a real unit-of-work concept. Right when multi-statement consistency matters, not before. |
| Stored compute backfill on schema add | The current schema is recreated via `reset_db`. Real migrations are a Stage 3 concern. |
| ACL, record rules, multi-company | Stage 5. The `Environment` already carries `uid`/`context`, so the integration point is in place. |

## Why the design holds up

Three invariants do most of the structural work:

1. **Cache is keyed by `(model, id, attr)`** — every layer (CRUD, descriptors,
   computed fields, the dep graph) speaks the same coordinate.
2. **Recordsets are tuples of ids over an env** — operations naturally
   bulk-scale; singletons are special cases enforced explicitly.
3. **Init is multi-pass** — schema/constraint/relation/validation each runs
   when its prerequisites are met. Adding Stage 3 module loading slots in as
   another pass between (3) and (4).
