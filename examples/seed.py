"""Seed demo partner data for visual exploration in the browser.

Run AFTER the server has done a fresh install (or after basic.py has reset
the DB).  Creates a small set of partners with VIP notes, tags, countries,
and parent/child relationships so there's something interesting to browse.

Usage:
    python examples/seed.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(".env")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))


def main():
    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN is not set")

    from pyvelm import Environment, Registry, loader

    MODULES_ROOT = HERE / "modules"

    with psycopg.connect(dsn, autocommit=True) as conn:
        reg = Registry()
        env = Environment(conn, registry=reg)
        loader.load_and_install([MODULES_ROOT], env)

        Partner = env["res.partner"]
        Country = env["res.country"]
        Tag = env["res.tag"]

        france = Country.search([("name", "=", "France")], limit=1)
        japan = Country.search([("name", "=", "Japan")], limit=1)

        # Upsert demo tags.
        vip_tag = Tag.search([("name", "=", "VIP")], limit=1)
        if not vip_tag:
            vip_tag = Tag.create({"name": "VIP"})
        pro_tag = Tag.search([("name", "=", "Pro")], limit=1)
        if not pro_tag:
            pro_tag = Tag.create({"name": "Pro"})

        alice = Partner.create({
            "name": "Alice Beaumont",
            "code": "ALI-PRO",
            "age": 34,
            "vip_note": "Top-tier reseller — priority support",
            "country_id": france,
            "tag_ids": [vip_tag, pro_tag],
        })
        Partner.create({
            "name": "Bob Tanaka",
            "code": "BOB-PRO",
            "age": 28,
            "country_id": japan,
            "tag_ids": [pro_tag],
        })
        carol = Partner.create({
            "name": "Carol Dupont",
            "code": "CAR-PRO",
            "age": 41,
            "vip_note": "Founding customer",
            "country_id": france,
            "tag_ids": [vip_tag],
        })
        Partner.create({
            "name": "Dave Kim",
            "code": "DAV-PRO",
            "age": 25,
        })
        Partner.create({
            "name": "Eve Dupont",
            "code": "EVE-PRO",
            "age": 22,
            "country_id": france,
            "parent_id": carol,
        })

    print("Seeded 5 demo partners (Alice Beaumont, Bob Tanaka, Carol Dupont, Dave Kim, Eve Dupont)")
    print("Open http://127.0.0.1:8000/web/views/partners/partner.list to browse them.")


if __name__ == "__main__":
    main()
