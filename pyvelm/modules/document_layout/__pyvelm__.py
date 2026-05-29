"""document_layout module manifest.

Odoo-style configurable document PDF layouts: a company-level document layout
(logo, address, colors, paper format, layout variant) and a generic mechanism to
render any record to a branded PDF (HTML → wkhtmltopdf). Business modules register
their printable documents via ``document_layout.api.register_document(...)``.

When this module moves into pyvelm core, the manifest path becomes
``pyvelm.modules.document_layout``; app code should depend on ``document_layout``
and import from ``document_layout.api``.
"""

NAME: str = "document_layout"
DISPLAY_NAME: str = "Document Layouts"
VERSION: tuple[int, ...] = (0, 2, 0)
SUMMARY: str = "Configurable company document layout + record-to-PDF printing."
DESCRIPTION: str = (
    "A configurable external document layout (logo, address, accent colour, "
    "paper format, layout variant) plus a registry + print route that renders "
    "any record to a branded PDF via wkhtmltopdf. Other modules register their "
    "printable documents (invoices, receipts, delivery slips) against it."
)
CATEGORY: str = "Technical"
AUTHOR: str = "savannabits"

DEPENDS: list[str] = ["base"]

DATA: list[str] = [
    "views/company.py",
    "views/menu.py",
]

INSTALL_HOOK: str = "document_layout.hooks:install"
SYNC_HOOK: str = "document_layout.hooks:sync"

WEB_ROUTES: str = "document_layout.web:register_routes"
