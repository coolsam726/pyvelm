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

        # Ensure the two demo companies exist.
        Company = env["res.company"]
        my_co = Company.search([("name", "=", "My Company")], limit=1)
        if not my_co:
            my_co = Company.create({"name": "My Company", "active": True})
        contoso = Company.search([("name", "=", "Contoso Ltd")], limit=1)
        if not contoso:
            contoso = Company.create({"name": "Contoso Ltd", "active": True})

        # --- My Company partners ---
        alice = Partner.create({
            "name": "Alice Beaumont",
            "code": "ALI-PRO",
            "age": 34,
            "vip_note": "Top-tier reseller — priority support",
            "country_id": france,
            "tag_ids": [vip_tag, pro_tag],
            "company_id": my_co,
        })
        Partner.create({
            "name": "Bob Tanaka",
            "code": "BOB-PRO",
            "age": 28,
            "country_id": japan,
            "tag_ids": [pro_tag],
            "company_id": my_co,
        })
        carol = Partner.create({
            "name": "Carol Dupont",
            "code": "CAR-PRO",
            "age": 41,
            "vip_note": "Founding customer",
            "country_id": france,
            "tag_ids": [vip_tag],
            "company_id": my_co,
        })

        # --- Contoso Ltd partners ---
        Partner.create({
            "name": "Dave Kim",
            "code": "DAV-CON",
            "age": 25,
            "company_id": contoso,
        })
        Partner.create({
            "name": "Eve Laurent",
            "code": "EVE-CON",
            "age": 31,
            "vip_note": "Key account at Contoso",
            "country_id": france,
            "tag_ids": [vip_tag],
            "company_id": contoso,
        })
        Partner.create({
            "name": "Frank Müller",
            "code": "FRK-CON",
            "age": 45,
            "country_id": japan,
            "tag_ids": [pro_tag],
            "company_id": contoso,
        })

    print("Seeded 6 demo partners — 3 for My Company, 3 for Contoso Ltd.")
    print("Companies: My Company | Contoso Ltd")
    print("Switch company on the dashboard: http://127.0.0.1:8000/web/admin")
    print("Browse partners: http://127.0.0.1:8000/web/views/partners/partner.list")


if __name__ == "__main__":
    main()
