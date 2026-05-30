"""Seed a rich demo dataset for visual exploration of the DataTable.

Run AFTER a fresh install (or after basic.py has reset the DB).
Creates ~60 partners across 3 companies, 10 countries, several tags,
parent/child partner hierarchies, and ~40 CRM leads so the pagination,
search, and ordering features of the DataTable are easily exercised.

Usage:
    python examples/seed.py
"""
from __future__ import annotations

import os
import random
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(".env")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

# ── stable random seed so re-runs produce the same data ──────────────────────
random.seed(42)


def _upsert_country(Country, name: str):
    rec = Country.search([("name", "=", name)], limit=1)
    return rec if rec else Country.create({"name": name})


def _upsert_tag(Tag, name: str):
    rec = Tag.search([("name", "=", name)], limit=1)
    return rec if rec else Tag.create({"name": name})


def _upsert_company(Company, name: str):
    rec = Company.search([("name", "=", name)], limit=1)
    return rec if rec else Company.create({"name": name, "active": True})


def _birth_date_for_age(age: int) -> date:
    """Rough birth date from age — enough for the date picker demo."""
    year = date.today().year - max(age, 0)
    return date(year, 6, 15)


def _lead_schedule(index: int) -> dict:
    """Sample date, datetime, and time values for CRM leads."""
    return {
        "expected_close": date.today() + timedelta(days=21 + index * 5),
        "next_contact_at": datetime.now().replace(microsecond=0)
        + timedelta(days=index % 10, hours=9 + (index % 6)),
        "preferred_call_time": time(8 + (index % 9), (index * 15) % 60),
    }


