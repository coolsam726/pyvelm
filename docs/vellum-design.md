# Vellum — design doc

**Status:** Slices A–D implemented (Vellum feature-complete; Slice E migration
DSL deferred). **User guide:** [vellum.md](vellum.md). Inheritance:
``class Model(Vellum, BaseModel)``; add ``SoftDeletes`` last:
``class Post(Vellum, BaseModel, SoftDeletes)``.
**Module name:** `vellum`
**Location:** `pyvelm/modules/vellum/` (bundled, opt-in per model)
**Depends on:** `base`
**Tracking issue:** TBD

> **Why "Vellum"?** Vellum is the fine parchment scribes used for
> manuscripts that had to last — the surface that holds expressive,
> deliberate writing. The metaphor lands cleanly on an ORM (the surface
> that holds the record), and the name rhymes with **pyvelm**, so
> `pyvelm.vellum` reads like it was named for this framework.

## 1. Goal

Bring [Laravel Eloquent](https://laravel.com/docs/eloquent)-style ergonomics
to pyvelm — chainable query builder, method-based relationships, eager
loading, model events, mass-assignment policy, accessors/mutators, optional
soft deletes — **without forking the ORM**.

Every Vellum verb must compose down to an existing pyvelm primitive
(`BaseModel.search`, `BaseModel._read`, `env.cache`,
`AutomationEngine.fire`, etc.). The veneer is sugar; the substrate stays
authoritative for SQL, ACL, multi-company, and computed-field
invalidation.

## 2. Non-goals

- **Not a parallel ORM.** No second cache, no second connection layer,
  no second ACL pipeline, no second domain compiler.
- **Not a replacement for `env[...].search(...)`.** The two styles
  coexist on the same models in the same env. Existing pyvelm code
  keeps working unchanged.
- **Not a Python port of PHP idioms.** `Model::where` becomes
  `Model.query(env).where`; `$user->name` becomes `user.name` (already
  works); facades (`DB::table(...)`) are out of scope.
- **No new field types.** Fields stay in `pyvelm.fields`.
- **No view-layer changes.** Forms / lists / kanbans still consume the
  same recordsets.

## 3. The substrate (what already exists)

To anchor the design, here's what we already have in core:

| Concern | Existing primitive |
|---|---|
| Read by domain | `BaseModel.search(domain, limit, offset, order)` |
| Count | `BaseModel.search_count(domain)` |
| Bulk fetch into cache | `BaseModel._read(fields)` keyed by `(model, id, field)` |
| Recordset semantics | `BaseModel.__iter__`, `len`, `bool`, `==`, `browse` |
| Cache layer | `env.cache.get/set/contains/invalidate` |
| Lifecycle hooks | `AutomationEngine.fire(env, model, event, records)` from `create/write/unlink` |
| Computed invalidation | `env.notify_changed(model, ids, fields)` |
| Multi-company filter | `_company_scoped` auto-injects in `search` |
| ACL | `env.check_access(model, perm)` in every CRUD/search |

Every section below maps Vellum verbs onto these primitives.

## 4. File layout

```
pyvelm/modules/vellum/
├── __pyvelm__.py            # manifest: NAME="vellum", DEPENDS=["base"]
├── __init__.py              # public API re-exports
├── mixin.py                 # the Vellum opt-in mixin (Slice A)
├── query.py                 # QueryBuilder (Slice A)
├── collection.py            # recordset extensions (Slice A)
├── relations.py             # BelongsTo / HasMany / HasOne / BelongsToMany (Slice B)
├── eager.py                 # with_() driver, batched prefetch (Slice B)
├── scope.py                 # @scope decorator (Slice C)
├── attribute.py             # get_X_attribute / set_X_attribute weaving (Slice C)
├── events.py                # creating/created/updating/... dispatcher (Slice C)
├── soft_delete.py           # SoftDeletes mixin + with_trashed/only_trashed (Slice D)
└── tests/...
```

The module ships **no DB models of its own**. The manifest exists only so
the loader knows the module is installed; nothing in the migration table
changes when it loads. (We may want a `vellum.fake` test-only model
in `tests/` so the CI suite has something to exercise; it would not be
seeded.)

## 5. Opting a model into Vellum

Vellum is a **per-model opt-in**, not a global switch:

```python
from pyvelm import BaseModel, Char, Integer, Many2one
from pyvelm.vellum import Vellum, scope


class Post(Vellum, BaseModel):
    _name = "blog.post"

    title = Char(required=True)
    body = Char()
    author_id = Many2one("res.users", required=True)
    views = Integer(default=0)

    _fillable = ["title", "body", "author_id"]

    def author(self):
        return self.belongs_to("res.users", "author_id")

    @scope
    def popular(qb):
        return qb.where("views", ">", 100)
```

The `Vellum` mixin's `__init_subclass__` does the wiring (collects
`@scope` methods, weaves accessors/mutators, registers event hooks).
**List `Vellum` before `BaseModel`** in the inheritance tuple so Python
MRO picks Vellum's ``create`` / ``write`` / ``unlink`` overrides for
events and mutators.

