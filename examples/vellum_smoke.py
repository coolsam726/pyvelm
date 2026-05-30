"""Vellum smoke test against the example app modules.

Runs against the same module roots as ``examples/serve.py`` (including
``examples/modules/vellum_demo``). Does **not** wipe the full database;
safe to run on a dev DB that already has partners/crm installed.

**Do not rename this file to ``vellum.py``** — Python puts ``examples/`` on
``sys.path``, which would shadow the bundled ``vellum`` loader module.

Usage::

    pip install -e .
    cp .env.example .env   # set PYVELM_DSN
    python examples/vellum_smoke.py

Optional fresh vellum_demo tables only::

    python examples/vellum_smoke.py --reset-vellum
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader

load_dotenv(".env")

HERE = Path(__file__).parent
EXAMPLE_ROOT = HERE / "modules"
MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [EXAMPLE_ROOT]

VELLUM_TABLES = (
    "vellum_demo_comment",
    "vellum_demo_note",
    "vellum_demo_soft_note",
)


def _reset_vellum_tables(conn) -> None:
    for table in VELLUM_TABLES:
        conn.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    conn.execute(
        "DELETE FROM ir_module WHERE name = %s", ["vellum_demo"]
    )


def _ensure_soft_note_column(env) -> None:
    env.conn.execute(
        'ALTER TABLE "vellum_demo_soft_note" '
        'ADD COLUMN IF NOT EXISTS "deleted_at" timestamp'
    )


def _cleanup(env) -> None:
    if "vellum.demo.comment" in env.registry:
        env["vellum.demo.comment"].search([]).unlink()
    if "vellum.demo.note" in env.registry:
        env.registry["vellum.demo.note"]._created_log.clear()
        env["vellum.demo.note"].search([]).unlink()
    if "vellum.demo.soft_note" in env.registry:
        trashed = env.query("vellum.demo.soft_note").with_trashed().get()
        if trashed:
            trashed.force_delete()
        env.query("vellum.demo.soft_note").get().unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Vellum example smoke test")
    parser.add_argument(
        "--reset-vellum",
        action="store_true",
        help="Drop vellum_demo tables and reinstall that module only",
    )
    args = parser.parse_args()

    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN is not set (copy .env.example to .env)")

    with psycopg.connect(dsn, autocommit=True) as conn:
        if args.reset_vellum:
            _reset_vellum_tables(conn)

        reg = Registry()
        env = Environment(conn, registry=reg, uid=1)
        specs = loader.load_and_install(MODULE_ROOTS, env, install_all=True)
        print("Loaded modules:", [s.name for s in specs])

        assert "vellum" in {s.name for s in specs}, "bundled vellum module missing"
        assert "vellum_demo" in {s.name for s in specs}, (
            "examples/modules/vellum_demo not installed — check MODULE_ROOTS"
        )

        _ensure_soft_note_column(env)
        _cleanup(env)

        # --- Slice A: query builder + env.query --------------------------------
        low = env["vellum.demo.note"].create(
            {"title": "  Low  ", "body": "x", "score": 10}
        )
        high = env["vellum.demo.note"].create(
            {"title": "  High  ", "body": "y", "score": 90}
        )
        assert low.title == "Low", "mutator should strip title on create"
        assert high.title == "High"

        hot = env.query("vellum.demo.note").high_score().order_by("id", "asc").get()
        assert hot._ids == (high.id,), hot._ids
        print("query builder + @scope high_score OK")

        empty = env.query("vellum.demo.note").where("score", ">", 200).first()
        assert not empty
        print("first() returns empty recordset OK")

        # --- Slice B: relations, with_, with_count ---------------------------
        c1 = env["vellum.demo.comment"].create(
            {"note_id": high, "body": "first comment"}
        )
        c2 = env["vellum.demo.comment"].create(
            {"note_id": high, "body": "second comment"}
        )

        via_relation = high.has_many(
            "vellum.demo.comment", "note_id"
        ).order_by("id", "asc").get()
        assert via_relation._ids == (c1.id, c2.id)

        parent = c1.belongs_to("vellum.demo.note", "note_id").get()
        assert parent._ids == (high.id,)

        loaded = (
            env.query("vellum.demo.note")
            .where("id", "=", high.id)
            .with_("comment_ids")
            .with_count("comment_ids")
            .get()
        )
        assert loaded.count_of("comment_ids") == 2
        assert set(loaded.comment_ids._ids) == {c1.id, c2.id}
        print("relations + with_ + with_count OK")

        # --- Slice C: accessor, events ---------------------------------------
        assert loaded.title_upper == "HIGH"
        assert "High" in env.registry["vellum.demo.note"]._created_log
        print("accessor + @on(created) OK")

        loaded.fill({"body": "updated body", "not_allowed": True})
        assert loaded.body == "updated body"
        print("fill() + _fillable OK")

        # --- Slice D: soft deletes -------------------------------------------
        soft = env["vellum.demo.soft_note"].create({"title": "Soft row"})
        sid = soft.id
        soft.delete()
        assert not env.query("vellum.demo.soft_note").where("id", "=", sid).exists()
        assert env.query("vellum.demo.soft_note").with_trashed().where(
            "id", "=", sid
        ).exists()
        soft.restore()
        assert env.query("vellum.demo.soft_note").where("id", "=", sid).exists()
        soft.delete()
        soft.force_delete()
        assert not env.query("vellum.demo.soft_note").with_trashed().where(
            "id", "=", sid
        ).exists()
        print("SoftDeletes OK")

        _cleanup(env)
        print("\nAll Vellum example checks passed.")


if __name__ == "__main__":
    main()
