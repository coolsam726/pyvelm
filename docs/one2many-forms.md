# One2many on parent forms

When a **form** shows a `One2many` field (`order_line_ids`, `comment_ids`, …),
the framework renders an embedded **sub-grid** (dialog table or inline
editable table). Three things are configured independently:

| Concern | Controls | Doc below |
|---------|----------|-----------|
| **How** users edit children | `widget="dialog"` vs `widget="inline"` | [Edit mode](#edit-mode-dialog-vs-inline) |
| **Which columns** appear in the grid | `list_view`, `columns`, or default | [Column layout](#column-layout) |
| **Which form** opens for a row / Add | `form_view` or default | [Form view for links](#form-view-for-row-links) |

This page covers **column layout** and **form view** selection. For list
**page** domains (standalone `/web/views/...` URLs), see
[Building UIs → Fixed domain](views.md#fixed-domain).

---

## Column layout

The sub-grid needs a list of comodel fields to show as columns. There are
four ways to supply that list, in **priority order**:

| Priority | Mechanism | List view record required? |
|----------|-----------|---------------------------|
| 1 | `columns=[...]` on the **parent form** field spec | **No** |
| 2 | `list_view="..."` on the **parent form** field spec | Yes |
| 3 | `list_view="..."` on the **`One2many` field** in the model | Yes |
| 4 | Default: lowest `ir.ui.view` **id** for `view_type="list"` on the comodel | Yes (if any exist) |
| 5 | Fallback: **every stored scalar** on the comodel (except nested O2m/M2m) | No |

If the comodel has **no** list view and you omit `columns` and `list_view`,
you get row (5) — often too many columns. Prefer `columns=` for lightweight
embeds or register a dedicated list view for a full grid.

### `columns` — ad-hoc grid (no list view)

Define columns **only on the parent form** (or on the model field). Same
entries as a list view `arch["fields"]`: bare names or `field(...)` dicts.

```python
from pyvelm.builders import field, form_view, section

form_view(
    "note.form", "vellum.demo.note",
    sections=[
        section(
            "comments",
            "Comments",
            [
                field(
                    "comment_ids",
                    widget="dialog",
                    columns=["body", field("active", widget="toggle")],
                    form_view="demo_comment.form",
                ),
            ],
        ),
    ],
)
```

On the **model** (default for every form that shows the field):

```python
comment_ids = One2many(
    "vellum.demo.comment",
    "note_id",
    columns=["body", "active"],
    form_view="demo_comment.form",
)
```

- Nested `One2many` / `Many2many` columns are **skipped** (they need full form width).
- Inline `columns` do **not** enable drag-reorder; use a list view with
  `sequence=` on the arch for that.

### `list_view` — reuse a registered list view

Point at an existing **`view_type="list"`** declaration (in the module's
`VIEWS` and synced to `ir.ui.view`). The embedded table uses that view's
**columns** and its optional **`sequence`** field for drag handles.

**On the model:**

```python
invoice_line_ids = One2many(
    "account.move.line",
    "move_id",
    list_view="account.move.line.invoice",
    form_view="account.move.line.invoice.form",
)

entry_line_ids = One2many(
    "account.move.line",
    "move_id",
    list_view="account.move.line.entry",
    form_view="account.move.line.entry.form",
)
```

**On one parent form only** (overrides the model default):

```python
field("line_ids", widget="dialog", list_view="account.move.line.entry")
```

#### View reference syntax

Same rules as menu `view=` and dashboard widgets:

| Form | Example | Resolves to |
|------|---------|-------------|
| Short name (parent form's module) | `"move.line.invoice"` | `(parent_module, "move.line.invoice")` |
| Slash-qualified | `"account/move.line.invoice"` | `("account", "move.line.invoice")` |
| Tuple | `("account", "move.line.invoice")` | as given |

The resolved view must exist, target the **comodel** of the `One2many`, and
have `view_type="list"`. If the name is missing or wrong, the framework
falls back to the lowest-id list view on that model, then to the scalar
fallback.

#### What `list_view` is **not**

- **Not** a call to `list_view()` inline — the builder returns a full view
  dict for `VIEWS`, not a field parameter:

  ```python
  # Wrong — do not pass the builder result into field()
  field("line_ids", list_view=list_view("x.list", "my.model", fields=[...]))

  # Right — string name of a view already in VIEWS / ir.ui.view
  field("line_ids", list_view="x.list")
  ```

- **Not** a replacement for `columns=` — use `columns` when you never
  registered a standalone list page for the comodel.

---

## Form view for row links

Dialog mode and inline tables link each row (and **Add**) to a **form**
view on the comodel. Configure it the same way as `list_view`:

| Where | Example |
|-------|---------|
| Model field | `form_view="demo_comment.form"` on `One2many(...)` |
| Parent form arch | `field("comment_ids", form_view="other.form")` |

Reference syntax is identical to `list_view` (short name, slash, or tuple).
The view must be `view_type="form"` on the comodel.

If omitted, the framework picks the comodel form view with the **lowest**
`ir.ui.view` id (same legacy rule list views used to use).

**Add** navigates to:

```text
/web/views/<module>/<form_view>/new?<inverse_name>=<parent_id>
```

After save in the dialog, the parent table refreshes (`data-pv-dialog-refresh`).

If the comodel has **no** form view, `One2many` falls back to a **chip
summary** (no table / dialog).

---

## Edit mode: dialog vs inline

### Dialog / Inline toggle (`edit_toggle`)

Instead of duplicating fields or notebook pages, enable a segmented
**Dialog | Inline grid** switch on one field:

```python
field(
    "state_ids",
    widget="dialog",          # default mode when the form loads
    edit_toggle=True,
    list_view="move.line.compact",
    form_view="move.line.form",
    columns=["name", "short_code", "code", "type"],
)
```

- **Dialog** — read-only sub-table on the parent form; row / Add open the
  comodel form in the floating dialog (saves on the child form).
- **Inline grid** — editable cells on the parent form (saved on **parent Save**).

The choice is remembered per record in ``localStorage`` (key
``pv-o2m-edit-<model>-<id>-<field_name>``). Only one pane is visible at a
time; the inactive pane is hidden with CSS (``data-o2m-mode`` on the toggle
root) so it is not submitted with the parent form.

On **display** forms, ``edit_toggle`` is ignored — you always get the dialog
table until you click **Edit** on the parent record.

### Excel-style keyboard (inline / `table` widget)

Inline grids (`widget="inline"` or `widget="table"`) support spreadsheet-style
navigation (since v0.20.x):

| Key | Action |
|-----|--------|
| **Tab** / **Shift+Tab** | Next / previous editable cell (wraps across rows) |
| **Enter** | Move to the cell below (Shift+Enter = newline in textarea) |
| **Arrow keys** | Move between cells; in text fields, arrows move the caret until the edge, then jump cells |
| **Ctrl/Cmd + arrows** | Always jump cells |
| **Escape** | Clear the active-cell highlight |
| **Click** | Focus the cell editor |

The active cell is highlighted. **Add a line** appends a row and focuses the
first column; Tab past the last cell on the last row also triggers **Add a line**.

Many2one comboboxes keep their own ↑/↓/Enter behaviour while the dropdown is open.

| `widget` | One2many behaviour |
|----------|-------------------|
| **`dialog`** (default when a comodel form exists) | Read-only table; edit in floating dialog; child save is separate from parent Save. |
| **`inline`** or **`table`** | Editable cells on the parent form; create/update/delete on **parent Save**. |

```python
section(
    "lines",
    "Lines",
    [
        field("invoice_line_ids", widget="dialog", list_view="move.line.invoice"),
        field("rate_ids", widget="inline", columns=["name", "rate"]),
    ],
)
```

Column selection (`list_view` / `columns`) applies to **both** modes.

See [Building UIs → Relational fields](views.md#relational-fields-widgetdialog-vs-widgetinline)
for Many2many and more UI detail.

---

## Tabbed notebooks on the parent form

When several One2many fields (or other heavy widgets) should not all
appear on one long scroll, group them in a **notebook** — each tab is
a `page(...)` with its own field list:

```python
from pyvelm.builders import field, form_view, notebook, page, section

form_view(
    "move.form", "account.move",
    sections=[
        section("header", "Header", ["partner_id", "date"]),
        notebook("lines", pages=[
            page(
                "invoice",
                "Invoice lines",
                [field("invoice_line_ids", list_view="move.line.invoice")],
            ),
            page(
                "entry",
                "Journal items",
                [field("entry_line_ids", list_view="move.line.entry")],
            ),
        ]),
    ],
)
```

See [Building UIs → Form views](views.md#form-views). View inheritance
targets notebook fields with paths like
``["sections", "lines", "pages", "invoice", "fields", "qty"]``.

---

## Worked example: two grids on one comodel

`account.move.line` might power both an **invoice** lines grid and a
**journal entry** lines grid on different parent forms:

```python
# views/move_line.py
VIEWS = [
    list_view(
        "move.line.invoice", "account.move.line",
        fields=["product_id", "quantity", "price_unit", "tax_ids"],
        form_view="move.line.invoice.form",
    ),
    list_view(
        "move.line.entry", "account.move.line",
        fields=["account_id", "debit", "credit", "name"],
        form_view="move.line.entry.form",
    ),
    form_view("move.line.invoice.form", "account.move.line", sections=[...]),
    form_view("move.line.entry.form", "account.move.line", sections=[...]),
]

# models/move.py
class AccountMove(BaseModel):
    _name = "account.move"
    invoice_line_ids = One2many(
        "account.move.line", "move_id",
        list_view="move.line.invoice",
        form_view="move.line.invoice.form",
    )

class AccountMoveLine(BaseModel):
    _name = "account.move.line"
    # ...
```

```python
# views/journal_entry.py — only entry lines on this form
form_view(
    "entry.form", "account.journal.entry",
    sections=[
        section(
            "lines", "Lines",
            [field("line_ids", widget="inline", list_view="move.line.entry")],
        ),
    ],
)
```

Live example in the repo: `examples/modules/vellum_demo/views/note.py` —
`demo_comment.compact` list vs `list_view="demo_comment.compact"` on
`comment_ids`.

---

## Field spec reference (`FieldRef`)

On a parent form, each `One2many` entry in a section's `fields` list can be
a string or a dict. Relational keys (see `pyvelm.types.FieldRef`):

| Key | Type | Purpose |
|-----|------|---------|
| `name` | `str` | **Required.** `One2many` field name on the parent model. |
| `widget` | `"dialog"` \| `"inline"` \| `"table"` | Edit UX (default: dialog when form exists). |
| `edit_toggle` | `bool` | **Edit only:** show **Dialog \| Inline grid** switch (needs `list_view` or `columns`). |
| `columns` | `list[str \| FieldRef]` | Inline column list; no list view needed. |
| `list_view` | `str` \| `(module, name)` | Registered list view for columns + `sequence`. |
| `form_view` | `str` \| `(module, name)` | Form for row links and dialog create. |
| `label`, `readonly`, `required`, `colspan`, … | | Same as other fields. |

Model-level defaults on `One2many(...)`:

```python
One2many(
    comodel_name,
    inverse_name,
    string=None,
    list_view=None,   # str or (module, name)
    form_view=None,
    # columns= only on FieldRef / future model kwarg if added
)
```

`columns` is most often set on **`field(...)`** in the form arch. Setting
`list_view` / `form_view` on the model applies everywhere unless the form
arch overrides them.

---

## Deploying view changes

- Declarative views live in module `DATA` files (`VIEWS = [...]`).
- After editing, bump the module version and run **`pyvelm db migrate`** or
  **Apps → Sync** so `ir.ui.view` rows update.
- Hard-refresh the browser on the parent form.

---

## Related

- [Form UX](form-ux.md) — notebooks, sticky actions, Ctrl+S, toasts, `PvDialog`
- [Building UIs](views.md) — list / form / kanban views, list `domain`, widgets
- [Declaring models → One2many](models.md#one2many)
- [IDE typing stubs](ide-typing.md) — `list_view=` / `columns` string literals (partial)
