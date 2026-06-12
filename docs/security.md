# Security

Every CRUD operation in PyVELM goes through access checks. Every `search`
call injects the current user's record-rule domain into the query.

There is no unguarded mode. Unauthenticated requests still pass through the
same system and only see what is explicitly granted to the public bucket.

This guide is organized for practical setup first, then deeper behavior.

## Quick setup checklist

When you create a new module, do these first:

1. Add model ACL rows in your install hook.
2. Add record rules for row-level constraints.
3. Hide write/delete actions behind permission checks in views.
4. Verify behavior with a non-admin user.

Then return to this page for policy gates, sudo patterns, and multi-company
details.

---

## Security models at a glance

PyVELM's security layer is built on four database models that work together:

| Model | Purpose |
|---|---|
| `res.groups` | Named groups such as Admin, Partner Manager, Sales. Has a back-reference `user_ids` listing the members of each group. |
| `res.users` | Holds login credentials (bcrypt-hashed password), an `active` flag, and `group_ids` group membership. |
| `ir.model.access` | Per-`(model, group, perm)` CRUD permission bits — `read`, `write`, `create`, `unlink`. Setting `group_id=None` means the rule applies to everyone, including unauthenticated users. |
| `ir.rule` | Per-`(model, group, perm)` **domain filter** that restricts which rows a group can see or modify. |

### Superuser behavior

The superuser is hard-coded at **uid = 1** and bypasses both
`ir.model.access` and `ir.rule` checks.

The base install hook creates the Admin group and a user with
`login="admin"` / `password="admin"` as the first insert, so sequence
assignment gives it id 1.

Change the admin password immediately in any non-development environment.

---

## Step 1: Grant model access

Access checks run on every `search`, `read`, `create`, `write`, and `unlink` call. If no `ir.model.access` row grants the requested permission, the operation raises a `PermissionError`. The HTTP layer translates this as follows:

- **Unauthenticated browser requests** → redirect to `/login`
- **Unauthenticated API clients** → HTTP 401 with a `WWW-Authenticate: Basic` header
- **Authenticated but denied** → HTTP 403; browsers see a rendered "Access denied" page; API / HTMX callers receive a plain-text status

### Seed ACL rows in your install hook

Module install hooks are the conventional place to create `ir.model.access` rows. Use `grant_model_access()` so the Admin group gets full CRUD and the internal User group gets at least read access (needed to load list and form views):

```python
# crm/hooks.py
from pyvelm.security import grant_model_access

def install(env):
    grant_model_access(env, "crm.lead", admin="crud", user="read")
```

The helper creates the three standard rows (Admin, User, Public) in one call. The `admin="crud"` shorthand grants all four permissions; `user="read"` grants read only.

For public read access — for example, country dropdowns on a public signup form — create a row with `group_id=None`:

```python
Access.create({
    "name": "Public/res.country",
    "model": "res.country",
    "group_id": None,   # applies to everyone, including unauthenticated users
    "perm_read": True,
})
```

### Read opens pages; actions respect their own permissions

The guiding rule for the web layer is: **read access gets the user onto the page, and any action they cannot perform is hidden rather than rendered and then rejected**.

A read-only user lands on list, kanban, and record-display pages without encountering a single 403 error. The framework simply omits the buttons they cannot use:

| Action | Permission required |
|---|---|
| View a list, kanban, or record | `read` |
| The **New** button | `create` |
| The **Edit / Save** button | `write` |
| The **Delete** button | `unlink` |
| Per-row **Design** link | `write` |

Missing `create` no longer prevents a user from loading the list page — it only removes the New button.

### Sidebar menus

Menu entries are shown only when the user has `read` on the model that the menu's view is backed by. A group with no reachable children is pruned entirely from the sidebar. Home and Apps are not model-backed, so they always show. The superuser sees the full tree.

#### Add policy gates when ACL is too coarse

