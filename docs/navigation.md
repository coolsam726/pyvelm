# Shell navigation

The signed-in web UI (`layouts/main.html`) builds navigation from
`ir.ui.menu` rows contributed by each module's `MENUS` list. The same
tree powers two **layout modes**; switch globally with `PYVELM_MENU_LAYOUT`
or per company on `res.company.menu_layout` (see below).

## Layout modes

| Mode | Env value | Sidebar (desktop) | Top bar (desktop) | Mobile drawer |
|------|-----------|-------------------|-------------------|---------------|
| **Apps** (default) | `apps` | Root applications only | Subsections for the active app | Full nested tree |
| **Deep sidebar** | `sidebar` | Section headings + nested links (up to three levels) | Chrome only | Same as desktop |

```bash
# Default — omit the variable or set explicitly
PYVELM_MENU_LAYOUT=apps

# Classic nested sidebar (Filament / VS Code style)
PYVELM_MENU_LAYOUT=sidebar
```

Restart the app process after changing the variable. Invalid values fall
back to `apps`.

### Per-company override

Each `res.company` record has an optional **Navigation Layout** field
(`menu_layout`). When set to `apps` or `sidebar`, users in that company
see that layout for every signed-in request. When left empty (**Default
(env var)**), the global `PYVELM_MENU_LAYOUT` value applies.

Configure on each company under **Settings → Organization → Companies**
(open a company → **Branding & white-label** → **Navigation Layout**).
Resolution order:

1. Per-request override from the active company's `menu_layout` (when non-empty)
2. Global `PYVELM_MENU_LAYOUT` environment variable
3. Hard default: `apps`

The active company's layout is resolved in **`base.web`** middleware on each
authenticated request (session cookie + company cookie) and stored in a
`ContextVar` until the response completes. Custom code or tests can set it
directly:

```python
from pyvelm.menu import menu_layout, reset_request_menu_layout, set_request_menu_layout

token = set_request_menu_layout("sidebar")
try:
    assert menu_layout() == "sidebar"
finally:
    reset_request_menu_layout(token)
```

> **Note:** `PYVELM_MENU_LAYOUT=odoo` is still accepted as an alias for
> `apps` for older deployments; prefer `apps` in new configuration.

### Apps layout (`apps`)

Best for ERP shells with many top-level applications (CRM, Inventory,
Settings).

