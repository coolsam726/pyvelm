# Report Builder

User-defined reports on any installed model: a visual builder, preview in the
browser, and export to **Excel**, **CSV**, or **PDF**. Reports are stored as
**declarative JSON** (schema v1) compiled to parameterized SQL through the same
ACL, record-rule, and company-scope stack as list views.

Install the **`reports`** module from **Apps** (depends on `base` and `admin`).

## Enable the module

1. Open **Apps** (`/web/apps`).
2. Find **Report Builder** under **System**.
3. Click **Install**.

After install, the sidebar shows **Reports** with list, run, and builder
entry points.

## Using the visual builder

Open **Reports → New report** (`/web/reports/build`) or edit an existing
report (`/web/reports/{id}/build`).

The builder is a four-step wizard:

| Step | What you configure |
|------|-------------------|
| 1. Data source | Root model, report name, **List** (detail) or **Summary** (grouped) mode |
| 2. Columns | Fields, formatting, drag-reorder, **Order by** |
| 3. Filters | Fixed filters, runtime **parameters**, row limit |
| 4. Preview | Live preview, save, schedule |

### Field drill-down

Column, filter, parameter, and sort fields are picked through an
**Odoo-style drill-down browser**:

- Start at the root model's fields.
- Click a **Many2one** or **One2many** / **Many2many** relation to browse the
  next level.
- Use **← Back** or the breadcrumb to navigate up.
- The full dotted path (e.g. `company_id.currency_id.symbol`) is stored in
  the definition.

The drill UI calls `GET /api/reports/field-level?root=&prefix=` — one level at
a time, with ACL checks on every model in the path.

### List (detail) reports

- Add **columns** from the field picker; drag the ⋮⋮ handle to reorder.
- Per-column **format**: text, number, integer, or currency.
- **Alignment**: left, center, right.
- **Currency** columns: pick a fixed currency from active `res.currency`
  records, or use **from record field** (typically `currency_id` on monetary
  fields).
- **Order by**: add one or more sort rules with priority (drag to reorder).
  Sort fields do not need to appear as columns — the compiler adds the joins
  required for `ORDER BY`.

### Summary (grouped) reports

Switch to **Summary** in step 1:

- **Group by** — one or more root-level stored fields.
- **Measures** — `__count` or numeric aggregates (`sum:amount`, `avg:score`, …).
- **Order by** — sort by group-by keys or measure keys only.

Summary mode uses SQL `GROUP BY`; relation drill-down for group-by is limited
to root-model fields in v1.

### Filters and parameters

**Fixed filters** apply every run (standard domain tuples).

**Parameters** prompt the user at run time. Each parameter has a name, label,
type (`string`, `integer`, `float`, `boolean`, `date`, `datetime`), and
optional required flag. **Parameter filters** reference parameters with
`{"param": "name"}` as the domain value.

Example: a `q` string parameter with filter `["name", "ilike", {"param": "q"}]`.

### Preview, run, export

- **Preview** (step 4 or `POST /api/reports/validate-run`) returns up to 100 rows.
- **Run** (`/web/reports/{id}/run`) shows the full result with parameter form.
- Export: **Excel** (`.xlsx`), **CSV**, or **PDF** — formatted values and
  column alignment are applied in exports.

Power users can still edit the raw JSON on the report form (`ir.report.definition`).

## Security contract

1. **No user SQL** — only validated report definitions (schema v1).
2. **ACL** — `check_access(model, "read")` on every model touched.
3. **Record rules** — merged into the WHERE clause (same as `search()`).
4. **Company scope** — auto-applied on `_company_scoped` models.
5. **Private fields** — never selectable (`Field.private`).
6. **Joins** — registry-known M2o chains; O2m/M2m via correlated subqueries.
7. **Limits** — per-report `row_limit` (default 10 000) and preview cap (100 rows).

## Definition schema (v1)

Stored on `ir.report.definition` as JSON:

```json
{
  "version": 1,
  "root": "res.users",
  "columns": [
    {
      "expr": "name",
      "label": "Name",
      "format": {"type": "text", "align": "left"}
    },
    {
      "expr": "login",
      "label": "Login"
    },
    {
      "expr": "group_ids.name",
      "label": "Groups",
      "subaggregate": "string_agg"
    },
    {
      "expr": "amount",
      "label": "Amount",
      "format": {
        "type": "currency",
        "align": "right",
        "decimals": 2,
        "currency_source": "fixed",
        "currency_id": 1
      }
    }
  ],
  "filters": [["active", "=", true]],
  "parameters": [
    {"name": "q", "type": "string", "label": "Name contains", "required": false}
  ],
  "parameter_filters": [
    ["name", "ilike", {"param": "q"}]
  ],
  "order": ["name asc", "login desc"]
}
```

### Summary example

```json
{
  "version": 1,
  "root": "crm.lead",
  "groupby": ["stage_id"],
  "measures": ["__count", "sum:expected_revenue"],
  "order": ["__count desc"]
}
```

### Column format object

| Key | Values | Notes |
|-----|--------|-------|
| `type` | `text`, `number`, `integer`, `currency` | Default `text` |
| `align` | `left`, `center`, `right` | Default `left` |
| `decimals` | `0`–`8` | For number/currency |
| `currency_source` | `field`, `fixed` | Currency columns only |
| `currency_id` | integer | When `currency_source` is `fixed` |
| `currency_field` | string | When `currency_source` is `field` (default `currency_id`) |

### Collection columns (O2m / M2m)

Paths through one2many or many2many use a correlated subquery. Set
`subaggregate`:

| Value | Use |
|-------|-----|
| `string_agg` | Join related text values (default for text) |
| `count` | Count related rows |
| `sum` / `avg` / `min` / `max` | Numeric aggregates on the leaf field |

### Order by

`order` is a list of strings: `"field asc"` or `"field desc"`.

- **Detail reports** — any exportable field path on the root model (including
  fields not shown as columns).
- **Summary reports** — only group-by or measure keys.

## HTTP API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/reports/models` | Models the current user can read |
| `GET /api/reports/fields?model=` | Flat exportable field list (legacy picker) |
| `GET /api/reports/field-level?root=&prefix=` | One drill-down level for the field browser |
| `GET /api/reports/currencies` | Active currencies for currency column format |
| `POST /api/reports/validate-run` | Preview a definition without saving |
| `POST /api/reports` | Create report |
| `PUT /api/reports/{id}` | Update report |
| `GET /api/reports/{id}/preview` | JSON preview of saved report |
| `GET /api/reports/{id}/export.xlsx` | Excel download |
| `GET /api/reports/{id}/export.csv` | CSV download |
| `GET /api/reports/{id}/export.pdf` | PDF download |
| `POST /api/reports/{id}/schedule` | Enable daily cron + attachment output |

Web UI routes:

| Route | Purpose |
|-------|---------|
| `GET /web/reports/build` | New report builder |
| `GET /web/reports/{id}/build` | Edit existing report |
| `GET /web/reports/{id}/run` | Run with parameters + export buttons |

All API routes require authentication (`env.uid`).

## Scheduling

On the builder page (advanced options) or via the schedule API, enable
**Daily cron** and choose output format (`xlsx`, `csv`, or `pdf`). Each run
creates an `ir.attachment` linked to the report (`res_model=ir.report`) and
logs the run in `ir.report.run`.

The cron worker (`pyvelm-cron`) must be running for scheduled reports to fire.
See [Deployment → Background cron runner](deployment.md#the-cron-worker).

## Module layout

| Path | Role |
|------|------|
| `pyvelm/reports/` | Schema validation, SQL compiler, executor, exporters, scheduler |
| `pyvelm/modules/reports/` | `ir.report`, `ir.report.run`, views, sidebar menu |
| `pyvelm/templates/report_builder.html` | Visual builder UI |
| `pyvelm/templates/report_run.html` | Run + export page |
| `pyvelm/templates/widgets/field_drill_browser.html` | Drill-down field picker |

## Dependencies

Excel and PDF export require optional packages (included in the main wheel
dependencies):

- `openpyxl` — Excel export
- `fpdf2` — PDF export

## Related UI: `pvCombo`

The builder and form **Selection** fields use **`pvCombo`** — a searchable
combobox widget (`pyvelm/templates/widgets/pv_combo_fragment.html`). It
dispatches a `combo-change` custom event so Alpine handlers can read the
selected value without native `change` blur issues on HTMX pages.