Sometimes a raw ACL grant is too broad. For example, `res.users` needs `Everyone/read` so the shell can resolve user display names — but only Admins should see Settings → Users.

Policies let you attach a named authorization function to a menu item as a second gate, evaluated after the ACL ceiling:

```python
# hooks.py
from pyvelm.policy import register_policy
from pyvelm.policies.management import AdminManagementPolicy

# Register the policy for this model
register_policy("res.users", AdminManagementPolicy)
```

```python
# menu.py
m.item(
    "settings.users",
    "Users",
    parent="settings.access",
    view="user.list",
    policy="view_any",  # only users who pass this policy see this menu item
)
```

**Evaluation order:** ACL ceiling (`perm`, default `read`) is checked first, then `env.can(model, policy)`. Both must pass for the item to appear.

Built-in management models (Settings, Security, workflow admin lists, Apps catalog) use `AdminManagementPolicy.view_any`, which requires the Admin group. The workflow inbox uses `WorkflowApprovalPolicy.inbox`.

#### Custom `href` menu items

For menu items that point to a custom URL rather than a model-backed view, there is no model to infer — so you must name `model=` explicitly alongside `policy=` or `perm=`:

```python
m.item(
    "reports.build",
    "Design a report",
    parent="reports",
    href="/web/reports/build",
    model="ir.report",   # required when using href + policy/perm
    perm="create",
    policy="create",
)
```

On a `view=` entry the model is inferred automatically. A custom `href` with `policy` or `perm` **must** also declare `model`.

#### Gating header actions on a form

Form header action buttons follow the same scheme. Declare the permission a button requires and it disappears for users who lack it:

```python
form_view(
    "cron.form",
    "ir.cron",
    header_actions=[
        {
            "label": "Run Now",
            "url": "/web/cron/{id}/run-now",
            "method": "POST",
            "perm": "write",  # hidden for users without write on ir.cron
        },
    ],
    sections=[...],
)
```

`perm` accepts `read`, `write`, `create`, or `unlink`. Add `model` to check a different model than the view's own. A button with no `perm` stays visible to anyone who can read the record — so always tag buttons that mutate state or open write-only screens.

> **Important:** Hiding a button is a UX convenience layer, not a security boundary. The endpoint the button calls must still enforce its own `check_access`. Never rely on a hidden button as your only authorization check.

### The User group and backfill behaviour

The internal User group is backfilled once during the `0_23 → 0_24` migration and is **not** re-applied on every Apps Sync or dev-server reload. This means you can remove User from an account (for example, a Sales-only operator) and it will not come back on restart. Assign User manually in Settings → Users when a new internal account needs module `User/…` read grants.

---

## Step 2: Use `sudo()` deliberately

Trusted framework or application code sometimes needs to touch rows the current user cannot reach — a cross-company lookup, a counter increment, system bookkeeping. `sudo()` returns an ACL-bypassed view of the environment or a recordset:

```python
# Env-level sudo: derive a bypassed env and work through it
companies = env.with_company(None).sudo()["res.company"].search([])

# Recordset-level sudo: the original recordset stays access-enforced
partner.sudo().write({"credit_limit": 0})
```

### What `sudo()` keeps and drops

- **Keeps** the real `uid` — audit trails and `{"placeholder": "uid"}` rule substitutions still attribute actions to the actual user.
- **Drops** all `ir.model.access` and `ir.rule` enforcement.

Call `sudo(False)` to get back an enforced environment. `sudo()` returns a sibling env sharing the same database connection and value cache, so it composes cleanly with `with_context` and `with_company` — the sudo flag carries along:

```python
env.sudo().with_company(other_co)   # still in sudo mode
```

> **Best practice:** Reach for `sudo()` deliberately and keep the bypassed section as small as the work requires. Hand normal (non-sudo) recordsets back to caller code once the elevated operation is done. `sudo()` is the supported replacement for poking `env._acl_bypass` directly.

