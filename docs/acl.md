# Access control & authentication

Stage 5 introduces a four-model security layer (`res.groups`,
`res.users`, `ir.model.access`, `ir.rule`) and wires it through the
ORM and HTTP boundary. Until Stage 5 every ORM call was effectively
superuser; with Stage 5 every CRUD operation goes through an access
check, and `search`/`search_count` additionally AND-inject record-rule
domains scoped to the active user.

For the rationale, see
[architecture.md](architecture.md#stage-5-access-control).

## The four models

| Model | Purpose |
|---|---|
| `res.groups` | Named groups (e.g. `Admin`, `Partner Manager`). Has an M2m `user_ids` back-reference. |
| `res.users` | Login, bcrypt password, `active` flag, `group_ids` M2m. The `password` field is a `Char` subclass that bcrypt-hashes on assignment; verification goes through `user.check_password(plain)`. |
| `ir.model.access` | Per-`(model, group, perm)` CRUD bits. `group_id=None` means "applies to everyone, including unauthenticated." Same convention as Odoo's `group_id=False`. |
| `ir.rule` | Per-`(model, group, perm)` domain filter. `domain` is JSON-encoded; `{"placeholder": "uid"}` substitutes the current user's id at query time. |

The superuser is hard-coded at `uid=1` and bypasses both
`ir.model.access` and `ir.rule`. The convention matches Odoo's
`SUPERUSER_ID`. The base module's install hook creates the Admin
group and a user with `login="admin"`, `password="admin"`, in that
group, as the first INSERT — so SERIAL hands out id=1.

## Enforcement points

Every model CRUD method checks before doing work:

- `search` / `search_count` — `check_access(model, "read")` then
  `collect_record_rules(model, "read")`, AND-ing the resulting leaves
  into the user's view.
- `_read` (field-level lazy load) — `check_access(model, "read")`.
  Cached on the env so every cell render isn't a fresh lookup.
- `create` — `check_access(model, "create")`.
- `write` — `check_access(model, "write")`.
- `unlink` — `check_access(model, "unlink")`.

Failure raises `PermissionError`. The HTTP layer's exception handler
maps that to a 401 (anonymous, with `WWW-Authenticate: Basic`) or 403
(authenticated but denied).

The env carries:

- `env.uid` — the active user's id, or `None` for unauthenticated.
- `env.is_superuser()` — short-circuit for uid=1.
- `env.user_group_ids` — cached set of group ids the user belongs to.
- `env.check_access(model, perm)` — raise on denial; bypassed when
  `env._acl_bypass` is set (used during ACL self-lookups to avoid
  infinite recursion).
- `env.collect_record_rules(model, perm)` — return resolved domain
  leaves to AND-inject into a search.
- `env._access_cache` — `(model, perm) -> bool` decisions, keyed
  per env instance.

## HTTP authentication

`create_app(registry, pool)` ships HTTP Basic auth out of the box. The
`get_env` dependency reads `Authorization: Basic ...` from each
request, validates against `res.users.login` + bcrypt, and sets
`env.uid` accordingly. No header / bad credentials → `env.uid = None`.

There are no session cookies yet. Every request re-validates against
the password hash; bcrypt's per-call cost (~100ms on default work
factor) is the rate limiter against credential stuffing. Production
should add session cookies + a real rate limiter; that's Stage 5.B.

## Anonymous access

`uid=None` requests are NOT denied wholesale — they pass through
`check_access`, which looks for `ir.model.access` rows with
`group_id IS NULL` granting the requested perm. So a module can opt
specific models into public read by inserting such rows. The example
does this for `res.country` and `res.region` so the demo's form
view's Many2one dropdowns can populate without auth.

## Record rules

`ir.rule.domain` is a JSON-encoded list of `[attr, op, value]` leaves
(same shape the domain compiler already accepts). The `value` can be
a literal or a placeholder dict that resolves at query time:

```python
# In an install hook:
Rule.create({
    "name": "PM: only my partners",
    "model": "res.partner",
    "group_id": pm.id,
    "perm_read": True,
    "perm_write": True,
    "domain": json.dumps([
        ["owner_id", "=", {"placeholder": "uid"}],
    ]),
})
```

At search time, `env._resolve_rule_leaves` substitutes the
placeholder with `env.uid`. The current placeholder vocabulary is
`uid` / `user_id` only; extending it means adding entries in
`_resolve_rule_leaves`.

### Rule combination semantics

All rules for the active user's groups, plus all global rules
(`group_id IS NULL`), are **AND-ed** together. This is stricter than
Odoo's "rules within a group are OR-ed, rules across groups are
AND-ed" — chosen here for simplicity. Refining to Odoo's exact
semantics is a Stage 5.B item if it bites a real use case.

## Example: the demo's three identities

The example seeds three identities the smoke test exercises:

| Identity | Auth | Group(s) | Can read partners? | Can write? | Can create / unlink? |
|---|---|---|---|---|---|
| `admin` | `admin:admin` | `Admin` (uid=1 → superuser) | All | All | All |
| `manager` | `manager:manager` | `Partner Manager` | Active partners only (record rule) | Yes | No |
| anonymous | — | — | No (401) | No (401) | No (401) |

Anonymous can still read countries / regions because the partners
install hook grants public read on those (group_id=None).

## What's deliberately not here

- **Session cookies + a login UI**. Stage 5.B. HTTP Basic is enough
  for the demo and machine-to-machine clients; humans want a form
  login + cookie.
- **Rate limiting / lockout**. Bcrypt's per-call cost is the only
  brake. Production needs a real limiter (in front of `get_env` or
  via middleware).
- **`pyvelm.web` form integration with the user table**. The list /
  form / kanban renderers don't know about `res.users` yet; they
  render it like any other model. Operator UIs for user management
  come with the admin module slice.
- **Field-level ACL**. Per-(model, group, field) grants are a real
  Odoo feature; we don't implement them yet. Workaround: split
  sensitive fields into their own model linked by Many2one.
- **`with_user(user_id)` context manager** for running a block as
  another user. Easy to add when needed.
- **Granular Odoo-style rule combination** (within-group OR,
  across-group AND).
