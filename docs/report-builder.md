# Report Builder

User-defined reports on any installed model: filters, columns, optional
grouping, runtime parameters, preview in the browser, and export to **Excel**,
**CSV**, or **PDF**. Reports are **declarative JSON** compiled to parameterized
SQL through the same ACL, record-rule, and company-scope stack as list views.

## Security contract

1. **No user SQL** — only validated report definitions (schema v1).
2. **ACL** — `check_access(model, "read")` on every model touched.
3. **Record rules** — merged into the WHERE clause (same as `search()`).
4. **Company scope** — auto-applied on `_company_scoped` models.
5. **Private fields** — never selectable (`Field.private`).
6. **Joins** — registry-known M2o chains; O2m/M2m via correlated subqueries.
7. **Limits** — per-report `row_limit` (default 10 000) and preview cap (100 rows).

## Using the builder

1. Sidebar → **Reports → New report** (`/web/reports/build`).
2. Pick a **root model**, add **columns** from the field picker.
3. Add **filters** and optional **parameters**.
4. **Preview**, then **Save**.
5. **Run** or export from `/web/reports/{id}/run`.

Power users can still edit raw JSON on the report form.

## Definition schema (v1)

```json
{
  "version": 1,
  "root": "res.users",
  "columns": [
    {"expr": "name", "label": "Name"},
    {"expr": "login", "label": "Login"},
    {"expr": "group_ids.name", "label": "Groups", "subaggregate": "string_agg"}
  ],
  "filters": [["active", "=", true]],
  "parameters": [
    {"name": "q", "type": "string", "label": "Name contains", "required": false}
  ],
  "parameter_filters": [
    ["name", "ilike", {"param": "q"}]
  ],
  "order": ["name asc"]
}
```

### Collection columns (O2m / M2m)

Paths through one2many or many2many use a correlated subquery. Set
`subaggregate`:

| Value | Use |
|-------|-----|
| `string_agg` | Join related text values (default for text) |
| `count` | Count related rows |
| `sum` / `avg` / `min` / `max` | Numeric aggregates on the leaf field |

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/reports/models` | Models the user can read |
| `GET /api/reports/fields?model=` | Exportable fields for the picker |
| `POST /api/reports/validate-run` | Preview definition without saving |
| `POST /api/reports` | Create report |
| `PUT /api/reports/{id}` | Update report |
| `GET /api/reports/{id}/preview` | JSON preview |
| `GET /api/reports/{id}/export.xlsx` | Excel |
| `GET /api/reports/{id}/export.csv` | CSV |
| `GET /api/reports/{id}/export.pdf` | PDF |
| `POST /api/reports/{id}/schedule` | Enable daily cron + attachment output |

## Scheduling

On the builder page, enable **Daily cron** and choose output format. Each run
stores an `ir.attachment` linked to the report (`res_model=ir.report`).

## Module layout

| Path | Role |
|------|------|
| `pyvelm/reports/` | Compiler, executor, exporters, scheduler |
| `pyvelm/modules/reports/` | `ir.report`, `ir.report.run`, UI |

## Dependencies

- `openpyxl` — Excel export
- `fpdf2` — PDF export
