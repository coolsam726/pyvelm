"""View scaffolding from registered models."""
from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from pyvelm.scaffold_generators import (
    build_view_scaffold_from_model,
    generate_views,
    load_registry_for_module,
)
from pyvelm.tests._isolation import purge_import_prefix


class ViewScaffoldFromModelTests(unittest.TestCase):
    def tearDown(self):
        purge_import_prefix("demo")

    def test_build_sections_for_partner_like_model(self):
        from pyvelm import BaseModel, Boolean, Char, Many2many, Many2one, One2many
        from pyvelm.registry import Registry

        reg = Registry()
        with reg.activate():

            class Partner(BaseModel):
                _name = "test.scaffold.partner"
                name = Char()
                code = Char()
                active = Boolean()
                country_id = Many2one("res.country")
                tag_ids = Many2many("res.tag")
                child_ids = One2many("test.scaffold.partner", inverse_name="parent_id")

        list_lines, sections = build_view_scaffold_from_model(
            reg, "test.scaffold.partner"
        )
        self.assertTrue(any("toggle" in line for line in list_lines))
        ids = [s[0] for s in sections]
        self.assertIn("main", ids)
        self.assertIn("relations", ids)
        rel_lines = next(lines for sid, _t, lines in sections if sid == "relations")
        self.assertTrue(any('widget="dialog"' in line for line in rel_lines))

    def test_generate_views_from_model_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod = root / "demo"
            (mod / "models").mkdir(parents=True)
            (mod / "__pyvelm__.py").write_text(
                textwrap.dedent(
                    """
                    NAME = "demo"
                    VERSION = (0, 1, 0)
                    DEPENDS: list[str] = []
                    DATA: list[str] = []
                    """
                ),
                encoding="utf-8",
            )
            (mod / "models" / "__init__.py").write_text(
                "from . import item  # noqa: F401\n", encoding="utf-8"
            )
            (mod / "models" / "item.py").write_text(
                textwrap.dedent(
                    """
                    from pyvelm import BaseModel, Char, Integer

                    class Item(BaseModel):
                        _name = "demo.item"
                        name = Char()
                        qty = Integer()
                    """
                ),
                encoding="utf-8",
            )
            import sys

            sys.path.insert(0, str(root))
            try:
                reg = load_registry_for_module("demo", modules_root=root)
                self.assertIsNotNone(reg)
                path = generate_views(
                    mod, "demo", "demo.item", registry=reg, from_model=True
                )
                text = path.read_text(encoding="utf-8")
                self.assertIn("demo.item", text)
                self.assertIn('"name"', text)
                self.assertIn('"qty"', text)
                self.assertIn("section(\"main\"", text)
            finally:
                sys.path.remove(str(root))
                purge_import_prefix("demo")