Models that don't inherit `Vellum` are unaffected — they keep working
through the regular pyvelm idiom.

### 5.1 Which class to call `query` on? (`env.query`)

Models are often extended with `_inherit` in other modules. The loader
**replaces** `registry["blog.post"]` with a merged class; importing
`Post` from `blog.models.post` may be a stale Python object after
extensions load.

**Runtime rule:** use the technical name on the environment:

```python
posts = env.query("blog.post").where("views", ">", 100).get()
```

`Environment.query(model_name)` resolves `registry[model_name]` (the
same class as `env[model_name].__class__`) and returns a `QueryBuilder`.
Works for any registered model; collection helpers (`pluck`, in-memory
`where`, …) still require the `Vellum` mixin on that model.

`Post.query(env)` remains valid in the module that defines `_name`
(tests, scripts with a fixed module set).

## 6. Slice A — QueryBuilder + collections

### 6.1 QueryBuilder API

`env.query("blog.post")` (preferred) or `Post.query(env)` returns a
`QueryBuilder` bound to that env. Builders are immutable — every
chainable returns a fresh builder, so they're safe to share and compose.

```python
# Build (prefer env.query when _inherit is in play)
qb = env.query("blog.post")                 # QueryBuilder
qb = Post.query(env)                        # same, if Post is the registry class
qb = qb.where("author_id", env.uid)
qb = qb.where("views", ">", 100)
qb = qb.where_in("status", ["draft", "review"])
qb = qb.where_like("title", "intro%")
qb = qb.where_between("published_at", start, end)
qb = qb.where_null("archived_at")
qb = qb.order_by("created_at", "desc").limit(20)

# Terminate
posts = qb.get()                            # Recordset
post = qb.first()                           # Recordset(1) or empty
post = Post.query(env).find(42)             # by id
post = Post.query(env).find_or_fail(42)     # raises
names = qb.pluck("title")                   # list[str]
total = qb.count()                          # int
exists = qb.exists()                        # bool
for chunk in qb.chunk(500):                 # iterates page-by-page
    ...
page = qb.paginate(page=2, per_page=20)     # {items, total, page, per_page}
```

**Implementation:** the builder accumulates `(field, op, value)` tuples
in a `_wheres` list and an `_orders` list. Terminators call
`Model.search(domain, limit, offset, order)` / `search_count` /
`browse` — no new SQL paths.

#### Operator mapping

Laravel Eloquent's verbose operator strings map cleanly to pyvelm domain ops:

| QB call | pyvelm domain leaf |
|---|---|
| `where("x", v)` | `("x", "=", v)` |
| `where("x", "!=", v)` | `("x", "!=", v)` |
| `where("x", ">", v)` | `("x", ">", v)` |
| `where_in("x", vs)` | `("x", "in", list(vs))` |
| `where_not_in("x", vs)` | `("x", "not in", list(vs))` |
| `where_like("x", pat)` | `("x", "like", pat)` |
| `where_ilike("x", pat)` | `("x", "ilike", pat)` |
| `where_null("x")` | `("x", "=", None)` |
| `where_not_null("x")` | `("x", "!=", None)` |
| `where_between("x", a, b)` | `("x", ">=", a), ("x", "<=", b)` |

`or_where(...)` and grouped `where(callable)` need OR support. The
existing pyvelm domain parser uses Polish-style `|` / `&` prefixes
(check `pyvelm/domain.py` before implementing). The builder emits the
right prefix tokens at terminate time.

