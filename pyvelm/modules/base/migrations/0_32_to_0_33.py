"""Header logo height + show brand text in chrome."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)

    def _alter(t):
        t.integer("header_logo_height", nullable=True).default(0)
        t.boolean("show_header_brand_text", nullable=True).default(True)

    schema.table("res_company", _alter)
    schema.update_rows(
        "res_company", {"header_logo_height": 0}, header_logo_height=None
    )
    schema.update_rows(
        "res_company",
        {"show_header_brand_text": True},
        show_header_brand_text=None,
    )
