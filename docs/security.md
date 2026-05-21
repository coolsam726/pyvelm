# Security

Every CRUD operation goes through an access check, and every search
AND-injects the active user's record-rule domain. There's no
"unguarded" mode — even unauthenticated requests pass through the
same machinery, they just see whatever's granted to the "everyone"
bucket.

This page covers what the framework gives you (the four security
models) and how to use them.

## The four models

| Model | Purpose |
|---|---|
| `res.groups` | Named groups (Admin, Partner Manager, Sales). Has a back-reference `user_ids` to the members. |
| `res.users` | Login, bcrypt-hashed password, `active` flag, `group_ids` membership. |
| `ir.model.access` | Per-`(model, group, perm)` CRUD bits — read / write / create / unlink. `group_id=None` means "applies to everyone." |
| `ir.rule` | Per-`(model, group, perm)` **domain filter** that restricts which rows the group can see / change. |

The superuser is hard-coded at **uid=1** and bypasses both
`ir.model.access` and `ir.rule`. The base install hook creates the
Admin group + a user with `login="admin"`, `password="admin"`, in
that group, as the first INSERT — so SERIAL hands out id=1.

## Granting access to a model

Access checks happen on every `search` / `read` / `create` / `write` /
`unlink`. If no `ir.model.access` row grants the requested perm, the
operation raises `PermissionError`. The HTTP layer turns that into
**401** for unauthenticated clients (with a `WWW-Authenticate: Basic`
header) and **403** for authenticated-but-denied.

Module install hooks are the conventional place to seed the access
rows:

```python
# crm/hooks.py
def install(env):
    Access = env["ir.model.access"]
    Group = env["res.groups"]
    admin = Group.search([("name", "=", "Admin")])
    admin.ensure_one()

    Access.create({
        "name": "Admin/crm.lead",
        "model": "crm.lead",
        "group_id": admin,
        "perm_read": True,
        "perm_write": True,
        "perm_create": True,
        "perm_unlink": True,
    })
```

For public read access (e.g. country dropdowns on a signup form),
use `group_id=None`:

```python
Access.create({
    "name": "Public/res.country",
    "model": "res.country",
    "group_id": None,
    "perm_read": True,
})
```

## Restricting which rows a group sees

Record rules narrow `search` and `_read` with a per-group domain
filter. A common pattern: "Partner Manager sees only active
partners owned by them."

```python
import json
Rule = env["ir.rule"]
Rule.create({
    "name": "PM: own active partners",
    "model": "res.partner",
    "group_id": pm.id,                  # the Partner Manager group
    "perm_read": True,
    "perm_write": True,
    "domain": json.dumps([
        ["active", "=", True],
        ["owner_id", "=", {"placeholder": "uid"}],
    ]),
})
```

The `{"placeholder": "uid"}` substitutes the active user's id at
query time. The current vocabulary is `uid` (and its alias
`user_id`); extending it requires adding entries in
`Environment._resolve_rule_leaves`.

### How rules combine

All rules that apply to the active user (group rules for the user's
groups + global rules with `group_id=None`) are **AND-ed** together.
This is stricter than Odoo's "OR within a group, AND across groups"
behaviour — chosen here for simplicity. Refining to Odoo's exact
semantics is on the list.

## Multi-company scoping

A model can opt into automatic per-company filtering by setting
`_company_scoped = True` and exposing a `company_id` field:

```python
class Partner(BaseModel):
    _name = "res.partner"
    _company_scoped = True
    company_id = Many2one("res.company", ondelete="SET NULL")
```

When `env.company_id` is set, the framework injects
`("company_id", "=", env.company_id)` into every search. The
`pyvelm_company` cookie + the company switcher in the topbar
drive the env value.

`res.users` is **not** company-scoped on purpose — users carry a
home `company_id` but stay globally visible so an admin in one
company can manage users in another from the same screen.

## How users sign in

The framework supports two authentication paths and both can be
active at once:

| Mode | When used |
|---|---|
| **HTTP Basic** | Machine clients calling `/api/*`. Each request re-validates against bcrypt. |
| **Session cookie** | Browsers. POST `/login` validates credentials, mints a 32-byte token, sets the `pyvelm_session` cookie. Subsequent requests resolve `env.uid` from the cookie. |

`POST /logout` deletes the session cookie and revokes the token.
The browser session cookie wins when both are present.

`/login` is rate-limited at 5 attempts per 5 minutes per client IP;
the 6th attempt returns 429 with a `Retry-After` header.

## What's deliberately not here

- **Field-level ACL.** Per-`(model, group, field)` grants are an
  Odoo feature pyvelm doesn't implement yet. The workaround is to
  split sensitive fields into their own model linked by Many2one.
- **Session-token rotation on password change.** Old sessions stay
  valid until the cookie expires. On the list.
- **`with_user(user_id)` context manager** for running a block as
  another user. Cheap to add when needed.

??? note "Why every search injects the domain"
    Adding the rule filter at the `search`/`search_count` level
    (rather than post-filtering after fetch) means the rule scales
    with the query. A 10-million-row table with a strict rule
    fetches only the rows the user can see — Postgres uses the
    same index it would use for an unrestricted query.