### 6.2 Collection helpers on recordsets

These extend recordsets returned from Vellum-opted models. Two
options to expose them:

- **Option A (clean, recommended):** the `Vellum` mixin contributes
  methods directly to the model class — so `Post.query(env).get()`
  returns a `Post`-class recordset that has `.pluck`, `.first`, `.map`,
  etc., natively.
- **Option B (universal):** a `Collection.wrap(rs)` adapter that any
  recordset can pass through. Useful when collection helpers are wanted
  on a non-opted model.

We ship Option A and keep Option B as a small utility.

```python
posts = Post.query(env).get()

posts.pluck("title")                # ["Intro", "Tutorial", ...]
posts.first()                        # Post(...) singleton or empty
posts.last()                         # Post(...) singleton or empty
posts.contains(some_post)            # bool, by id
posts.where("status", "draft")       # in-memory filter; returns Post recordset
posts.find(42)                       # in-set lookup; empty if not present
posts.map(lambda p: p.title.upper())
posts.filter(lambda p: p.views > 100)
posts.each(lambda p: print(p.id))
posts.chunk(100)                     # iterable of Post recordsets
posts.to_list()                      # list of dicts via .read()
posts.fresh()                        # re-search same ids, drop cache
```

**Important distinction:** `qb.where(...).get()` builds SQL; `posts.where(...)`
filters in-memory and never hits the DB. Same name, different layer —
Laravel does this too, and it's a footgun. We document it loudly.

### 6.3 Slice A footprint

- ~3 new files: `query.py`, `collection.py`, plus the skeleton `mixin.py`.
- ~400 LoC + tests.
- **Zero changes to pyvelm core.**
- Lands as a single PR.

## 7. Slice B — Relationships as methods + eager loading

### 7.1 Method-based relations

Laravel Eloquent's killer feature: relations are methods, and the method
returns a relation object that is itself queryable.

```python
class Post(Vellum, BaseModel):
    _name = "blog.post"
    author_id = Many2one("res.users", required=True)

    def author(self):
        return self.belongs_to("res.users", "author_id")

    def comments(self):
        return self.has_many("blog.comment", inverse_name="post_id")

    def tags(self):
        return self.belongs_to_many("blog.tag")
```

Usage:

```python
post = Post.query(env).find(1)
post.author().get()                  # Recordset[res.users] of size 1
post.comments().where("approved", True).order_by("posted_at").get()
post.tags().count()
```

Relations are thin wrappers over `QueryBuilder` with a pre-applied
filter. `BelongsTo` reads the FK column from the parent and queries the
co-model by id; `HasMany` filters the co-model by the inverse column;
`BelongsToMany` joins through the existing M2M junction table that
`Many2many` already generates.

**Coexistence with field descriptors.** A user can declare *both* a
relational field and a relation method on the same name:

```python
class Post(Vellum, BaseModel):
    comments = One2many("blog.comment", "post_id")   # field

    def comments(self):                              # SHADOWS the field
        return self.has_many("blog.comment", "post_id")
```

Python's class body rules pick the last-assigned name, which is the
method — so the descriptor disappears. **We disallow this collision**
at `__init_subclass__` time and raise a clear error. Two acceptable
patterns:

- Declare the relation as a method only; `post.comments()` returns the
  queryable, `post.comments().get()` returns the recordset.
- Keep the field and don't declare a method — `post.comments` already
  works the pyvelm way, and `with_("comments")` (below) eager-loads it.

The doc will recommend the second pattern for One2many/Many2many (since
the field is already there) and the first pattern for relation styles
the pyvelm field layer doesn't yet model (e.g. polymorphic relations,
through-relations, scope-bound relations).

### 7.2 Eager loading via `with_(...)`

The N+1 fix. `with_(*paths)` adds prefetch instructions to the builder;
the terminator runs them after the main `search`.

```python
posts = (
    Post.query(env)
        .with_("author_id", "comments.author_id", "tags")
        .latest()
        .limit(20)
        .get()
)

for p in posts:
    print(p.author_id.name)            # 0 extra queries — cache hit
    for c in p.comments:               # 0 extra queries — bucket hit
        print(c.author_id.name)        # 0 extra queries — cache hit
```

