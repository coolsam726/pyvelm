from __future__ import annotations

import unittest


class AppsCatalogGatingTests(unittest.TestCase):
    def test_catalog_access_model_filters_entries(self):
        # This test is file-system based (module discovery), so it runs only
        # when executing inside the repo checkout.
        from pathlib import Path

        from pyvelm.env import Environment
        from pyvelm.registry import Registry
        from pyvelm.render import _apps_catalog

        root = Path(__file__).resolve().parents[2]  # project root
        module_roots = [root / "pyvelm" / "modules"]

        # Minimal env stub for apps catalog: needs conn.execute + has_access/can.
        class _Conn:
            def execute(self, *_a, **_k):
                raise RuntimeError("no ir_module table in unit test")

        env = Environment(_Conn(), registry=Registry(), uid=2)

        # Deny all ACL so gated apps (like admin) are filtered out.
        env.has_access = lambda *_a, **_k: False  # type: ignore[method-assign]
        env.can = lambda *_a, **_k: False  # type: ignore[method-assign]

        catalog = _apps_catalog(env, module_roots)
        names = {c["name"] for c in catalog}
        self.assertNotIn("admin", names)

