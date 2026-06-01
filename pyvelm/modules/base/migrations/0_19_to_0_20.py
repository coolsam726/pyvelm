"""White-label branding columns on res_company."""

from pyvelm.migrations import Schema


def upgrade(env):
    schema = Schema(env)

    def _alter(t):
        t.string("app_name", nullable=True)
        t.string("app_tagline", nullable=True)
        t.string("logo_url", nullable=True)
        t.string("favicon_url", nullable=True)
        t.string("copyright_text", nullable=True)
        t.string("support_email", nullable=True)
        t.string("support_url", nullable=True)
        t.boolean("show_powered_by", nullable=True).default(True)

    schema.table("res_company", _alter)
