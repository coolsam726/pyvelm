"""Tests for SQLAlchemy Core domain compilation."""
from __future__ import annotations

import unittest

from pyvelm import BaseModel, Char, Many2many, Registry
from pyvelm.database import dialect_capabilities
from pyvelm.domain import domain_to_sql
from pyvelm.domain_sa import domain_search_select


def _partner_registry():
    reg = Registry()
    with reg.activate():

        class Tag(BaseModel):
            _name = "test.tag"
            name = Char()

        class Partner(BaseModel):
            _name = "test.partner"
            name = Char()
            tag_ids = Many2many("test.tag")

    return reg, Partner


class DomainSACompileTests(unittest.TestCase):
    def test_m2m_path_compiles_to_exists(self):
        reg, Partner = _partner_registry()
        stmt = domain_search_select(
            Partner,
            [("tag_ids.name", "=", "VIP")],
            reg,
        )
        compiled = str(stmt).upper()
        self.assertIn("EXISTS", compiled)

    def test_m2o_chain_compiles_to_join(self):
        reg, Partner = _partner_registry()
        stmt = domain_search_select(
            Partner,
            [("name", "=", "Acme")],
            reg,
        )
        self.assertIn("test_partner", str(stmt))

    def test_oracle_text_equality_uses_dbms_lob_compare(self):
        reg, Partner = _partner_registry()
        cap = dialect_capabilities("oracle")
        stmt = domain_search_select(
            Partner,
            [("name", "=", "Admin")],
            reg,
            capabilities=cap,
        )
        self.assertIn("DBMS_LOB.COMPARE", str(stmt).upper())

    def test_matches_legacy_sql_shape_for_simple_domain(self):
        reg, Partner = _partner_registry()
        domain = [("name", "ilike", "%vip%")]
        legacy_where, _, _ = domain_to_sql(domain, Partner, reg)
        stmt = domain_search_select(Partner, domain, reg)
        compiled = str(stmt).upper()
        self.assertIn("LOWER", compiled)
        self.assertIn("LIKE", compiled)
        self.assertIn("ILIKE", legacy_where)
