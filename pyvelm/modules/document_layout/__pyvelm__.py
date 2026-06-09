"""document_layout module manifest.

Odoo-style configurable document PDF layouts: a company-level document layout
(logo, address, colors, paper format, layout variant) and a generic mechanism to
render any record to a branded PDF (HTML → wkhtmltopdf). Business modules register
their printable documents via ``document_layout.api.register_document(...)``.

When this module moves into pyvelm core, the manifest path becomes
``pyvelm.modules.document_layout``; app code should depend on ``document_layout``
and import from ``document_layout.api``.
"""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("document_layout")
    .version(0, 3, 0)
    .display_name("Document Layouts")
    .summary("Configurable company document layout + record-to-PDF printing.")
    .description(
        "A configurable external document layout (logo, address, accent colour, "
        "paper format, layout variant) plus a registry + print route that renders "
        "any record to a branded PDF via wkhtmltopdf. Other modules register their "
        "printable documents (invoices, receipts, delivery slips) against it."
    )
    .category("Technical")
    .author("savannabits")
    .depends("base")
    .data(
        "views/company.py",
        "views/menu.py",
    )
    .install_hook("document_layout.hooks:install")
    .sync_hook("document_layout.hooks:sync")
    .web_routes("document_layout.web:register_routes")
)