---

## Step 3: Restrict visible rows with record rules

`ir.rule` narrows `search` and `read` with a per-group domain filter injected at query time. The filter is applied inside the SQL query — not as post-fetch filtering — so it scales correctly even on large tables.

A common pattern: "Partner Managers see only active partners they own."

```python
import json

Rule = env["ir.rule"]
Rule.create({
    "name": "PM: own active partners",
    "model": "res.partner",
    "group_id": pm.id,      # the Partner Manager group
    "perm_read": True,
    "perm_write": True,
    "domain": json.dumps([
        ["active", "=", True],
        ["owner_id", "=", {"placeholder": "uid"}],  # substituted with the current user's id at query time
    ]),
})
```

The `{"placeholder": "uid"}` value is substituted with the active user's id at query time. Its alias `user_id` works identically. To support additional placeholders, add entries to `Environment._resolve_rule_leaves`.

### Rule combination behavior

All rules that apply to the active user — group rules for every group the user belongs to, plus global rules with `group_id=None` — are **AND-ed** together.

> **Note:** This is stricter than Odoo's behaviour, which OR-s rules within a group and AND-s across groups. PyVELM's simpler AND-everything approach is intentional for now. Refining to Odoo's exact semantics is on the roadmap.

---

## Step 4: Apply multi-company scoping

A model can opt into automatic per-company filtering by setting `_company_scoped = True` and adding a `company_id` field:

```python
class Partner(BaseModel):
    _name = "res.partner"
    _company_scoped = True
    company_id = Many2one("res.company", ondelete="SET NULL")
```

When `env.company_id` is set, PyVELM automatically injects `("company_id", "=", env.company_id)` into every `search` on that model. The active company is driven by the `pyvelm_company` cookie and the company switcher in the top bar.

### Why `res.users` is not company-scoped

`res.users` intentionally does not use `_company_scoped`. Users carry a home `company_id` but remain globally visible so that an admin in one company can manage users across all companies from a single screen.

Non-admin operators still need their own user row for the web shell. The base module seeds `Everyone/res.users (read)` plus a global `ir.rule` called "Own user record only" (`id = uid`) so ordinary users can only read their own record. The Groups model gets `Everyone/res.groups (read)` so profile pages can display group names. Profile and password writes use an ACL bypass — only Admins can edit other users' records.

---

## Authentication flow

PyVELM supports two authentication modes simultaneously:

| Mode | When used |
|---|---|
| **HTTP Basic** | Machine clients calling `/api/*`. Credentials are validated against bcrypt on every request. |
| **Session cookie** | Browsers. `POST /login` validates credentials, mints a 32-byte token, and sets the `pyvelm_session` cookie. Subsequent requests resolve `env.uid` from the cookie. |

When both are present on a request, the browser session cookie takes precedence.

`POST /logout` deletes the session cookie and revokes the server-side token.

### Login rate limiting

`/login` is rate-limited to **5 attempts per 5 minutes per client IP**. The sixth attempt returns HTTP 429 with a `Retry-After` header.

---

## Known gaps

These are known gaps on the roadmap:

**Field-level ACL** — per-`(model, group, field)` grants exist in Odoo but are not yet implemented in PyVELM. The workaround is to move sensitive fields into a separate model linked by Many2one and apply model-level ACL to that model.

**Session-token rotation on password change** — existing sessions remain valid until the cookie expires after a password change. This will be fixed in a future release.

**`with_user(user_id)` context manager** — running a block as a different user is not yet available. It is straightforward to add when needed.

---

## Why record rules run inside the query

PyVELM injects rule domains into `search` and `search_count` rather than filtering results after fetching. This means the rule is evaluated by the database engine, not Python, so it uses the same indexes as an unrestricted query. A table with ten million rows and a strict record rule fetches only the rows the user is permitted to see — with no performance penalty compared to an unrestricted query on a small dataset.