"""Migration 0.32.0 → 0.33.0 — header logo height + show brand text in chrome."""

from __future__ import annotations


def migrate(env):
    conn = env.conn
    conn.execute(
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "header_logo_height" integer DEFAULT 0'
    )
    conn.execute(
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "show_header_brand_text" boolean DEFAULT true'
    )
    conn.execute(
        'UPDATE "res_company" SET "header_logo_height" = 0 '
        'WHERE "header_logo_height" IS NULL'
    )
    conn.execute(
        'UPDATE "res_company" SET "show_header_brand_text" = true '
        'WHERE "show_header_brand_text" IS NULL'
    )
