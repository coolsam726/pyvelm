# Architecture

This page explains the design decisions that shape pyvelm — the
"why" behind the public API. The other guides (Models, Views,
Modules) cover the "how". Read this when you want to know what
the framework is doing under the hood.

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

- `conn` — the psycopg connection.
- `uid` — the acting user id (or `None` for anonymous).
- `company_id` — the active company for multi-company-scoped models.
- `context` — an ad-hoc dict for per-request state.
- `registry` — the model registry.
- `cache` — the field-value cache (see below).
- `_in_compute` — a flag the compute-field orchestrator flips.

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

The cache is a plain dict today. No LRU, no eviction — the working set
per request is bounded, so it's not yet a problem.

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

## Access control

Four models in the base module — `res.groups`, `res.users`,
`ir.model.access`, `ir.rule` — plus a thin enforcement layer at the
ORM and HTTP boundaries.

- `env.uid` carries the active user's id; `uid=1` is the hard-coded
  superuser and bypasses every check (Odoo's `SUPERUSER_ID`).
- `BaseModel.search` / `search_count` / `_read` call
  `env.check_access(model, perm)` and `env.collect_record_rules(model,
  perm)`. The latter returns domain leaves that get AND-injected into
  the search's WHERE — that's how row-level filters happen.
- `BaseModel.create` / `write` / `unlink` only check the perm bit; no
  rule injection — write paths don't restrict to rows the user
  already can see (yet).
- The HTTP layer's `get_env` dependency reads HTTP Basic auth or the
  session cookie, validates against `res.users` + bcrypt, and sets
  `env.uid` per request. Failures raise `PermissionError`; the
  exception handler maps anonymous to 401 + `WWW-Authenticate`,
  authenticated to 403.
- Passwords are bcrypt-hashed on assignment via a `Password(Char)`
  field subclass.
- Record-rule domains are stored as JSON, with `{"placeholder":
  "uid"}` dicts substituted at query time. All applicable rules
  (global + user's group rules) are **AND-ed** — stricter than
  Odoo's per-group OR semantics, chosen for simplicity.

## Web layer: views as data

Views are records. `ir.ui.view` stores `(module, name, model,
view_type, arch)`; a module declares views in its `__pyvelm__.py`
under a `VIEWS = [...]` list, and the loader upserts them by
`(module, name)` on every install pass. There is no separate "view
migration" — re-declaring rewrites the record.

The HTTP surface (`pyvelm/web.py`) is a thin FastAPI app parameterized
by a loaded `Registry` and a psycopg connection pool. Each request
checks out a connection, wraps it in a fresh `Environment`, runs the
handler synchronously, and returns the connection to the pool. The
async wrapping happens entirely at FastAPI's level; the ORM stays
sync.

JSON serialization is one shape: Many2one as `[id, display_value]`,
collections as id lists, scalars pass through. `display_value` reads
`display_name` then `name` then falls back to `str(id)`. Frontends
fetch related details with a follow-up `/api/records?model=...`.

**UI stack: Tailwind v4 + Flowbite, compiled locally.** The
bundled HTMX renderer ships templates that load
`pyvelm/static/dist/pyvelm.css`, built by `npm run build` against
`pyvelm/static/tailwind.css`. The dist file is checked into git so
the framework boots without requiring `npm install` first. This is
the major UI-stack deviation from Odoo (Bootstrap).

**View inheritance** is dict-merge on the arch with addressable paths
(no XPath, no XML). An extension view declares `inherit_id` and an
`operations` list; the resolver walks the chain in ascending
`priority` order and applies each level's ops to a deepcopy of the
root arch. Six op kinds cover the full Odoo XPath-position vocabulary
(`set` / `replace` / `update` / `remove` / `before` / `after`); see
[Extending views](inheritance.md) for the user-facing reference.

Targets are lists of segments. Strings address dict keys or by-`name`
matches in list-of-dicts; ints address positional indices; dict
predicates match list entries by any attribute; `"**"` as a prefix
finds the next segment anywhere in the tree. Authoring sugar
(`"fields": ["name", "age"]`) is normalized at load time to the
list-of-dicts form so inheritance always works against stable
addresses.

## Module lifecycle

A pyvelm app is a set of modules, each a Python package with a
`__pyvelm__.py` manifest declaring `NAME`, `VERSION`, and `DEPENDS`. The
loader (`pyvelm/loader.py`) discovers them under one or more roots,
topo-sorts by `DEPENDS`, and installs each module's schema and
migrations into a `Registry`.

There is **no module-global registry**. Models register into whichever
`Registry` is "active" at class-creation time, set via
`with registry.activate():`. The loader brackets each module's models
import in that context. Defining a model outside any active registry
raises — silent fallbacks make multi-registry bugs hard to find.

The loader walks specs in topo order and, for each module:

- If absent from `ir_module`: create its tables and FKs, run the install
  hook, record the version.
- If present with an older version: run every script under
  `<module>/migrations/` sorted by filename; bump the version.
- If present with the same version: no-op.

Each per-module step runs inside `env.transaction()`. The compute graph
(`_build_compute_graph`) and relational validation
(`_validate_relations`) run *after* all modules are loaded so cross-module
references (e.g. `partners.Partner.display_name` depending on
`base.Region.name`) resolve.

See [Modules](modules.md) for the user-facing guide.

## Multi-pass database init

`registry.init_db(conn)` is now the "install everything at once" shortcut
used by tests and the legacy `reset_db`. Production goes through
`loader.install` which runs the same passes scoped to one module at a
time, transaction-wrapped. The pass list is the same either way:

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
`like`, `ilike`. Top-level leaves without operators are **AND**ed
(``normalize_domain`` makes this explicit).

**Prefix operators** (Odoo-compatible): ``&`` (AND), ``|`` (OR), ``!`` (NOT).
Example: ``['&', ('state', '=', 'posted'), '|', ('name', 'ilike', 'a'), ('ref', 'ilike', 'a')]``.

The legacy ``("__or__", "=", [sub_leaves…])`` leaf is expanded to ``|`` groups
before compilation. See [Declaring models → Search domains](models.md#search-domains).

**Path traversal in domains.** A dotted attr (`country_id.region_id.name`)
is parsed against the model into a `Path`. Two emission strategies:

- **Pure-M2o chains** emit `LEFT JOIN`s with generated aliases (`_j1`,
  `_j2`, ...) and qualify the leaf reference against the last-join alias.
  Aliases are memoized per `(base, ...attr_chain)` so multiple leaves on
  the same chain share JOINs.
- **Paths containing any O2m or M2m hop** emit an `EXISTS (SELECT 1 ...)`
  subquery instead. Each such leaf gets its *own* subquery, with aliases
  in its own `_e<n>_<i>` namespace, anchored to the outer base via the
  hop's linkage column (`junction.col1 = base.id` for M2m;
  `child.inverse_fk = base.id` for O2m).

The per-leaf EXISTS rule is the semantically correct one for collections:
`[("tag_ids.name", "=", "EU"), ("tag_ids.name", "=", "Asia")]` reads as
"has an EU-named tag AND has an Asia-named tag" — possibly different
tags. Two separate `EXISTS` clauses say exactly that. Merging them into
one body would silently mean "has a single tag that is both EU and
Asia," which is rarely what anyone wants.

Negated operators in collection paths (`!=`, `not in`) keep their natural
existential read: "has at least one member whose value doesn't match."

**Universal quantification** — add a fourth leaf element `{"all": True}` on
collection paths only:

```python
# every tag is non-VIP (including partners with no tags)
Partner.search([("tag_ids.name", "!=", "VIP", {"all": True})])
```

Implemented as `NOT EXISTS` over members that fail the condition.

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

Built once at `registry.init_db()` via the path parser (see `paths.py`).
A single index:

```
_edge_index[(listen_model, listen_attr)] -> [(dep_model, dep_field, HopEdge), ...]
```

Each `@depends` path is parsed into a `Path` with zero or more relational
`Hop` objects. The path emits one `HopEdge` per hop *and* one for the
leaf — these are the listening points whose changes should invalidate the
dependent compute field. When a change fires at `(model, attr)`,
`notify_changed` looks up the matching edges and calls
`edge.find_source_ids(env, ids)`, which:

1. Runs the edge's `to_source` transform (identity for M2o/M2m, or a
   read-the-inverse-FK lookup for O2m hops).
2. Reverse-walks any remaining hops back toward the source model.

Concretely, `@depends("country_id.region_id.name")` on
`res.partner.display_name` registers three edges:

| Listening at | Hops to reverse-walk |
|---|---|
| `(res.partner, country_id)` | none — partner is already on the source side |
| `(res.country, region_id)` | walk `country_id` reverse (countries → partners) |
| `(res.region, name)` | walk `region_id` reverse, then `country_id` reverse |

The first handles "the FK on the partner changed." The second handles "a
country's region_id changed — find all partners pointing at those
countries." The third handles "a region's name changed — chase it back
through countries to partners."

`HopEdge` is type-agnostic. The same machinery handles M2o, O2m, and M2m
hops because each hop type implements `reverse_walk(env, ids) -> ids`.
O2m hops listen on the comodel's inverse-FK attr; M2m hops listen on the
source-side M2m attr (which fires when the junction is mutated through
`write`/`_apply_m2m`).

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
| Universal-quantifier edge cases | Vacuous truth when a partner has no tags; `like`/`ilike` with `all` use `NOT ILIKE` failure rows. |
| O2m/M2m caching (full dep graph) | Tuple cache + invalidation on inverse FK / M2M writes, comodel unlink, and symmetric M2M fields sharing a junction table. Remaining gap: raw SQL junction edits. |
| M2M command tuples | Replace-only writes work for everything in the example; `[(0,_,vals), (4,id)]` are an API ergonomics layer, not a capability layer. |
| Transaction boundaries beyond autocommit | Adds a real unit-of-work concept. Right when multi-statement consistency matters, not before. |
| Stored compute backfill on schema add | The bulk-recompute step is hand-written when needed — the auto-diff story would have to ship first. |

## Why the design holds up

Three invariants do most of the structural work:

1. **Cache is keyed by `(model, id, attr)`** — every layer (CRUD, descriptors,
   computed fields, the dep graph) speaks the same coordinate.
2. **Recordsets are tuples of ids over an env** — operations naturally
   bulk-scale; singletons are special cases enforced explicitly.
3. **Init is multi-pass** — schema, constraints, relations, and
   validation each run when their prerequisites are met. Module
   loading slots in as another pass; future additions (a new view
   type, a new dep-graph hop kind) work the same way.
