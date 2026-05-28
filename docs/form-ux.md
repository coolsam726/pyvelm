# Form UX

Features that apply across **form views** (and related list interactions):
tabbed notebooks, sticky actions, keyboard save, success toasts, and opening
related records in a floating dialog instead of leaving the page.

Introduced in **[v0.21.0](releases/v0.21.0.md)** unless noted otherwise.

---

## Tabbed notebooks

Long forms can mix flat **sections** (stacked cards) and **notebooks**
(Odoo-style tabs). Each tab is a `page(...)` with its own field grid.

### Python builders

```python
from pyvelm.builders import form_view, section, notebook, page, field

form_view(
    "country.form", "res.country",
    sections=[
        section("identity", "Identity", ["name", "code", "continent_id"]),
        notebook(
            "subdivisions",
            title="Subdivisions",   # optional legend above the tab strip
            pages=[
                page(
                    "states",
                    "States / provinces",
                    [field("state_ids", edit_toggle=True, list_view="state.compact")],
                    cols=1,         # optional; defaults to form cols
                ),
                page(
                    "cities",
                    "Cities",
                    [field("city_ids", edit_toggle=True, list_view="city.compact")],
                ),
            ],
        ),
    ],
)
```

| Builder | Purpose |
|---------|---------|
| `section(name, title, fields, *, cols=2)` | Single card of fields |
| `notebook(name, pages, *, title=None)` | Tab container |
| `page(name, title, fields, *, cols=None)` | One tab's field list |

The **first page** is selected by default. The active tab is remembered per
notebook in `localStorage` (key `pv-nb-<module>-<view>-<notebook_name>`).

### View XML

Equivalent arch (normalized to the same structure as builders):

```xml
<form>
  <section name="identity" title="Identity">
    <field name="name"/>
  </section>
  <notebook name="lines">
    <page name="invoice" title="Invoice lines">
      <field name="invoice_line_ids" widget="dialog" list_view="move.line.invoice"/>
    </page>
    <page name="entry" title="Journal items">
      <field name="entry_line_ids" widget="inline" list_view="move.line.entry"/>
    </page>
  </notebook>
</form>
```

### View inheritance

Target a field inside a notebook page with a path through `pages`:

```python
op_after(
    ["sections", "subdivisions", "pages", "states", "fields", "code"],
    {"name": "type"},
)
```

See [Extending views](inheritance.md).

### When to use notebooks vs `edit_toggle`

| Pattern | Use when |
|---------|----------|
| **Notebook** | Several *different* One2many fields (States vs Cities) or unrelated heavy widgets should not share one scroll |
| **`edit_toggle`** | One field can be edited as a **dialog table** or an **inline grid** without duplicating the field on two tabs |

You can combine both: notebook tabs that each host an `edit_toggle` field.
Live examples: `pyvelm/modules/geo_data/views/geo.py` (country form),
`examples/modules/vellum_demo/views/note.py` (note → Comments tab).

---

## Sticky action bar

On form views, the mode badge (**display** / **edit** / **new**) and action
buttons (**Edit**, **Save**, **Cancel**, **Delete**, header actions) stay
**pinned at the top** while you scroll long field content.

This is pure layout CSS (`.pv-form-actions-bar`); no extra configuration.

---

## Save with Ctrl+S / Cmd+S

In **edit** or **new** mode, **Ctrl+S** (Windows/Linux) or **Cmd+S** (macOS)
clicks the same control as the green **Save** or **Create** button — including
HTMX validation and the success toast.

The shortcut is **not** captured when focus is inside:

- HTML / code field editors (`.pv-html-editor`, `.pv-code-editor`)
- A **textarea** inside an inline One2many grid (so Enter/Ctrl+S behave as
  expected in multi-line cells)

Buttons carry `data-pv-form-save` and a tooltip (`Save (Ctrl+S)`).

---

## Save confirmation toast

After a successful **Save** or **Create** on a full-page form, a green toast
appears (e.g. **Saved Kenya.** / **Created …**). The server sets
`HX-Trigger: pv-toast` on the POST response; the layout routes it to the
global toast stack (`window.pvToast`).

Saving inside **`PvDialog`** also shows a toast before the dialog closes.

Failed saves (422 validation or ORM errors) do **not** toast — errors stay on
the form.

---

## Opening related records (`PvDialog`)

Many2one values and One2many rows can open the comodel form in a **floating,
draggable dialog** instead of navigating away. The page behind stays put.

### Many2one — display (lists and forms)

When the comodel has a form view, the cell shows:

1. **Plain text** — the display name (not a link).
2. **Open button** — small external-link icon (Odoo-style) beside the label.

Clicking the button opens **`PvDialog`** with that record in **display** mode.
Use **Open full page** in the dialog title bar to navigate to the normal
`/web/views/.../record/{id}` route.

### Many2one — edit (combobox)

The edit widget keeps the searchable combobox; the same **open** button sits
to the right of the input. It calls `PvDialog.open()` (no full-page navigation).

**Create and edit…** in the dropdown still opens the comodel **new** form in
the dialog.

### One2many — dialog table

With `widget="dialog"` (or **Dialog** on an `edit_toggle` field), each row
and **Add** open the child form in `PvDialog`. After a successful child save,
the parent table can refresh (`data-pv-dialog-refresh` on the trigger).

### Declarative dialog triggers

Any element can open the dialog:

```html
<a href="/web/views/partners/partner.form/record/42"
   data-pv-dialog
   data-pv-dialog-title="Partner"
   data-pv-dialog-refresh>
   Open
</a>
```

| Attribute | Purpose |
|-----------|---------|
| `data-pv-dialog` | Mark as dialog trigger (or use `data-pv-dialog-url`) |
| `data-pv-dialog-url` | URL to load (defaults to `href`) |
| `data-pv-dialog-title` | Dialog title bar |
| `data-pv-dialog-refresh` | After save, re-fetch the parent form shell on the page |

Imperative API (from Alpine or scripts):

```javascript
window.PvDialog.open({
    url: '/web/views/geo_data/geo_data.country.form/record/115',
    title: 'Kenya',
});
```

Dialog requests send **`X-PV-Dialog: 1`** so the server returns a **body-only**
form fragment (no sidebar) and skips out-of-band pager swaps on the parent
page. Successful saves return **204** + `pv-dialog-saved` instead of swapping
the dialog body to display mode.

### Lists — row click vs open button

List rows are still **clickable** to open the record form on the full page.
Clicks on **buttons**, **links**, the M2O **open** button, checkboxes, or
drag handles do **not** trigger row navigation (`pvListRowNavigate`).

---

## Autosave on navigation

Unchanged since earlier releases, but pairs with the above:

- In **edit** / **new**, if the form is **dirty** and you click a normal
  in-app link (sidebar, breadcrumb), the framework **POSTs the form first**,
  then follows the link on success.
- **Save**, **Cancel**, and **Ctrl+S** use their own flows (not double-saving).
- **Back** / tab close uses the browser **Leave site?** prompt when dirty.

See [Building UIs → Autosave on navigation](views.md#autosave-on-navigation).

---

## Related guides

| Topic | Doc |
|-------|-----|
| One2many `edit_toggle`, inline grid keys, `list_view` | [One2many on parent forms](one2many-forms.md) |
| List / form / kanban views, widgets | [Building UIs](views.md) |
| Notebook field paths in inheritance | [Extending views](inheritance.md) |
| Geo Data country notebook demo | [Geo data](geo-data.md) |
