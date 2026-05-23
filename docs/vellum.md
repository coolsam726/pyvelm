# Vellum (optional ORM veneer)

**Vellum** is pyvelm’s **optional** Eloquent-style layer: chainable queries, eager loading, model events,
mass-assignment policy, and soft deletes. It does **not** replace the
core ORM — every Vellum call compiles down to `search`, `write`,
`env.cache`, and the same ACL/company rules as always.

Use it when you want nicer syntax in application code. Skip it when you
prefer `env["model"].search([...])` everywhere; both styles work on the
same models in the same `env`.

For design rationale and slice history, see the
[Vellum design doc](vellum-design.md).

## Bundled module + import path

The wheel ships a marker module `vellum` (dependency: `base`) so the
loader knows the feature is installed. **Import the API from Python:**

```python
from pyvelm.vellum import Vellum, scope, on, SoftDeletes
```

Do **not** name your own scripts `vellum.py` inside a directory on
`sys.path` (e.g. `examples/vellum.py`) — that shadows the bundled
`vellum` package and breaks `import vellum.models`.

## Opt in per model

List **`Vellum` before `BaseModel`** so Python’s MRO uses Vellum’s
`create` / `write` / `unlink` overrides:

```python
from pyvelm import BaseModel, Char, Integer, Many2one
from pyvelm.vellum import Vellum, scope, on


class Post(Vellum, BaseModel):
    _name = "blog.post"

    title = Char(required=True)
    views = Integer(default=0)
    author_id = Many2one("res.users")

    @scope
    def popular(qb):
        return qb.where("views", ">", 100)

    @on("created")
    def _on_created(self):
        # runs after insert; use vals= in creating/saving hooks
        ...
```

Add **`SoftDeletes` last** when you need soft deletes:

```python
from pyvelm.vellum import SoftDeletes

class Post(Vellum, BaseModel, SoftDeletes):
    _name = "blog.post"
    deleted_at = Datetime()   # or _soft_delete_column = "active"
```

### Which class to query?

Models are often extended with `_inherit` in other modules. The
**technical name** on `env` is stable; a Python import from one
`models/` file may be stale after merges.

**Prefer at runtime:**

```python
posts = env.query("blog.post").popular().limit(20).get()
```

`env.query(model_name)` resolves `registry[model_name]` — the same
merged class as `env[model_name].__class__`.

## Query builder (Slice A)

`env.query("blog.post")` returns an immutable `QueryBuilder`. Chain
filters, then terminate:

| Terminator | Result |
|------------|--------|
| `.get()` | Recordset |
| `.first()` | Recordset (0 or 1 rows — **not** `None`) |
| `.find(id)` | Recordset if id matches domain, else empty |
| `.count()` / `.exists()` | `int` / `bool` |
| `.pluck("field")` | `list` |
| `.paginate(page=2, per_page=20)` | `{items, total, page, per_page}` |

Common filters:

```python
env.query("blog.post") \
    .where("author_id", uid) \
    .where("views", ">", 100) \
    .where_in("status", ["draft", "review"]) \
    .where_null("archived_at") \
    .where_any(("status", "=", "draft"), ("status", "=", "review")) \
    .order_by("created_at", "desc") \
    .limit(20) \
    .get()
```

**SQL vs in-memory:** `qb.where(...).get()` hits the database.
On a recordset, `posts.where("status", "draft")` filters **in memory**
only (same name, different layer — like Laravel).

Collection helpers on Vellum recordsets: `.pluck`, `.filter`, `.chunk`,
`.fresh()`, `.to_list()`, etc.

## Eager load and counts (Slice B)

```python
posts = (
    env.query("blog.post")
    .with_("comment_ids", "author_id")
    .with_count("comment_ids")
    .limit(20)
    .get()
)

for p in posts:
    p.count_of("comment_ids")   # from with_count, not a DB column
    for c in p.comment_ids:    # uses cache — no N+1 per parent
        ...
```

Dotted paths work: `.with_("comments.author_id")`.

