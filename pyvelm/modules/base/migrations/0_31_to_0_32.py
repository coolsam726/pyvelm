"""Migration 0.31.0 → 0.32.0 — add ``res_company.font_family``."""

from __future__ import annotations


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "font_family" text'
    )
    env.conn.execute(
        'UPDATE "res_company" SET "font_family" = \'\' '
        'WHERE "font_family" IS NULL'
    )
