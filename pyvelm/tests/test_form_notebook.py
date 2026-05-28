"""Form view notebooks (tabbed sections)."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pyvelm.registry import Registry
from pyvelm.render import _form_sections
from pyvelm.builders import op_after
from pyvelm.views import apply_operations, normalize_arch


class FormNotebookArchTests(unittest.TestCase):
    def test_normalize_promotes_page_fields(self):
        arch = {
            "sections": [
                {
                    "name": "nb",
                    "pages": [
                        {"name": "a", "title": "A", "fields": ["x", "y"]},
                    ],
                },
            ],
        }
        out = normalize_arch(arch, "form")
        fields = out["sections"][0]["pages"][0]["fields"]
        self.assertEqual(fields[0], {"name": "x"})
        self.assertEqual(fields[1], {"name": "y"})

    def test_inherit_can_patch_field_inside_notebook_page(self):
        arch = normalize_arch(
            {
                "sections": [
                    {
                        "name": "nb",
                        "pages": [
                            {
                                "name": "lines",
                                "title": "Lines",
                                "fields": ["qty"],
                            },
                        ],
                    },
                ],
            },
            "form",
        )
        apply_operations(
            arch,
            [
                op_after(
                    ["sections", "nb", "pages", "lines", "fields", "qty"],
                    {"name": "price_unit"},
                ),
            ],
        )
        names = [
            f["name"]
            for f in arch["sections"][0]["pages"][0]["fields"]
        ]
        self.assertEqual(names, ["qty", "price_unit"])


class FormNotebookRenderTests(unittest.TestCase):
    def test_form_sections_emits_notebook_kind(self):
        from pyvelm import BaseModel, Char, One2many

        reg = Registry()
        with reg.activate():

            class DemoLine(BaseModel):
                _name = "nb.line"
                name = Char()

            class DemoParent(BaseModel):
                _name = "nb.parent"
                title = Char()
                line_ids = One2many("nb.line", "parent_id")

        arch = normalize_arch(
            {
                "sections": [
                    {
                        "name": "main",
                        "title": "Main",
                        "fields": [{"name": "title"}],
                    },
                    {
                        "name": "lines_nb",
                        "pages": [
                            {
                                "name": "lines",
                                "title": "Lines",
                                "fields": [{"name": "line_ids"}],
                            },
                        ],
                    },
                ],
            },
            "form",
        )
        view = SimpleNamespace(
            module="demo",
            name="parent.form",
            model="nb.parent",
        )
        env = type("E", (), {"registry": reg})()
        with patch("pyvelm.views.resolve_arch", return_value=arch):
            sections = _form_sections(view, None, env, "display")
        self.assertEqual(sections[0]["kind"], "section")
        self.assertEqual(sections[1]["kind"], "notebook")
        self.assertEqual(len(sections[1]["pages"]), 1)
        self.assertEqual(sections[1]["pages"][0]["title"], "Lines")
        self.assertTrue(sections[1]["storage_key"].startswith("pv-nb-demo-"))


if __name__ == "__main__":
    unittest.main()
