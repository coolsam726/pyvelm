"""Migration 0.2.0 → 0.3.0 — configurable document header logo height."""

from __future__ import annotations


def migrate(env):
    env.conn.execute(
        'ALTER TABLE "res_company" '
        'ADD COLUMN IF NOT EXISTS "document_logo_height" integer DEFAULT 0'
    )
    env.conn.execute(
        'UPDATE "res_company" SET "document_logo_height" = 0 '
        'WHERE "document_logo_height" IS NULL'
    )
