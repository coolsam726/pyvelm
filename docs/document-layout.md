# Document layouts & PDF printing (`document_layout` module)

Odoo-style **external document layout**: each company configures logo,
address block, accent colours, paper format, and a layout variant. Business
modules register printable documents (invoices, delivery slips, receipts);
the framework wraps the body HTML in the company layout and renders PDF via
**wkhtmltopdf**.

## Install

`document_layout` ships in the wheel under `pyvelm/modules/`. Add it to your
app's module roots (or install from **Apps**) and declare a dependency:

```python
# mymodule/__pyvelm__.py
DEPENDS: list[str] = ["base", "document_layout"]
```

Requires **base** (company branding fields, attachments). Optional **admin**
menus are provided by the module's own `views/menu.py` — not required for
printing.

### Server dependency: wkhtmltopdf

PDF routes call the `wkhtmltopdf` binary on `PATH`. HTML preview routes work
without it.

```bash
# Debian/Ubuntu
apt-get install -y wkhtmltopdf
```

When the binary is missing, `GET /report/pdf/…` returns **503** with an
install hint. Use `GET /report/html/…` to iterate on templates without PDF
round-trips.

## Company configuration

**Settings → Organization → Layout & Print** (or open
`res_company_layout.form` for a company).

| Area | Fields |
|------|--------|
| **Document Layout** | Variant (`light`, `boxed`, `bold`, …), paper (`A4` / `Letter`), Google Font, logo, primary/secondary colours |
| **Design layout** | Opens the live designer dialog (`design_button` widget) |
| **Company Address** | Street, city, ZIP, phone, email, website, VAT — rendered in the PDF header |
| **Branding** | Copyright line on the footer |

Layout variants include **light**, **boxed**, **bold**, **striped**,
**editorial**, **split**, **dark**, and **folder** (Odoo 19-style tab
header). The designer previews unsaved changes before save.

Company fields are added via `_inherit` on `res.company` in
`document_layout/models/company_ext.py` (address block, `document_layout`,
`paper_format`, etc.).

## Register a printable document

During module load (typically an `INSTALL_HOOK` or at import time in a
`hooks.py` that runs before routes are registered), call
`document_layout.api.register_document`:

```python
from document_layout.api import register_document


def _render_invoice_body(env, record):
    return f"<h1>Invoice {record.name}</h1><p>Total: {record.amount_total}</p>"


def install(env):
    register_document(
        "account.invoice",
        model="account.move",
        render_body=_render_invoice_body,
        title="Invoice",
    )
```

| Argument | Meaning |
|----------|---------|
| `key` | URL segment and registry id (e.g. `account.invoice`) |
| `model` | Model technical name — read ACL is enforced on print |
| `render_body` | `(env, record) -> html str` — inner body only; layout wrapper is automatic |
| `title` | Document title in the header (defaults to `key`) |

Register keys must be unique across the registry.

## HTTP routes

Registered via `WEB_ROUTES = "document_layout.web:register_routes"`. All
routes require login and **read** access on the underlying model (not sudo).

| Route | Purpose |
|-------|---------|
| `GET /report/pdf/{key}/{record_id}` | Download branded PDF |
| `GET /report/html/{key}/{record_id}` | Full HTML preview (same markup as PDF) |
| `GET /report/layout/preview/{company_id}` | Sample document in company layout |
| `GET /report/layout/designer` | Designer fragment (PvDialog) |
| `GET /web/report/layout/designer` | Designer full page in app shell |
| `GET /report/layout/preview-live` | Live preview with query-string overrides (designer JS) |
| `POST /report/layout/designer/save` | Persist layout fields on `res.company` |

Link to a PDF from a list or form:

```html
<a href="/report/pdf/account.invoice/{{ record.id }}">PDF</a>
```

## Python API

```python
from document_layout.api import (
    document_spec,
    register_document,
    render_html,
    render_layout_preview,
    render_pdf,
)

# Full branded HTML (preview=True wraps in paper sheet for browser)
html = render_html(env, "account.invoice", move_id, preview=True)

# PDF bytes + paper format string
pdf_bytes, paper = render_pdf(env, "account.invoice", move_id)

# Design-time sample (optional overrides dict for live designer)
fragment = render_layout_preview(env, company_id=1, overrides={"layout": "folder"}, inline=True)
```

`render_pdf` pipes HTML through wkhtmltopdf with margins matching the
preview CSS (`16 mm` top/bottom, `12 mm` left/right).

## Templates & packaging

Module Jinja templates live in `document_layout/templates/` and extend the
framework shell where needed. They are shipped in the wheel via
`modules/**/templates/**` in `pyproject.toml` package-data.

Logo URLs stored as `/api/attachment/{id}/download` are inlined as `data:`
URIs server-side so wkhtmltopdf (a separate process with no session) can
embed them.

## Tests

Unit tests:

- `pyvelm/tests/test_document_layout_all.py` — layout rendering (bundled module tests)
- `pyvelm/tests/test_document_layout_coverage.py` — hooks, PDF, web routes, registry

Run:

```bash
pytest pyvelm/tests/test_document_layout_all.py pyvelm/tests/test_document_layout_coverage.py -q
```