Method-based relations (alternative to field access):

```python
post = env["blog.post"].browse(post_id)
post.has_many("blog.comment", "note_id").where("approved", True).get()
comment.belongs_to("blog.post", "post_id").get()
```

**Do not** declare a `One2many` / `Many2many` field and a relation
method with the **same name** — class creation raises `TypeError`.
Prefer the field + `with_("comments")`, or a method-only relation.

## Scopes, accessors, events (Slice C)

**Scopes** — chain on the builder:

```python
@scope
def published(qb):
    return qb.where_not_null("published_at")

env.query("blog.post").published().get()
```

**Accessors** — `get_<name>_attribute` exposes synthetic reads:

```python
def get_display_name_attribute(self):
    self.ensure_one()
    return f"{self.title}!"
# post.display_name
```

**Mutators** — `set_<name>_attribute` transforms values on create/write:

```python
def set_title_attribute(self, value):
    return (value or "").strip()
```

**Events** — `@on("creating")`, `"created"`, `"updating"`, `"updated"`,
`"saving"`, `"saved"`, `"deleting"`, `"deleted"`. Handlers receive the
recordset; `creating` / `saving` also get `vals=` for create-time edits.

## Mass assignment (Slice D)

```python
class Post(Vellum, BaseModel):
    # Laravel-style (preferred): everything fillable except listed fields.
    _guarded = ["id", "internal_flag"]
    # Whitelist alternative:
    # _fillable = ["title", "body", "author_id"]
    # _strict_fillable = True   # raise instead of silently dropping keys
```

Vellum models default to `_guarded = ["id", "created_at", "updated_at"]` when you
declare neither policy (timestamp columns are omitted when `_timestamps = False`).
Use `_guarded = ["*"]` to block all mass assignment (whitelist via `_fillable`).

`create`, `write`, `fill(vals)`, and web `parse_form_vals` filter keys before
they reach the ORM.

`_fillable` and `_guarded` are mutually exclusive.

## Automatic timestamps

Vellum models maintain Laravel-style `created_at` and `updated_at` columns
(UTC, stored as naive `timestamp`). Both are set on create; only `updated_at`
changes on write. Disable with `_timestamps = False`, or customize column names
via `_CREATED_AT` / `_UPDATED_AT` (set to `None` to skip one side).

New columns require a migration — run **Apps Sync**, `pyvelm db autogen
<module>`, or hand-write `ALTER TABLE`. Scaffolds and autogenerated views
include `created_at` / `updated_at` on list and form (detail) views by default
(read-only on forms).

## Soft deletes (Slice D)

```python
env.query("blog.post").get()              # hides soft-deleted
env.query("blog.post").with_trashed().get()
env.query("blog.post").only_trashed().get()

post.delete()         # sets deleted_at (or active=False)
post.restore()
post.force_delete()   # real unlink (hard delete)
```

`unlink()` on the model always hard-deletes (pyvelm semantics).
`delete()` is the soft-delete verb when `SoftDeletes` is mixed in.

New columns (`deleted_at`) require a migration — run `pyvelm db autogen
<module>` or hand-write `ALTER TABLE`.

## Example app smoke test

The repo includes `examples/modules/vellum_demo` and a runnable check:

```bash
pip install -e .
cp .env.example .env    # PYVELM_DSN
python examples/vellum_smoke.py
python examples/vellum_smoke.py --reset-vellum   # drop only vellum_demo tables
```

Same module roots as `examples/serve.py` (`BUILTIN_MODULE_ROOTS` +
`examples/modules`). The smoke script does **not** wipe partners/CRM.

## Tests

Unit tests live under `pyvelm/modules/vellum/tests/` (require
`PYVELM_DSN`):

```bash
for f in pyvelm/modules/vellum/tests/test_*.py; do python "$f" -v; done
```

## API reference

See **[pyvelm.vellum](api/vellum.md)** in the API reference for the full
public surface (`Vellum`, `QueryBuilder`, `SoftDeletes`, `scope`, `on`, …).
