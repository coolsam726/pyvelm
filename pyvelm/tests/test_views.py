"""Unit tests for ``pyvelm.views`` — arch normalization, op application,
target traversal, and chain resolution."""
from __future__ import annotations

import json
import unittest

from pyvelm.views import (
    _find_descendant,
    _matches_predicate,
    _resolve_position,
    _step_into,
    apply_operations,
    normalize_arch,
    resolve_arch,
)


def _arch():
    return {"sections": [{"name": "main", "fields": [{"name": "a"}, {"name": "b"}]}]}


class NormalizeArchTests(unittest.TestCase):
    def test_none_passthrough(self):
        self.assertIsNone(normalize_arch(None, "list"))

    def test_list_fields_promoted(self):
        out = normalize_arch({"fields": ["a", "b"]}, "list")
        self.assertEqual(out["fields"], [{"name": "a"}, {"name": "b"}])

    def test_form_nested_sections_promoted(self):
        out = normalize_arch(
            {"sections": [{"name": "s", "fields": ["x"]}]}, "form"
        )
        self.assertEqual(out["sections"][0]["fields"], [{"name": "x"}])

    def test_kanban_card_lists_promoted(self):
        out = normalize_arch({"card": {"fields": ["a"], "badges": ["b"]}}, "kanban")
        self.assertEqual(out["card"]["fields"], [{"name": "a"}])
        self.assertEqual(out["card"]["badges"], [{"name": "b"}])

    def test_unknown_view_type_is_noop(self):
        src = {"fields": ["a"]}
        self.assertEqual(normalize_arch(src, "mystery"), src)

    def test_does_not_mutate_input(self):
        src = {"fields": ["a"]}
        normalize_arch(src, "list")
        self.assertEqual(src["fields"], ["a"])


class MatchesPredicateTests(unittest.TestCase):
    def test_non_dict_is_false(self):
        self.assertFalse(_matches_predicate("x", {"name": "a"}))

    def test_all_keys_must_match(self):
        self.assertTrue(_matches_predicate({"a": 1, "b": 2}, {"a": 1}))
        self.assertFalse(_matches_predicate({"a": 1}, {"a": 2}))


class StepIntoTests(unittest.TestCase):
    def test_list_int_index(self):
        self.assertEqual(_step_into([10, 20], 1), 20)

    def test_list_str_name_match(self):
        self.assertEqual(_step_into([{"name": "x", "v": 1}], "x"), {"name": "x", "v": 1})

    def test_list_str_no_match_raises(self):
        with self.assertRaises(KeyError):
            _step_into([{"name": "x"}], "y")

    def test_list_predicate_match(self):
        self.assertEqual(_step_into([{"a": 1}, {"a": 2}], {"a": 2}), {"a": 2})

    def test_list_predicate_no_match_raises(self):
        with self.assertRaises(KeyError):
            _step_into([{"a": 1}], {"a": 9})

    def test_list_bad_seg_type_raises(self):
        with self.assertRaises(TypeError):
            _step_into([1, 2], 1.5)

    def test_dict_key(self):
        self.assertEqual(_step_into({"k": 5}, "k"), 5)

    def test_dict_missing_key_raises(self):
        with self.assertRaises(KeyError):
            _step_into({"k": 5}, "nope")

    def test_scalar_node_raises(self):
        with self.assertRaises(TypeError):
            _step_into(42, "k")


class ResolvePositionTests(unittest.TestCase):
    def test_int_in_range(self):
        self.assertEqual(_resolve_position([1, 2, 3], 1), 1)

    def test_int_out_of_range_raises(self):
        with self.assertRaises(KeyError):
            _resolve_position([1], 5)

    def test_str_name(self):
        self.assertEqual(_resolve_position([{"name": "x"}, {"name": "y"}], "y"), 1)

    def test_str_name_missing_raises(self):
        with self.assertRaises(KeyError):
            _resolve_position([{"name": "x"}], "z")

    def test_predicate(self):
        self.assertEqual(_resolve_position([{"a": 1}, {"a": 2}], {"a": 2}), 1)

    def test_predicate_missing_raises(self):
        with self.assertRaises(KeyError):
            _resolve_position([{"a": 1}], {"a": 9})

    def test_dict_key(self):
        self.assertEqual(_resolve_position({"k": 1}, "k"), "k")

    def test_dict_missing_key_raises(self):
        with self.assertRaises(KeyError):
            _resolve_position({"k": 1}, "nope")

    def test_bad_address_raises_type_error(self):
        with self.assertRaises(TypeError):
            _resolve_position(42, "k")


class FindDescendantTests(unittest.TestCase):
    def test_finds_in_nested_dict(self):
        root = {"a": {"b": {"name_key": 1}}}
        parent, seg = _find_descendant(root, "name_key")
        self.assertEqual(parent, {"name_key": 1})
        self.assertEqual(seg, "name_key")

    def test_finds_named_entry_in_nested_list(self):
        root = {"outer": [{"name": "target", "v": 9}]}
        parent, seg = _find_descendant(root, "target")
        self.assertEqual(parent, [{"name": "target", "v": 9}])

    def test_no_match_raises(self):
        with self.assertRaises(KeyError):
            _find_descendant({"a": 1}, "missing")


