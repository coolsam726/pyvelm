"""Tests for PYVELM_MODULE_ROOTS parsing."""

from __future__ import annotations

import unittest

from pyvelm.loader import parse_module_roots_env


class ParseModuleRootsEnvTests(unittest.TestCase):
    def test_comma_separated(self):
        roots = parse_module_roots_env(
            "./examples/modules,./examples/modules_demo"
        )
        self.assertEqual(len(roots), 2)
        self.assertEqual(roots[0].as_posix(), "examples/modules")
        self.assertEqual(roots[1].as_posix(), "examples/modules_demo")

    def test_colon_separated(self):
        roots = parse_module_roots_env("/app/a:/app/b")
        self.assertEqual(len(roots), 2)
        self.assertEqual(str(roots[0]), "/app/a")
        self.assertEqual(str(roots[1]), "/app/b")

    def test_empty(self):
        self.assertEqual(parse_module_roots_env(""), [])

