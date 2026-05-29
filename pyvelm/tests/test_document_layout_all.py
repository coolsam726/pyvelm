"""Load document_layout tests from ``pyvelm/modules/document_layout/tests``.

``pyvelm.modules`` is a poison package (see ``pyvelm/modules/__init__.py``);
pytest cannot collect under ``modules/document_layout/tests`` directly. Test
classes are imported by file path (with ``document_layout`` on ``sys.path``)
and re-exported into this module's namespace.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_MODULE_ROOT = Path(__file__).resolve().parent.parent / "modules"
if str(_MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(_MODULE_ROOT))

_DL_TESTS = _MODULE_ROOT / "document_layout" / "tests"
_seen: set[type] = set()


def _import_document_layout_test_module(path: Path):
    mod_name = f"_pyvelm_document_layout_tests.{path.stem}"
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


if _DL_TESTS.is_dir():
    for _path in sorted(_DL_TESTS.glob("test_*.py")):
        _import_document_layout_test_module(_path)
