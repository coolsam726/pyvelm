"""``pyvelm.modules`` is a discovery root, not an importable package."""
from __future__ import annotations

import unittest


class ModulesPackageTests(unittest.TestCase):
    def test_import_raises_with_helpful_message(self):
        import importlib

        with self.assertRaises(ImportError) as ctx:
            importlib.import_module("pyvelm.modules")
        self.assertIn("not an importable", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
