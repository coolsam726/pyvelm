"""Helpers to keep filesystem-scaffolded module imports from leaking across tests."""
from __future__ import annotations

import sys


def purge_import_prefix(prefix: str) -> None:
    """Remove ``prefix`` and ``prefix.*`` from :data:`sys.modules`."""
    for key in list(sys.modules):
        if key == prefix or key.startswith(prefix + "."):
            del sys.modules[key]