def main():
    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN is not set")

    from pyvelm import BUILTIN_MODULE_ROOTS, Environment, Registry, loader

    # `base` + `admin` ship in the wheel; example addons live under
    # examples/modules (crm depends on base).
    MODULE_ROOTS = BUILTIN_MODULE_ROOTS + [HERE / "modules"]

    with psycopg.connect(dsn, autocommit=True) as conn:
        reg = Registry()
        env = Environment(conn, registry=reg)
        loader.load_and_install(MODULE_ROOTS, env, install_all=True)

        Partner = env["res.partner"]
        Country = env["res.country"]
        Tag = env["res.tag"]
        Company = env["res.company"]
        Lead = env["crm.lead"]

        # ── Countries ────────────────────────────────────────────────────────
        countries = {
            name: _upsert_country(Country, name)
            for name in [
                "France", "Germany", "Japan", "United Kingdom", "United States",
                "Spain", "Netherlands", "Brazil", "Canada", "Australia",
            ]
        }

        # ── Tags ─────────────────────────────────────────────────────────────
        tags = {
            name: _upsert_tag(Tag, name)
            for name in ["VIP", "Pro", "Enterprise", "Startup", "Partner", "Alumni"]
        }

        # ── Companies ────────────────────────────────────────────────────────
        my_co    = _upsert_company(Company, "My Company")
        contoso  = _upsert_company(Company, "Contoso Ltd")
        techcorp = _upsert_company(Company, "TechCorp Inc")

        # ── Partner data ─────────────────────────────────────────────────────
        # Each tuple: (name, code, age, vip_note, country_key, tag_names, company)
        PARTNERS_DATA = [
            # ── My Company ──────────────────────────────────────────────────
            ("Alice Beaumont",   "ALI-MC",  34, "Top-tier reseller — priority support",  "France",         ["VIP", "Pro"],           my_co),
            ("Bob Tanaka",       "BOB-MC",  28, None,                                     "Japan",           ["Pro"],                  my_co),
            ("Carol Dupont",     "CAR-MC",  41, "Founding customer",                      "France",          ["VIP"],                  my_co),
            ("Diana Weber",      "DIA-MC",  29, "DACH territory lead",                    "Germany",         ["Enterprise"],           my_co),
            ("Ethan Clarke",     "ETH-MC",  36, None,                                     "United Kingdom",  ["Partner"],              my_co),
            ("Fiona Rossi",      "FIO-MC",  32, "Strategic account",                      "United States",   ["VIP", "Enterprise"],    my_co),
            ("George Okonkwo",   "GEO-MC",  27, None,                                     "United Kingdom",  ["Startup"],              my_co),
            ("Hannah Schmidt",   "HAN-MC",  45, "Long-term client since 2014",             "Germany",         ["VIP", "Alumni"],        my_co),
            ("Ivan Petrov",      "IVA-MC",  38, None,                                     "France",          ["Pro"],                  my_co),
            ("Julia Santos",     "JUL-MC",  31, "Referred by Alice",                      "Brazil",          ["Partner"],              my_co),
            ("Kevin Park",       "KEV-MC",  26, None,                                     "United States",   ["Startup"],              my_co),
            ("Laura Bianchi",    "LAU-MC",  44, "Top Italy reseller",                     "France",          ["VIP", "Pro"],           my_co),
            ("Marco Ferreira",   "MAR-MC",  33, None,                                     "Brazil",          ["Partner", "Pro"],       my_co),
            ("Nina Johansson",   "NIN-MC",  29, None,                                     "Netherlands",     ["Startup"],              my_co),
            ("Oscar Nguyen",     "OSC-MC",  40, "Government sector account",               "France",          ["Enterprise"],           my_co),
            ("Paula Meier",      "PAU-MC",  37, None,                                     "Germany",         ["Pro"],                  my_co),
            ("Quinn O'Brien",    "QUI-MC",  24, "Fresh graduate, fast-tracker",           "United Kingdom",  ["Startup", "Alumni"],    my_co),
            ("Rachel Cohen",     "RAC-MC",  52, "Board advisor relationship",              "United States",   ["VIP"],                  my_co),
            ("Samuel Berg",      "SAM-MC",  35, None,                                     "Netherlands",     ["Partner"],              my_co),
            ("Tina Voss",        "TIN-MC",  30, None,                                     "Germany",         ["Pro", "Startup"],       my_co),
            # ── Contoso Ltd ─────────────────────────────────────────────────
            ("Dave Kim",         "DAV-CON", 25, None,                                     "Japan",           [],                       contoso),
            ("Eve Laurent",      "EVE-CON", 31, "Key account at Contoso",                 "France",          ["VIP"],                  contoso),
            ("Frank Müller",     "FRK-CON", 45, None,                                     "Japan",           ["Pro"],                  contoso),
            ("Greta Larsen",     "GRE-CON", 28, None,                                     "Netherlands",     ["Startup"],              contoso),
            ("Hugo Martínez",    "HUG-CON", 39, "Iberian sales lead",                     "Spain",           ["Enterprise", "VIP"],    contoso),
            ("Iris Nakamura",    "IRI-CON", 33, None,                                     "Japan",           ["Pro"],                  contoso),
            ("James Wilson",     "JAM-CON", 47, "Finance sector specialist",               "United Kingdom",  ["Enterprise"],           contoso),
            ("Kei Watanabe",     "KEI-CON", 22, None,                                     "Japan",           ["Startup"],              contoso),
            ("Lily Thompson",    "LIL-CON", 36, None,                                     "Australia",       ["Partner"],              contoso),
            ("Mia Svensson",     "MIA-CON", 29, None,                                     "Netherlands",     ["Pro", "Startup"],       contoso),
            ("Noah Schulz",      "NOA-CON", 41, "Key DACH contact",                       "Germany",         ["Enterprise", "Partner"],contoso),
            ("Olivia Petit",     "OLI-CON", 27, None,                                     "France",          ["Partner"],              contoso),
            ("Pedro Almeida",    "PED-CON", 34, "Portuguese language market",              "Brazil",          ["Pro"],                  contoso),
            ("Rosa García",      "ROS-CON", 50, "Longstanding EMEA relationship",          "Spain",           ["VIP", "Alumni"],        contoso),
            ("Sven Eriksson",    "SVE-CON", 43, None,                                     "Netherlands",     ["Enterprise"],           contoso),
            # ── TechCorp Inc ────────────────────────────────────────────────
            ("Adam Fisher",      "ADA-TC",  31, None,                                     "United States",   ["Startup"],              techcorp),
            ("Beth Sullivan",    "BET-TC",  28, "West Coast channel partner",              "United States",   ["Partner", "Pro"],       techcorp),
            ("Carlos Reyes",     "CAR-TC",  35, None,                                     "United States",   ["Enterprise"],           techcorp),
            ("Donna Chang",      "DON-TC",  44, "AI division stakeholder",                 "United States",   ["VIP", "Enterprise"],    techcorp),
            ("Eric Lund",        "ERI-TC",  26, None,                                     "Canada",          ["Startup"],              techcorp),
            ("Fatima Al-Hassan", "FAT-TC",  38, "MENA strategic partner",                 "Canada",          ["VIP", "Partner"],       techcorp),
            ("Gary Patel",       "GAR-TC",  33, None,                                     "Canada",          ["Pro"],                  techcorp),
            ("Helen Brooks",     "HEL-TC",  41, "Cloud infrastructure buyer",              "Australia",       ["Enterprise"],           techcorp),
            ("Ian Moore",        "IAN-TC",  29, None,                                     "Australia",       ["Pro", "Startup"],       techcorp),
            ("Jessica Lee",      "JES-TC",  36, "APAC territory manager",                  "Australia",       ["VIP", "Partner"],       techcorp),
        ]

        created_partners: dict[str, object] = {}
        for idx, (name, code, age, vip_note, country_key, tag_names, company) in enumerate(
            PARTNERS_DATA
        ):
            existing = Partner.search([("code", "=", code)], limit=1)
            if existing:
                created_partners[code] = existing
                continue
            rec = Partner.create({
                "name": name,
                "code": code,
                "age": age,
                "birth_date": _birth_date_for_age(age),
                **({"vip_note": vip_note} if vip_note else {}),
                "country_id": countries[country_key],
                "tag_ids": [tags[t] for t in tag_names],
                "company_id": company,
            })
            created_partners[code] = rec

        # ── CRM Leads ────────────────────────────────────────────────────────
        # Each tuple: (name, partner_code, stage, priority, revenue, prob, salesperson, company)
        STAGES = ["new", "qualified", "proposal", "won", "lost"]
        _my  = my_co
        _con = contoso
        _tc  = techcorp

        LEADS_DATA = [
            # My Company leads
            ("Cloud ERP Upgrade",           "ALI-MC",  "proposal",  2, 120.0,  75, "Rachel Cohen",    _my),
            ("Field Service Automation",    "FIO-MC",  "qualified", 1,  45.0,  50, "Tina Voss",       _my),
            ("Data Analytics Platform",     "IVA-MC",  "new",       0,  30.0,  20, "Kevin Park",      _my),
            ("E-Commerce Integration",      "JUL-MC",  "proposal",  1,  85.0,  60, "Bob Tanaka",      _my),
            ("HR Management System",        "MAR-MC",  "won",       2, 200.0, 100, "Alice Beaumont",  _my),
            ("Supply Chain Optimiser",      "NIN-MC",  "qualified", 1,  55.0,  45, "Paula Meier",     _my),
            ("Customer Portal Relaunch",    "OSC-MC",  "proposal",  2,  95.0,  70, "Carol Dupont",    _my),
            ("IoT Device Management",       "BOB-MC",  "new",       0,  22.0,  15, "Kevin Park",      _my),
            ("Security Audit & Compliance", "ETH-MC",  "lost",      1,  18.0,   0, "George Okonkwo",  _my),
            ("Marketing Automation",        "DIA-MC",  "qualified", 1,  40.0,  35, "Nina Johansson",  _my),
            ("ERP Phase 2 Rollout",         "LAU-MC",  "proposal",  2, 175.0,  80, "Samuel Berg",     _my),
            ("Logistics Tracking System",   "PAU-MC",  "qualified", 0,  28.0,  30, "Marco Ferreira",  _my),
            ("SaaS License Renewal",        "QUI-MC",  "won",       1,  50.0, 100, "Fiona Rossi",     _my),
            ("AI Chatbot Implementation",   "CAR-MC",  "new",       2,  70.0,  25, "Diana Weber",     _my),
            ("Digital Transformation",      "SAM-MC",  "proposal",  1, 110.0,  65, "Hannah Schmidt",  _my),
            ("Mobile App Development",      "TIN-MC",  "qualified", 0,  35.0,  40, "Ethan Clarke",    _my),
            ("Business Intelligence Suite", "KEV-MC",  "new",       1,  25.0,  10, "Quinn O'Brien",   _my),
            ("Cloud Migration",             "IVA-MC",  "lost",      2,  90.0,   0, "Julia Santos",    _my),
            ("Network Infrastructure",      "GEO-MC",  "proposal",  1,  60.0,  55, "Oscar Nguyen",    _my),
            ("Cybersecurity Framework",     "RAC-MC",  "won",       2, 250.0, 100, "Laura Bianchi",   _my),
            # Contoso Ltd leads
            ("ERP Consolidation",           "EVE-CON", "proposal",  2, 140.0,  72, "Noah Schulz",    _con),
            ("Warehouse Automation",        "HUG-CON", "qualified", 1,  65.0,  50, "Sven Eriksson",  _con),
            ("CRM Replacement",             "JAM-CON", "new",       0,  30.0,  15, "Greta Larsen",   _con),
            ("Partner Portal",              "LIL-CON", "proposal",  1,  80.0,  60, "Pedro Almeida",  _con),
            ("Payroll Integration",         "MIA-CON", "won",       1, 120.0, 100, "Olivia Petit",   _con),
            ("Document Management",         "NOA-CON", "qualified", 0,  25.0,  40, "Kei Watanabe",   _con),
            ("Customer Self-Service",       "ROS-CON", "proposal",  2,  95.0,  68, "Rosa García",    _con),
            ("Retail POS System",           "DAV-CON", "lost",      1,  42.0,   0, "Dave Kim",       _con),
            ("BI Dashboard",                "FRK-CON", "qualified", 2,  55.0,  48, "Iris Nakamura",  _con),
            ("Subscription Billing",        "IRI-CON", "won",       1,  88.0, 100, "Eve Laurent",    _con),
            ("GDPR Compliance Tool",        "OLI-CON", "new",       0,  18.0,  10, "Mia Svensson",   _con),
            ("Fleet Management",            "PED-CON", "proposal",  1,  72.0,  62, "Hugo Martínez",  _con),
            ("Field Operations App",        "SVE-CON", "qualified", 0,  40.0,  35, "James Wilson",   _con),
            ("Integration Middleware",      "KEI-CON", "new",       2,  50.0,  20, "Lily Thompson",  _con),
            ("Remote Monitoring Platform",  "GRE-CON", "proposal",  1, 100.0,  70, "Frank Müller",   _con),
            # TechCorp Inc leads
            ("AI Model Deployment",         "DON-TC",  "proposal",  2, 300.0,  85, "Jessica Lee",   _tc),
            ("Cloud-Native Migration",      "BET-TC",  "qualified", 1,  75.0,  55, "Helen Brooks",  _tc),
            ("Platform Engineering",        "CAR-TC",  "won",       2, 180.0, 100, "Donna Chang",   _tc),
            ("DevOps Toolchain",            "ERI-TC",  "new",       0,  35.0,  20, "Adam Fisher",   _tc),
            ("Data Lake Architecture",      "FAT-TC",  "proposal",  2, 220.0,  78, "Beth Sullivan", _tc),
            ("Kubernetes Operations",       "GAR-TC",  "qualified", 1,  60.0,  45, "Gary Patel",    _tc),
            ("Zero Trust Security",         "HEL-TC",  "proposal",  2, 130.0,  72, "Ian Moore",     _tc),
            ("MLOps Pipeline",              "IAN-TC",  "won",       1, 160.0, 100, "Carlos Reyes",  _tc),
            ("SRE Practice Build-out",      "JES-TC",  "new",       0,  45.0,  15, "Eric Lund",     _tc),
            ("Observability Platform",      "ADA-TC",  "qualified", 1,  85.0,  50, "Fatima Al-Hassan", _tc),
        ]

        partner_map: dict[str, object] = {}
        for _name, code, *_ in LEADS_DATA:
            if code in created_partners:
                partner_map[code] = created_partners[code]
            elif code not in partner_map:
                p = Partner.search([("code", "=", code)], limit=1)
                if p:
                    partner_map[code] = p

        lead_count = 0
        for lead_idx, (
            lead_name,
            p_code,
            stage,
            priority,
            revenue,
            prob,
            salesperson,
            company,
        ) in enumerate(LEADS_DATA):
            existing = Lead.search([("name", "=", lead_name), ("company_id", "=", company)], limit=1)
            if existing:
                continue
            partner = partner_map.get(p_code)
            Lead.create({
                "name": lead_name,
                **({"partner_id": partner} if partner else {}),
                "stage": stage,
                "priority": priority,
                "expected_revenue": revenue,
                "probability": prob,
                "salesperson": salesperson,
                "company_id": company,
                "active": stage != "lost",
                **_lead_schedule(lead_idx),
            })
            lead_count += 1

        partner_count = len(PARTNERS_DATA)
        print(f"Seeded {partner_count} partners across 3 companies.")
        print(f"Seeded {lead_count} CRM leads across 3 companies.")
        print("Companies: My Company | Contoso Ltd | TechCorp Inc")
        print()
        print("Browse:")
        print("  Partners list : http://127.0.0.1:8000/web/views/partners/partner.list")
        print("  CRM pipeline  : http://127.0.0.1:8000/web/views/crm/lead.kanban")
        print("  All leads     : http://127.0.0.1:8000/web/views/crm/lead.list")
        print("  Dashboard     : http://127.0.0.1:8000/web/admin")


if __name__ == "__main__":
    main()
