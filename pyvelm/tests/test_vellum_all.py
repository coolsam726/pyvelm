"""Load Vellum slice tests from ``pyvelm/modules/vellum/tests`` without importing ``pyvelm.modules``.

``pyvelm.modules`` is a poison package (see ``pyvelm/modules/__init__.py``);
pytest cannot collect under ``modules/vellum/tests`` directly. Test classes
are imported by file path and re-exported into this module's namespace.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_VELLUM_TESTS = (
    Path(__file__).resolve().parent.parent / "modules" / "vellum" / "tests"
)
_seen: set[type] = set()


def _import_vellum_test_module(path: Path):
    mod_name = f"_pyvelm_vellum_tests.{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        return
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    for name in sorted(dir(mod)):
        obj = getattr(mod, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, unittest.TestCase)
            and obj is not unittest.TestCase
            and obj not in _seen
        ):
            _seen.add(obj)
            globals()[f"{path.stem}_{name}"] = obj


if _VELLUM_TESTS.is_dir():
    for _path in sorted(_VELLUM_TESTS.glob("test_*.py")):
        _import_vellum_test_module(_path)
