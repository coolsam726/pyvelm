"""Schema predicate evaluation and view field fluent builders."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from pyvelm import BaseModel, Char, Many2one, Registry
from pyvelm.builders import Field
from pyvelm.database.sa_alter import execute_create_unique
from pyvelm.field_builders import OrmFieldBuilder
from pyvelm.fields import spec_readonly
from pyvelm.schema_eval import (
    SchemaContext,
    _call_predicate,
    _compare_leaf,
    _resolve_leaf_value,
    parse_live_spec,
    record_matches_domain,
    resolve_schema_bool,
    spec_readonly_schema,
    spec_required,
    spec_visible,
)
from pyvelm.tests.support.sa_ddl import wire_sa_conn


class _FakeRecord:
    _ids = (1,)

    def __init__(self, fields, values):
        self._fields = fields
        self._values = values

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._values.get(name)


class SchemaEvalTests(unittest.TestCase):
    def test_visible_when_domain(self):
        ctx = SchemaContext(env=None, submitted={"kind": "company"})
        spec = {"name": "vat", "visible_when": [("kind", "=", "company")]}
        self.assertTrue(spec_visible(spec, ctx))
        ctx.submitted = {"kind": "person"}
        self.assertFalse(spec_visible(spec, ctx))

    def test_visible_callable_three_arg(self):
        spec = {
            "name": "note",
            "visible": lambda record, env, get: get("show") is True,
        }
        ctx = SchemaContext(env=None, submitted={"show": True})
        self.assertTrue(spec_visible(spec, ctx))

    def test_hidden_callable_and_literal(self):
        spec = {"name": "x", "hidden": lambda _r, _e, get: get("hide")}
        ctx = SchemaContext(env=None, submitted={"hide": True})
        self.assertFalse(spec_visible(spec, ctx))
        self.assertFalse(spec_visible({"name": "x", "hidden": True}, ctx))
        spec2 = {"name": "x", "hidden": False}
        self.assertTrue(spec_visible(spec2, ctx))

    def test_field_builder_shortcuts(self):
        spec = (
            Field.make("code")
            .required_when([("active", "=", True)])
            .visible_when([("type", "=", "biz")])
            .readonly_when([("locked", "=", True)])
            .hidden(False)
            .visible_js("$get('type') === 'biz'")
            .live(debounce=300)
            .live(on_blur=True)
            .depends_on("type")
            .options_domain([("active", "=", True)])
            .default(lambda _r, _e, _g: "x")
            .to_dict()
        )
        self.assertEqual(spec["required_when"], [("active", "=", True)])
        self.assertEqual(spec["visible_when"], [("type", "=", "biz")])
        self.assertEqual(spec["live"], "blur")
        self.assertEqual(spec["depends_on"], ["type"])

    def test_record_matches_domain_and_or_not(self):
        ctx = SchemaContext(env=None, submitted={"a": 1, "b": 2, "tag": "vip"})
        self.assertTrue(record_matches_domain([("a", "=", 1), ("b", "=", 2)], ctx))
        self.assertTrue(record_matches_domain(["|", ("a", "=", 9), ("b", "=", 2)], ctx))
        self.assertFalse(record_matches_domain(["&", ("a", "=", 9), ("b", "=", 2)], ctx))
        self.assertTrue(record_matches_domain(["!", ("a", "=", 9)], ctx))
        self.assertTrue(record_matches_domain([], ctx))

    def test_resolve_schema_bool_variants(self):
        ctx = SchemaContext(env=None, submitted={})

        def _pred(context):
            return context.get("x") == 1

        self.assertFalse(resolve_schema_bool(_pred, ctx))
        ctx.submitted = {"x": 1}
        self.assertTrue(resolve_schema_bool(_pred, ctx))
        self.assertTrue(resolve_schema_bool(None, ctx, default=True))
        self.assertFalse(resolve_schema_bool(None, ctx, default=False))
        self.assertTrue(resolve_schema_bool(True, ctx))
        self.assertFalse(resolve_schema_bool(False, ctx))

    def test_call_predicate_arity(self):
        ctx = SchemaContext(env=None, submitted={"n": 3})
        self.assertTrue(_call_predicate(lambda: True, ctx))
        self.assertTrue(_call_predicate(lambda c: c.get("n") == 3, ctx))
        self.assertTrue(_call_predicate(lambda r, e: True, ctx))
        self.assertTrue(_call_predicate(lambda r, e, g: g("n") == 3, ctx))

    def test_schema_context_get_submitted_and_record(self):
        reg = Registry()
        with reg.activate():

            class Country(BaseModel):
                _name = "test.schema.country"
                code = Char()

            class Partner(BaseModel):
                _name = "test.schema.partner"
                name = Char()
                country_id = Many2one("test.schema.country")

        country = _FakeRecord(Country._fields, {"id": 5, "code": "US"})
        country._ids = (5,)
        partner = _FakeRecord(
            Partner._fields,
            {"name": "Acme", "country_id": country},
        )
        ctx = SchemaContext(env=None, record=partner, submitted={"name": "New"})
        self.assertEqual(ctx.get("name"), "New")
        ctx.submitted = {}
        self.assertEqual(ctx.get("name"), "Acme")
        self.assertEqual(ctx.get("country_id"), 5)
        self.assertIsNone(ctx.get("missing", None))

    def test_resolve_leaf_dotted_path(self):
        reg = Registry()
        with reg.activate():

            class Country(BaseModel):
                _name = "test.leaf.country"
                code = Char()

        country = _FakeRecord(Country._fields, {"code": "US"})
        country._ids = (1,)
        ctx = SchemaContext(env=None, submitted={"country_id": country})
        self.assertEqual(_resolve_leaf_value(ctx, "country_id.code"), "US")

    def test_compare_leaf_operators(self):
        self.assertTrue(_compare_leaf(2, "<", 3))
        self.assertTrue(_compare_leaf(2, "<=", 2))
        self.assertTrue(_compare_leaf(3, ">", 2))
        self.assertTrue(_compare_leaf(3, ">=", 3))
        self.assertTrue(_compare_leaf("ab", "like", "a"))
        self.assertTrue(_compare_leaf("Ab", "ilike", "ab"))
        self.assertTrue(_compare_leaf("x", "in", ["x", "y"]))
        self.assertTrue(_compare_leaf("z", "not in", ["x", "y"]))
        with self.assertRaises(ValueError):
            _compare_leaf(1, "??", 2)

    def test_spec_required_and_readonly(self):
        field = Char(required=False)
        ctx = SchemaContext(env=None, submitted={"active": True})
        spec = {"name": "x", "required_when": [("active", "=", True)]}
        self.assertTrue(spec_required(spec, field, ctx))
        spec2 = {"name": "x", "readonly_when": [("active", "=", True)]}
        self.assertTrue(spec_readonly_schema(spec2, field, ctx))
        self.assertTrue(spec_readonly({"readonly": True}, field))

    def test_parse_live_spec(self):
        self.assertIsNone(parse_live_spec(None))
        self.assertEqual(parse_live_spec(True), {"debounce": None, "on_blur": False})
        self.assertEqual(parse_live_spec("blur"), {"debounce": None, "on_blur": True})
        self.assertEqual(parse_live_spec(250), {"debounce": 250, "on_blur": False})
        self.assertEqual(
            parse_live_spec({"debounce": 100, "on_blur": True}),
            {"debounce": 100, "on_blur": True},
        )
        self.assertIsNone(parse_live_spec("nope"))


class OrmIndexUniqueTests(unittest.TestCase):
    def test_field_fluent_index_unique(self):
        reg = Registry()
        with reg.activate():

            class Demo(BaseModel):
                _name = "demo.idx"
                _table = "demo_idx"

                code = Char().unique().index(name="demo_code_idx")

        field = Demo._fields["code"]
        self.assertTrue(field.unique)
        self.assertTrue(field.index)
        self.assertEqual(field.index_name, "demo_code_idx")

    def test_collect_model_constraints(self):
        from pyvelm.database.sa_ddl import (
            collect_model_sql_indexes,
            collect_model_sql_uniques,
            ensure_model_indexes_and_uniques,
        )

        reg = Registry()
        with reg.activate():

            class Demo(BaseModel):
                _name = "demo.col"
                _table = "demo_col"
                _sql_uniques = (("demo_pair_uniq", ("code", "name")),)

                code = Char().unique()
                name = Char().index()

        idx = collect_model_sql_indexes(Demo)
        uniq = collect_model_sql_uniques(Demo)
        self.assertIn(("demo_col_name_idx", ("name",)), idx)
        self.assertIn(("demo_col_code_uniq", ("code",)), uniq)
        self.assertIn(("demo_pair_uniq", ("code", "name")), uniq)

        executed: list[str] = []
        conn = MagicMock()
        wire_sa_conn(conn, executed, dialect_name="postgresql")
        ensure_model_indexes_and_uniques(conn, Demo)
        joined = "\n".join(executed).upper()
        self.assertIn("UNIQUE", joined)
        self.assertIn("INDEX", joined)

    def test_execute_create_unique(self):
        executed: list[str] = []
        conn = MagicMock()
        wire_sa_conn(conn, executed, dialect_name="sqlite")
        execute_create_unique(conn, "uq_email", "demo_uq", ("email",))
        self.assertIn("UNIQUE", executed[0].upper())

    def test_orm_builder_constraint_kwargs(self):
        built = OrmFieldBuilder(Char).unique("u1").index("i1").build()
        self.assertTrue(built.unique)
        self.assertEqual(built.unique_name, "u1")
        self.assertTrue(built.index)
        self.assertEqual(built.index_name, "i1")


def _load_contacts_hooks():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "modules" / "contacts" / "hooks.py"
    spec = importlib.util.spec_from_file_location("contacts_hooks_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class ContactsHooksTests(unittest.TestCase):
    def test_backfill_partner_codes(self):
        hooks = _load_contacts_hooks()

        env = MagicMock()
        env.registry = {"res.partner": object()}
        partner = MagicMock()
        partner.name = "Acme"
        partner.id = 42
        partner.code = None
        Partner = MagicMock()
        Partner.search.return_value = [partner]
        env.__getitem__.return_value = Partner
        hooks._backfill_partner_codes(env)
        self.assertEqual(partner.code, "ACM-42")

    def test_sync_and_install_delegate(self):
        import unittest.mock

        hooks = _load_contacts_hooks()

        env = MagicMock()
        env.registry = {}
        hooks.sync(env)
        with unittest.mock.patch.object(hooks, "grant_model_access") as grant:
            hooks.install(env)
        self.assertEqual(grant.call_count, 3)


if __name__ == "__main__":
    unittest.main()