class ApplyOperationsTests(unittest.TestCase):
    def test_update_merges_into_dict(self):
        arch = _arch()
        apply_operations(arch, [
            {"op": "update", "target": ["sections", "main"], "value": {"label": "Main"}},
        ])
        self.assertEqual(arch["sections"][0]["label"], "Main")

    def test_update_non_dict_target_raises(self):
        with self.assertRaises(ValueError):
            apply_operations(_arch(), [
                {"op": "update", "target": ["sections", "main", "fields"], "value": {"x": 1}},
            ])

    def test_update_non_dict_value_raises(self):
        with self.assertRaises(ValueError):
            apply_operations(_arch(), [
                {"op": "update", "target": ["sections", "main"], "value": 5},
            ])

    def test_empty_target_raises(self):
        with self.assertRaises(ValueError):
            apply_operations(_arch(), [{"op": "set", "target": [], "value": 1}])

    def test_remove_list_entry(self):
        arch = _arch()
        apply_operations(arch, [
            {"op": "remove", "target": ["sections", "main", "fields", "a"]},
        ])
        names = [f["name"] for f in arch["sections"][0]["fields"]]
        self.assertEqual(names, ["b"])

    def test_set_new_dict_key(self):
        arch = _arch()
        apply_operations(arch, [
            {"op": "set", "target": ["sections", "main", "readonly"], "value": True},
        ])
        self.assertTrue(arch["sections"][0]["readonly"])

    def test_set_list_position(self):
        arch = _arch()
        apply_operations(arch, [
            {"op": "replace", "target": ["sections", "main", "fields", "b"],
             "value": {"name": "b", "readonly": True}},
        ])
        self.assertTrue(arch["sections"][0]["fields"][1]["readonly"])

    def test_before_inserts(self):
        arch = _arch()
        apply_operations(arch, [
            {"op": "before", "target": ["sections", "main", "fields", "a"],
             "value": {"name": "z"}},
        ])
        names = [f["name"] for f in arch["sections"][0]["fields"]]
        self.assertEqual(names, ["z", "a", "b"])

    def test_before_non_list_parent_raises(self):
        with self.assertRaises(ValueError):
            apply_operations(_arch(), [
                {"op": "before", "target": ["sections", "main", "name"], "value": 1},
            ])

    def test_after_inserts(self):
        arch = _arch()
        apply_operations(arch, [
            {"op": "after", "target": ["sections", "main", "fields", "a"],
             "value": {"name": "z"}},
        ])
        names = [f["name"] for f in arch["sections"][0]["fields"]]
        self.assertEqual(names, ["a", "z", "b"])

    def test_after_non_list_parent_raises(self):
        with self.assertRaises(ValueError):
            apply_operations(_arch(), [
                {"op": "after", "target": ["sections", "main", "name"], "value": 1},
            ])

    def test_unknown_op_raises(self):
        with self.assertRaises(ValueError):
            apply_operations(_arch(), [{"op": "frobnicate", "target": ["sections"]}])

    def test_wildcard_finds_descendant(self):
        arch = _arch()
        apply_operations(arch, [
            {"op": "set", "target": ["**", "a", "readonly"], "value": True},
        ])
        self.assertTrue(arch["sections"][0]["fields"][0]["readonly"])

    def test_wildcard_requires_selector(self):
        with self.assertRaises(ValueError):
            apply_operations(_arch(), [{"op": "set", "target": ["**"], "value": 1}])

    def test_wildcard_no_descendant_raises(self):
        with self.assertRaises(KeyError):
            apply_operations(_arch(), [
                {"op": "set", "target": ["**", "zzz", "x"], "value": 1},
            ])


# ----- resolve_arch with fake view objects -----

class _FakeUiViewMgr:
    def __init__(self, by_parent):
        self._by_parent = by_parent

    def search(self, domain, order=None):
        # domain shape: [("inherit_id", "=", parent_id)]
        parent_id = domain[0][2]
        return self._by_parent.get(parent_id, [])


class _FakeEnv:
    def __init__(self, by_parent=None):
        self._acl_bypass = False
        self._by_parent = by_parent or {}

    def __getitem__(self, _name):
        return _FakeUiViewMgr(self._by_parent)


class _FakeView:
    def __init__(self, env, *, id=1, inherit_id=None, arch=None,
                 view_type="form", module="m", name="n", operations=None):
        self.env = env
        self.id = id
        self.inherit_id = inherit_id
        self.arch = arch
        self.view_type = view_type
        self.module = module
        self.name = name
        self.operations = operations


class ResolveArchTests(unittest.TestCase):
    def test_base_view_resolves_and_normalizes(self):
        env = _FakeEnv()
        base = _FakeView(env, arch=json.dumps({"fields": ["a"]}), view_type="list")
        out = resolve_arch(base)
        self.assertEqual(out["fields"], [{"name": "a"}])
        self.assertFalse(env._acl_bypass)  # restored

    def test_extension_walks_up_to_root(self):
        env = _FakeEnv()
        base = _FakeView(env, id=1, arch=json.dumps({"fields": []}), view_type="list")
        ext = _FakeView(env, id=2, inherit_id=base, arch=None)
        out = resolve_arch(ext)
        self.assertEqual(out, {"fields": []})

    def test_root_without_arch_raises(self):
        env = _FakeEnv()
        view = _FakeView(env, arch=None)
        with self.assertRaises(ValueError):
            resolve_arch(view)

    def test_extension_operations_are_applied(self):
        # base (id=1) has one extension (id=2) carrying an op; the chain
        # walks it and applies the operation onto the resolved arch.
        env = _FakeEnv()
        base = _FakeView(
            env, id=1, arch=json.dumps({"fields": [{"name": "a"}]}), view_type="list"
        )
        ext = _FakeView(
            env, id=2, inherit_id=base,
            operations=json.dumps([
                {"op": "after", "target": ["fields", "a"], "value": "b"},
            ]),
        )
        env._by_parent = {1: [ext], 2: []}
        out = resolve_arch(base)
        # post-resolution normalize promotes the inserted string too.
        self.assertEqual(out["fields"], [{"name": "a"}, {"name": "b"}])


if __name__ == "__main__":
    unittest.main()
