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
header) and **403** for authenticated-but-denied. Browser navigations
get the rendered **Access denied** page (the app shell with a clear
message); API / HTMX callers get the plain-text status. Unauthenticated
browser requests are bounced to `/login` instead.

Module install hooks are the conventional place to seed the access
rows. Use :func:`pyvelm.security.grant_model_access` so **Admin** gets
full CRUD and the internal **User** group gets at least read (list/form
load without create):

```python
# crm/hooks.py
from pyvelm.security import grant_model_access

def install(env):
    grant_model_access(env, "crm.lead", admin="crud", user="read")
```

The web UI checks each permission separately: list/kanban need **read**
only; the **New** button needs **create**; **Edit** / **Save** need
**write**; **Delete** needs **unlink**. Missing create no longer blocks
the list page.

### Pages open on read; actions hide on their own perm

The guiding rule for the web layer is **read gets you the page, and
every action you can't perform is hidden — not rendered-then-denied.**
A read-only user lands on the list, kanban, and record-display pages
without a single `403`; the framework simply omits the buttons they
can't use (New, Edit, Delete, the row **Design** link, etc.).

### Sidebar menus

The **sidebar and top-bar menus** follow the same idea (see also
[Navigation](navigation.md)): a menu entry that points at a view is
shown only when the user can **read** (list) that view's model, and a
group with no reachable children is dropped entirely. Home/Apps aren't
model-backed, so they always show. Superuser sees the full tree.

**Policies** are the preferred gate when ACL alone is too coarse — for
example everyone gets read on `res.users` for the shell, but only
**Admin** should see Settings → Users. Register a policy class for the
model, then name the method on the menu:

```python
# hooks.py (or rely on built-in framework policies registered at boot)
from pyvelm.policy import register_policy
from pyvelm.policies.management import AdminManagementPolicy

register_policy("res.users", AdminManagementPolicy)

# menu.py
m.item("settings.users", "Users", parent="settings.access",
       view="user.list", policy="view_any")
```

Evaluation order: ACL ceiling (`perm`, default `read`) then
`env.can(model, policy)`. Built-in management models use
`AdminManagementPolicy.view_any` (Admin group). Workflow inbox uses
`WorkflowApprovalPolicy.inbox`; admin approval lists use `view_any`.

Custom feature pages (a menu with an `href` that isn't `/web/views/…`)
have no model to infer, so gate them with `model=` + `policy=` and/or
`perm=`:

```python
m.item("reports.build", "Design a report", parent="reports",
       href="/web/reports/build", model="ir.report",
       perm="create", policy="create")
```

On a `view=` entry the model is inferred from the view. A custom `href`
with `policy` or `perm` **must** also name the `model`.

Custom **header actions** on a form join the same scheme. Declare the
permission a button needs and it disappears for users who lack it:

```python
form_view("cron.form", "ir.cron",
    header_actions=[
        {"label": "Run Now", "url": "/web/cron/{id}/run-now",
         "method": "POST", "perm": "write"},
    ],
    sections=[...],
)
```

`perm` is one of `read` / `write` / `create` / `unlink`; add `model`
to check a different model than the view's own. An action with no
`perm` stays visible to anyone who can read the record — so always
tag buttons that mutate or open a write-only screen. The endpoint
behind the button still enforces its own `check_access`; hiding the
button is a UX layer over that, never a replacement for it.

The **User** group is backfilled once (migration ``0_23→0_24`` on upgrade).
It is **not** re-applied on every Apps Sync or dev-server reload, so you
can remove **User** from an account (e.g. Sales-only operators) without
it coming back. Assign **User** manually in Settings → Users when a new
internal account should get module ``User/…`` read grants.

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

## Bypassing access: sudo mode

Trusted framework or app code sometimes has to touch rows the current
user can't reach — a cross-company lookup, a counter increment, system
bookkeeping. `sudo()` returns a view of the env (or recordset) that
skips every `ir.model.access` check and `ir.rule` domain:

```python
# Env-level: derive a sudo env, then go through it.
companies = env.with_company(None).sudo()["res.company"].search([])

# Recordset-level: the original recordset stays access-enforced.
partner.sudo().write({"credit_limit": 0})
```

`sudo()` **keeps the real `uid`** — audit trails and
`{"placeholder": "uid"}` record rules still attribute to the actual
user; only the enforcement is lifted. Call `sudo(False)` to get back an
enforced view. It's a sibling env sharing the same connection and value
cache, so it composes with `with_context` / `with_company` and the sudo
flag rides along:

```python
env.sudo().with_company(other_co)   # still in sudo mode
```

Reach for sudo deliberately — it is the supported replacement for
poking `env._acl_bypass` by hand, and like `SUPERUSER_ID` it removes
the safety net. Keep the bypassed section as small as the work requires,
then hand normal (non-sudo) recordsets back to caller code.

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

Non-admin operators still need their **own** row for the web shell.
The base module seeds `Everyone/res.users` (read) plus a global
`ir.rule` ``Own user record only`` (`id = uid`). Group names for the
profile page use `Everyone/res.groups` (read). Profile/password writes
still use ACL bypass — only Admin can edit other users.

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