**How it works**, by relation type:

- **Many2one prefetch.** Bulk-load the FK column for all parent ids
  (`_read([fk])`), collect the referenced co-model ids, bulk-load every
  field the consumer will read on the co-model (`_read(...)`). All
  reads land in `env.cache`, so the descriptor in `fields.py` hits
  cache on access — zero new code paths in core.

- **One2many prefetch.** This one is harder because today
  `One2many.__get__` (in `pyvelm/fields.py:348`) re-queries every time
  — there is no per-parent cache. Two options:

  1. **Sidecar map (zero core changes).** The eager loader stashes
     `env._vellum_o2m_cache[(parent_model, parent_id, field_name)]`
     and the eager-fetched recordset uses a per-instance override of
     `__getattr__` to consult it before falling through to the
     descriptor. **Downsides:** brittle, breaks if any non-vellum
     code accesses the same field, doesn't help across model
     boundaries.
  2. **Small core hook (~5 lines).** Teach `One2many.__get__` to
     consult `env.cache` for a tuple-of-ids stored under
     `(parent_model, parent_id, field_name)` if present, and have the
     eager loader populate that key. This is a clean,
     framework-wide cache and benefits non-vellum code too. The
     descriptor invalidates on `notify_changed` for the inverse FK
     just like a stored field.

  **Recommendation: option 2.** It's the right place architecturally
  and it's tiny. It would land as part of Slice B with its own test.
  Flagged here as the only **core change** the Vellum veneer wants.

- **Many2many prefetch.** Single bulk `SELECT col1, col2 FROM
  <relation> WHERE col1 IN (...)`, group by parent id, cache like the
  One2many case. Same core hook benefits both.

**Dotted paths.** `with_("comments.author_id")` recurses — after
fetching all comments for all parents, treat that flat comment
recordset as a new parent set and run the Many2one prefetch for
`author_id`. Cycles are detected by tracking visited `(model, field)`
pairs.

### 7.3 `with_count`

```python
Post.query(env).with_count("comments").get()   # each post gets ._comments_count
```

