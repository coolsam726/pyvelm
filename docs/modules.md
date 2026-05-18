# Module reference

This file is a tour of the package, not an API dump. For each module: what
it's for, the public surface, and the invariants worth knowing when you read
the code.

## `pyvelm.registry` — [pyvelm/registry.py](../pyvelm/registry.py)

A single `Registry` instance lives at module scope (`pyvelm.registry`). Model
classes register themselves at class-creation time via the metaclass; nothing
else needs to find them.

**Public surface**

- `registry` — the singleton.
- `registry[name]` — look up a model class by `_name`.
- `registry.init_db(conn)` — run the four-pass init (see
  [architecture.md](architecture.md#multi-pass-database-init)).
- `registry.reset_db(conn)` — drop everything and re-init. Drops M2M relation
  tables explicitly before model tables.

**Internal but worth knowing**

- `_edge_index`, `_stored_compute_order` — populated by
  `_build_compute_graph()` during `init_db`. `_edge_index` is keyed by
  `(listen_model, listen_attr)` and stores a `HopEdge` per listening
  point on every parsed dep path. The `Environment` reads it to drive
  `notify_changed`.

**Invariant.** The module-global registry is fine until Stage 3. When module
loading lands, each loaded module will likely get its own registry slice.

## `pyvelm.env` — [pyvelm/env.py](../pyvelm/env.py)

Threads connection, user, context, registry, and cache through every
recordset.

**Public surface**

- `Environment(conn, uid=1, context=None, registry=None)`
- `env[model_name]` — empty recordset of that model.
- `env.with_context(**overrides)` — a sibling env sharing the same cache.
- `env.cache` — `(model, id, field)`-keyed dict with `get/set/contains/invalidate`.
- `env.compute_field(record, field)` — run a compute method, flush stored
  results to SQL.
- `env.notify_changed(model, ids, fields)` — BFS the dependency graph
  invalidating downstream cache entries and recomputing stored fields.
  Delegates the actual graph walk to `HopEdge.find_source_ids` (see
  `paths.py`), so the same code path handles M2o, O2m, and M2m
  traversals.

**Invariant.** `_in_compute` is the single flag that gates whether
`Field.__set__` accepts writes to a computed field. Always reset in a
`finally` block; otherwise an exception in a compute method permanently
unlocks computes.

## `pyvelm.fields` — [pyvelm/fields.py](../pyvelm/fields.py)

Where the field descriptors live. The base `Field` carries cache/SQL/DDL
contracts; subclasses customize storage and access.

**Class hierarchy**

```
Field
├── Char         (TEXT, with `size` for documentation only)
│   └── Text
├── Integer      (integer)
├── Float        (double precision)
├── Boolean      (boolean — native PG type)
├── Many2one     (integer FK, exposes singleton recordset)
├── One2many     (no column, lazy reverse query)
└── Many2many    (no column, auto junction table, lazy junction query)
```

**Per-field contracts**

| Hook | Called when |
|------|---|
| `bind(model_name, name)` | metaclass, after the class body |
| `column_ddl()` | model `_setup_table` |
| `column` | every SQL emitter that needs the column name |
| `is_stored` | DDL pass, `_split_vals`, `_read` |
| `to_sql_param(value)` | INSERT/UPDATE params + cache seeding |
| `to_python(value)` | descriptor read |
| `__get__` / `__set__` | descriptor protocol |
| `resolve_spec(model_cls, registry)` | Many2many only — gives `(relation, col1, col2, this_table, target_table)` |

**Invariants.**

1. Reads and writes to scalar fields go through `env.cache` first; SQL only
   when the cache misses.
2. `to_sql_param` is the canonical normalizer: a recordset → its id, a
   bool → bool (PG), etc. `create()` and `write()` use it for both SQL bind
   params and cache seeding so cache and DB never disagree.
3. `is_stored=False` means "no SQL column on this model's own table." It
   does **not** mean "no SQL anywhere" — Many2many is non-stored but owns a
   junction table.

## `pyvelm.paths` — [pyvelm/paths.py](../pyvelm/paths.py)

Shared parser for dotted references. Used by the compute-field dep graph
and by the domain compiler.

**Public surface**

- `parse_path(model_cls, path, registry) -> Path` — parses a dotted
  reference (`country_id.region_id.name`) against a model. Every non-leaf
  token must name a relational field. Validates as it goes.
- `Path` — `source_model`, `hops: list[Hop]`, `leaf_model`, `leaf_attr`.
  Exposes `is_m2o_only()`, `reads()`, and `edges()`.
- `Hop` and its three concretes: `M2oHop`, `O2mHop`, `M2mHop`. Each
  implements `reverse_walk(env, ids)` — "given ids on the *target* model,
  return ids on the *source* model that relate to them via this hop."
- `HopEdge` — `listen_at: (model, attr)`, `to_source: callable`,
  `hops_to_walk: list[Hop]`, with `find_source_ids(env, ids)` doing the
  full walk.

**Invariant.** A Path's `edges()` is the contract between the parser and
the dep graph. Adding a new hop type means: subclass `Hop`, implement
`reverse_walk`, and add the right `HopEdge` case in `Path.edges`. Nothing
else needs to know about your new hop type.

## `pyvelm.domain` — [pyvelm/domain.py](../pyvelm/domain.py)

Translates `[(attr, op, value), ...]` into a SQL `WHERE` clause plus any
required `LEFT JOIN`s.

**Public surface**

- `domain_to_sql(domain, model_cls)` — returns `(where, params, joins)`
  where `joins` is the `LEFT JOIN ...` text (or `""`).

**Behavior**

- Simple attrs validated against `model_cls._fields` (or accepted if
  `attr == "id"`).
- Dotted attrs parsed via `paths.parse_path`. M2o-only chains emit
  `LEFT JOIN`s with generated aliases (`_j1`, `_j2`, …); aliases are
  memoized per chain so two leaves on the same path share JOINs.
- Paths containing any O2m/M2m hop emit a per-leaf
  `EXISTS (SELECT 1 ...)` subquery with aliases in their own
  `_e<n>_<i>` namespace. Each leaf gets a fresh subquery — semantically
  correct because two collection leaves can match different members.
- Values coerced through `field.to_sql_param` so Many2one leaves accept
  recordsets.
- Operators: `=`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`, `like`,
  `ilike`. Native PG `ILIKE`.
- Empty `in`/`not in` short-circuit to `FALSE`/`TRUE`.

## `pyvelm.model` — [pyvelm/model.py](../pyvelm/model.py)

`MetaModel` collects fields and binds compute methods; `BaseModel`
implements the recordset protocol and the CRUD methods.

**Public surface**

- `BaseModel.create(vals)` — returns a singleton recordset.
- `BaseModel.write(vals)` — applies to every id in self.
- `BaseModel.unlink()` — DELETE, then drop cache entries for the deleted ids.
- `BaseModel.read(fields=None)` — bulk-load fields, return dicts; non-stored
  fields are accessed via their descriptor on per-record singletons.
- `BaseModel.search(domain, limit=None, offset=0, order=None)`
- `BaseModel.search_count(domain)`
- `BaseModel.browse(ids)` — wrap ids in a recordset.
- `BaseModel.ensure_one()` — assert singleton.

**Internal but worth knowing**

- `_split_vals(vals)` — separates column-vals (Many2one + scalars) from M2M
  vals. Rejects non-stored fields except Many2many. Used by both `create`
  and `write`.
- `_apply_m2m(parent_ids, m2m_vals)` — DELETE then INSERT junction rows.
  Full replacement semantics.
- `_setup_table`, `_setup_foreign_keys`, `_setup_relation_tables`,
  `_validate_relations` — the four init passes, one method each.

**Invariant.** Every write path that mutates state ends with a
`env.notify_changed(...)` call so the dep graph stays consistent.

## `pyvelm.depends` — [pyvelm/depends.py](../pyvelm/depends.py)

Tiny module. Defines `depends(*paths)` which stashes the dep tuple on the
method as `_pyvelm_depends`. The metaclass copies it onto the matching
field's `depends_on` attribute.

Paths supported: any combination of M2o, O2m, and M2m hops at any depth.
Parsing happens in `pyvelm.paths.parse_path`; the metaclass simply stashes
the raw path strings on `field.depends_on`. Validation (does the field
exist? is each non-leaf relational?) runs once at registry init.

## `pyvelm.__init__` — [pyvelm/__init__.py](../pyvelm/__init__.py)

Re-exports the public API: `BaseModel`, the field classes, `Environment`,
`registry`, and the `depends` decorator. Nothing imported from here is
considered private.