1. **Left rail** — one row per root menu entry (Dashboard, CRM,
   Settings, …). Icons use the same [Heroicons](modules.md#sidebar-menus)
   names as root groups.
2. **Top bar** — level-2 subsections for the active app (e.g.
   **Organization**, **Users & access** under Settings). Subsections
   with level-3 children open a **dropdown** (toggle on click); flat
   subsections without children are plain links.
3. **Single-page roots** (e.g. Dashboard with no children) — the app
   name appears in the top bar; the sidebar link still navigates to the
   root `href`.

Clicking a root without its own `href` opens the first reachable page
in that application's subtree.

#### Top-bar dropdowns

| Behavior | Detail |
|----------|--------|
| Default state | **Closed** on every page load |
| Open | Click the subsection label (chevron rotates) |
| Close | Click the same label again (toggle) |
| After navigation | Full page reload — menus start closed again |

Dropdowns do not use click-outside or link-click handlers; navigation
already resets the shell.

The header sits outside the main column's `overflow-x-hidden` region so
panels are not clipped under the top bar.

#### Mobile (`apps` layout)

On viewports below the `md` breakpoint (~768px), navigation adapts
without a separate env var:

| Surface | Behavior |
|---------|----------|
| **Top bar** | Hamburger, **active app name** (truncated), user/company chrome — no subsection strip |
| **Menu drawer** | Full **sidebar-style** nested tree (all apps and pages, vertical scroll) |

Desktop keeps the app rail plus top-bar subsections. The drawer uses the
same three-level tree as `sidebar` layout so phones never rely on
horizontal top-bar scrolling.

### Deep sidebar (`sidebar`)

Best when you want every page visible in one scrollable column.

| Tree level | Presentation |
|------------|----------------|
| Root group (no `href`) | Uppercase **section subheading** |
| Root link (has `href`, no children) | Top-level nav link (Dashboard, Apps) |
| Level 2 with children | Collapsible group (`<details>`) |
| Level 3 | Indented links under the level-2 group |

## Declaring menus

See [Modules → Sidebar menus](modules.md#sidebar-menus) for the
`Menus` builder, `m.group`, `m.item`, icons, and cross-module parents.

### Depth and authoring convention

`parent_id` on `ir.ui.menu` supports **unlimited depth**. Both layouts
read the full tree from `pyvelm.menu.build_menu_tree`.

**Recommended shape** for ERP modules:

| Level | Purpose | Count |
|-------|---------|-------|
| **1** | Application (`m.group` + `icon`) | One per functional area |
| **2** | Subsection (`m.group` + `parent`) | A few per app (top-bar tabs / dropdowns) |
| **3** | Page (`m.item` + `view` / `href`) | Most list/form routes |

**Apps layout** — keep level 2 sparse (typically 2–4 subsections per
app). Hang **pages** at level 3. Putting many `m.item` entries directly
under a level-1 app clutters the top bar.

**Sidebar layout** — same data model; renders as section → group → link.

#### Shipped examples (reference)

| App (L1) | L2 subsections | Notes |
|----------|----------------|-------|
| **Settings** | Organization, Users & access, Reference data | `admin` module |
| **Security** | Permissions | Model access, Record rules |
| **Workflows** | Operations, Configuration, Messaging | Inbox/design from `workflow`; compose from `mail_compose` |
| **CRM** | Pipeline, Analytics | Example module |
| **Reports** | Builder, Catalog | |
| **Feedback signals** | Overview, Collect, Analyze | Demo module |
| **Business** | Directory | Partners; Tags under Settings → Reference data |

#### Example — Settings (admin)

```python
m = Menus("admin")

MENUS = [
    m.group("settings", "Settings", icon="cog-6-tooth", sequence=80),
    m.group("settings.organization", "Organization",
            parent="settings", sequence=10),
    m.item("settings.companies", "Companies",
           parent="settings.organization", view="company.list", sequence=10),
    m.item("settings.currencies", "Currencies",
           parent="settings.organization", view="currency.list", sequence=20),
    m.group("settings.access", "Users & access",
            parent="settings", sequence=20),
    m.item("settings.users", "Users",
           parent="settings.access", view="user.list", sequence=10),
    m.item("settings.groups", "Groups",
           parent="settings.access", view="group.list", sequence=20),
]
```

| Layout | What the user sees |
|--------|-------------------|
| `apps` | Rail: **Settings**. Top bar: **Organization** ▾, **Users & access** ▾ |
| `sidebar` | Section **Settings** → subsections → page links |

### Parent references

Menu **names** may contain dots (`settings.organization`). A string
`parent` is always the **menu name** in the declaring module, not a
`module.name` pair:

| You write | Stored as |
|-----------|-----------|
| `parent="settings"` | `admin.settings` |
| `parent="settings.organization"` | `admin.settings.organization` |
| `parent=("admin", "workflows.operations")` | `admin.workflows.operations` |

Cross-module parents must use the `(module, name)` tuple.

The loader upserts parents before children (`_menu_sync_order` in
`pyvelm.loader`) so three-level trees install in one pass.

After editing `views/menu.py`, run **Apps → Sync** on affected modules
(or `pyvelm db migrate` on a dev database) so `ir.ui.menu` picks up
changes.

## Access control

Menu visibility uses the same rules as before; see
[Security → Sidebar menus](security.md#sidebar-menus).

- View-backed entries need **read** on the view's model (inferred from
  `href` or set with `model=`).
- Use `policy=` (e.g. `view_any`) when ACL alone is too coarse.
- Empty groups are removed; in `apps` mode an application with no visible
  children still appears if the root itself has an `href`.

### `dev_only`

Pass `dev_only=True` on `m.item(...)` or `m.group(...)` to hide an entry
unless `PYVELM_ENV=development`. Used by the bundled
[`technical` module](modules.md) to expose `ir.ui.menu` / `ir.ui.view` /
`ir.attachment` editors during development without leaking them into
production sidebars (the install hook may have granted the underlying
ACL, but the menu entry itself stays hidden). Combine `dev_only=True`
with `perm=` + `model=` so even in development, non-admin developers
don't see the editors.

```python
m.group(
    "technical", "Technical", icon="wrench-screwdriver",
    sequence=900, dev_only=True,
)
m.item(
    "technical.ui.menus", "Menu entries",
    parent="technical", view="technical.menu.list",
    perm="write", model="ir.ui.menu", dev_only=True,
)
```

## Template context

`pyvelm.render.layout_context` merges keys from
`pyvelm.menu.menu_layout_context`:

| Key | Always | `apps` only |
|-----|--------|-------------|
| `menu` | Full filtered tree | |
| `menu_layout` | `"apps"` or `"sidebar"` | |
| `menu_roots` | | Enriched roots (`nav_href`, `root_index`) |
| `menu_active_root` | | Active application node |
| `menu_active_root_index` | | Index into `menu_roots` |
| `menu_secondary` | | Top-bar items (children of active root) |

Templates under `pyvelm/templates/layouts/`:

| File | Role |
|------|------|
| `_nav_apps_roots.html` | Application rail (desktop `apps` layout) |
| `_nav_topbar_secondary.html` | Subsections + dropdowns for active app |
| `_nav_sidebar.html` | Deep sidebar (`sidebar` layout and mobile drawer) |

Account and public pages set `use_sidebar = false` and skip this
machinery.

## Python API

```python
from pyvelm.menu import (
    MENU_LAYOUT_APPS,
    MENU_LAYOUT_SIDEBAR,
    build_menu_tree,
    menu_layout,
    menu_layout_context,
    find_menu_entry,
)

tree = build_menu_tree(env, current_path="/web/views/crm/lead.list")
ctx = menu_layout_context(tree, current_path, layout=MENU_LAYOUT_SIDEBAR)
parent, leaf = find_menu_entry(tree, "/web/views/crm/lead.list")
```

For a future per-company or per-user layout, pass `layout=` into
`menu_layout_context` from your own `layout_context` wrapper; the env
var remains the global default.

## Related configuration

- [White-label branding](branding.md) — app name and logos in the
  sidebar header
- [Site entry](getting-started.md) — `PYVELM_HOME_URL` for the Home
  breadcrumb and post-login redirect
- [Modules](modules.md#sidebar-menus) — `MENUS` builder reference