Implemented via a single grouped-by-inverse-FK SQL aggregation; the
results stash into a sidecar dict on the recordset (we can't add a
field — it'd require a migration). Exposed via a `count_of(name)`
method to keep it explicit, since `post._comments_count` would look
like a real field but isn't.

### 7.4 Slice B footprint

- ~5 new files: `relations.py`, `eager.py`, `__init__.py` re-exports updates.
- ~500 LoC + tests.
- **One small core change**: 5-line addition to `One2many.__get__`
  (and same to `Many2many.__get__`) to read from `env.cache` when a
  tuple-of-ids is present. Worth its own PR even if Slice B doesn't
  ship; the speedup helps all of pyvelm.
- Lands as the second PR.

## 8. Slice C — Scopes, accessors/mutators, events

### 8.1 Scopes

`@scope` marks a method as a query modifier that becomes available as a
chainable on the builder.

```python
class Post(Vellum, BaseModel):
    @scope
    def published(qb):
        return qb.where_not_null("published_at")

    @scope
    def by_author(qb, author):
        return qb.where("author_id", author.id if hasattr(author, "id") else author)

Post.query(env).published().by_author(some_user).get()
```

**Implementation:** `@scope` tags the function with `__pyvelm_scope__ =
True`. At class creation, the Vellum mixin collects them into a
`_scopes: dict[str, callable]`. `QueryBuilder.__getattr__` dispatches
unknown attributes through `_scopes`.

### 8.2 Accessors and mutators

```python
class User(Vellum, BaseModel):
    _name = "res.users"
    name = Char()

    def get_display_name_attribute(self) -> str:
        # Synthetic attribute — no column.
        return f"{self.name} <{self.login}>"

    def set_login_attribute(self, value: str) -> str:
        return value.strip().lower()
```

- **Accessors** (`get_<X>_attribute`) make `user.display_name` work
  even when no field `display_name` exists. Implemented by adding a
  Python `__getattr__` on the Vellum mixin that, on miss, checks for
  a `get_<X>_attribute` method.
- **Mutators** (`set_<X>_attribute`) transform a value on write.
  Implemented by wrapping `BaseModel.write` and `BaseModel.create` in
  the mixin and routing each (field, value) through the mutator
  registry before reaching `_split_vals`.

Both are discovered at `__init_subclass__` so the lookup is `O(1)` at
runtime.

### 8.3 Events

```python
class Post(Vellum, BaseModel):
    @on("creating")
    def _slugify(self):
        if not self.slug:
            self.slug = slugify(self.title)

    @on("updated")
    def _bump_version(self):
        # Fired after write commits.
        ...
```

Eight events, matching Laravel: `creating`, `created`, `updating`,
`updated`, `saving`, `saved`, `deleting`, `deleted`. Plus the
already-existing automation triggers (`on_create`, `on_write`,
`on_unlink`) keep working — they fire alongside.

**Hookpoint.** The Vellum mixin overrides `create / write / unlink`
on the model class:

```python
def create(self, vals):
    vals = self._apply_mutators(vals)
    vals = self._apply_fillable(vals)
    dispatcher.fire(self.env, self._name, "creating", self.browse([]))
    dispatcher.fire(self.env, self._name, "saving", self.browse([]))
    rec = super().create(vals)
    dispatcher.fire(self.env, self._name, "created", rec)
    dispatcher.fire(self.env, self._name, "saved", rec)
    return rec
```

Zero core changes. `AutomationEngine.fire` still runs from the
`BaseModel` parent class, so DB-defined `base.automation` rules
continue to fire — Vellum events are an **in-code** additional
hook, not a replacement.

### 8.4 Slice C footprint

- ~3 new files: `scope.py`, `attribute.py`, `events.py`.
- ~200 LoC + tests.
- **Zero core changes.**

## 9. Slice D — Mass assignment + soft deletes

### 9.1 Mass assignment

```python
class Post(Vellum, BaseModel):
    _fillable = ["title", "body", "author_id"]
    # OR:
    # _guarded = ["id", "created_at", "internal_flag"]

# OK
post = Post.query(env).create({"title": "Hi", "body": "Hello"})

# Filtered (silently drops 'internal_flag') or raises depending on policy
post = Post.query(env).create({"title": "Hi", "internal_flag": True})
```

- `_fillable` and `_guarded` are mutually exclusive — declaring both
  is an error at class creation.
- Default behavior is to **silently drop** disallowed keys (Laravel
  default). An `_strict_fillable = True` flips to **raise**.
- A `fill(vals)` instance method does the same filtering and then
  calls `write` — useful for partial-update endpoints.

### 9.2 Soft deletes

```python
class Post(Vellum, BaseModel, SoftDeletes):
    _name = "blog.post"
    _soft_delete_column = "deleted_at"   # default

Post.query(env).get()                   # excludes soft-deleted
Post.query(env).with_trashed().get()    # includes them
Post.query(env).only_trashed().get()    # ONLY soft-deleted
post.delete()                            # sets deleted_at = now()
post.restore()                           # nulls deleted_at
post.force_delete()                      # actual unlink
```

- `SoftDeletes` adds a `deleted_at = Datetime()` field by default —
  but adding a field on an opt-in mixin means **adding a column to an
  existing table**. We piggyback on the `db autogen` flow: the
  developer who flips a model to `SoftDeletes` runs `pyvelm db autogen
  <module>` and the migration drops in.
- Alternative: support reusing an existing `active` Boolean instead of
  `deleted_at`. Set `_soft_delete_column = "active"` and the mixin
  reads from / writes to it. This avoids the migration cost for models
  that already follow the `active` convention.
- The QueryBuilder applies a default scope `where("deleted_at", "=",
  None)` (or `where("active", "=", True)` in the alternative mode);
  `with_trashed()` removes it; `only_trashed()` flips it.

### 9.3 Slice D footprint

- ~2 new files: `soft_delete.py` + extend `query.py` for the default
  scope plumbing.
- ~200 LoC + tests.
- **Zero core changes**, but soft-delete adopters pay a migration to
  add `deleted_at`.

## 10. Slice E — Migration DSL (optional, deferred)

```python
from pyvelm.vellum.schema import Schema

def migrate(env):
    Schema.create("blog_post", lambda t: (
        t.id(),
        t.string("title").not_null(),
        t.text("body"),
        t.belongs_to("res_users", as_="author"),
        t.integer("views").default(0),
        t.timestamps(),
    ))
```

This is the one feature where Laravel Eloquent has a clear edge over the
current `env.conn.execute("CREATE TABLE ...")` style. **But** pyvelm
already has:

- `db autogen` (waves additive migrations automatically),
- working hand-written migrations,
- the entire `BaseModel._setup_table` DDL path.

Recommendation: **defer Slice E** until we have a reason. It would
only help one developer audience (people writing migrations by hand
who want fluent DSL), and the autogen path covers most of that.

## 11. What changes in core, total

If we ship A → B → C → D:

| Slice | Core changes |
|---|---|
| A | none |
| B | 5–10 lines: `One2many.__get__` and `Many2many.__get__` consult `env.cache` for a tuple-of-ids before re-querying |
| C | none |
| D | none |

The Slice B change is **worth doing on its own** — it's an unambiguous
win for any pyvelm code that re-reads the same `One2many` more than
once in a request.

## 12. Decisions to confirm before coding

1. **Module location.** Confirmed: bundled at `pyvelm/modules/vellum/`.
2. **`with_` core hook.** Land the `One2many` / `Many2many` cache hook
   in core as its own PR before Slice B, or batch it with Slice B?
   **Recommendation:** its own PR — it stands on its own merit.
3. **Field/method name collision policy.** Reject at class-creation
   time with a clear error message? Or silently let the method win?
   **Recommendation:** reject.
4. **Default mass-assignment policy.** Silently drop disallowed keys
   (Laravel default) or raise? **Recommendation:** drop, with
   `_strict_fillable = True` to raise.
5. **Soft-delete column.** Default to `deleted_at` (Datetime, Laravel
   default) or reuse `active` (Boolean, pyvelm convention)? Or
   support both (the model picks)? **Recommendation:** support both
   via `_soft_delete_column`, default `deleted_at`.
6. **Builder mutability.** Immutable builders (Laravel-style) or
   mutate-in-place? **Recommendation:** immutable — matches Laravel
   and is easier to reason about with shared references.
7. **Where do `with_count` results live?** As a sidecar dict on the
   recordset (not a field) — confirm OK to expose via
   `recordset.count_of(name)` rather than attribute access.
8. **What does `Post.query(env).first()` return for an empty result?**
   Empty recordset (pyvelm style) or `None` (Laravel style)?
   **Recommendation:** empty recordset — keeps every Vellum return
   value compatible with the rest of pyvelm. `.first_or_fail()`
   raises.

## 13. Phasing & PR plan

| PR | Scope | LoC est. | Risk |
|---|---|---|---|
| 1 | Slice A — QueryBuilder + collection helpers | ~400 | low |
| 2 | Core: One2many/Many2many cache hook | ~30 | low–med |
| 3 | Slice B — relationships + eager loading (depends on PR 2) | ~500 | med |
| 4 | Slice C — scopes + accessors/mutators + events | ~200 | low |
| 5 | Slice D — mass assignment + soft deletes | ~200 | med |
| 6 | Slice E — migration DSL | ~300 | low, deferred |

Each PR ships with a test module under
`pyvelm/modules/vellum/tests/` exercising a representative model
(`vellum_demo_post`, `vellum_demo_user`) — same pattern the rest
of the framework uses for in-tree tests.

## 14. Open questions to flag in review

- Does the team want **soft delete to count as a deferred decision**
  (since it carries a migration cost) and ship A/B/C only first?
- Do we want a **Laravel-style query log** (per-env list of compiled
  SQL strings) to land alongside Slice A? Small, useful in tests, no
  user-facing impact otherwise.
- Are there any **fields the user might want to alias** under accessor
  rules (e.g. `get_email_attribute` lowercase-normalises every read)?
  If yes, we need to think about whether the cache stores the raw or
  the accessor-transformed value (recommendation: store raw, transform
  on read, since other Python code is the only path that hits the
  cache directly and we'd surprise it otherwise).
- `force_delete()` vs `unlink()`: should `Vellum.unlink()` route to
  `force_delete` (hard delete) or `delete` (soft delete on
  SoftDeletes-bearing models)? **Recommendation:** the existing
  `unlink()` always hard-deletes; SoftDeletes adds `delete()` and
  `restore()` as new verbs.
