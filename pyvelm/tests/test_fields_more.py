"""Unit tests for ``pyvelm.fields`` — targets >90% coverage."""
from __future__ import annotations

import unittest
from datetime import date, datetime, time
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Integer, Many2one, Registry, depends
from pyvelm.env import Cache, Environment
from pyvelm.fields import (
    Boolean,
    Code,
    Date,
    Datetime,
    Field,
    Float,
    Html,
    Many2many,
    Monetary,
    One2many,
    Time,
    _collection_ids_from_cache,
    _pluralize_label,
    _pluralize_word,
    _store_collection_cache,
    _title_words,
    finalize_related_field,
    spec_readonly,
)


def _stack_registry():
    """Partner + country + lines + tags for relational field tests."""
    reg = Registry()
    with reg.activate():

        class Tag(BaseModel):
            _name = "test.tag"
            name = Char()

        class Country(BaseModel):
            _name = "test.country"
            name = Char()

        class Line(BaseModel):
            _name = "test.line"
            partner_id = Many2one("test.partner")

        class Partner(BaseModel):
            _name = "test.partner"
            name = Char()
            country_id = Many2one("test.country")
            country_name = Char(related="country_id.name")
            line_ids = One2many("test.line", "partner_id")
            tag_ids = Many2many("test.tag")

    return reg, Partner, Country, Line, Tag


def _env(reg: Registry) -> Environment:
    return Environment(MagicMock(), registry=reg, uid=1)


class LabelHelperTests(unittest.TestCase):
    def test_title_and_plural_helpers(self):
        self.assertEqual(_title_words("partner_code"), "Partner Code")
        self.assertEqual(_pluralize_word("child"), "children")
        self.assertEqual(_pluralize_word("person"), "people")
        self.assertEqual(_pluralize_word("man"), "men")
        self.assertEqual(_pluralize_word("woman"), "women")
        self.assertEqual(_pluralize_word("Tag"), "Tags")
        self.assertEqual(_pluralize_word("bus"), "bus")
        self.assertEqual(_pluralize_word("city"), "cities")
        self.assertEqual(_pluralize_word("box"), "boxes")
        self.assertEqual(_pluralize_word("tags"), "tags")
        self.assertEqual(_pluralize_label("Sale Order"), "Sale Orders")
        self.assertEqual(_pluralize_word(""), "")
        self.assertEqual(_pluralize_label(""), "")


class FieldBaseTests(unittest.TestCase):
    def test_descriptor_on_class_returns_field(self):
        f = Char()
        self.assertIs(Char.__get__(f, None, object), f)

    def test_bind_related_clears_column(self):
        f = Char(related="other_id.name")
        f.bind("test.x", "rel_name")
        self.assertFalse(f.is_stored)
        self.assertIsNone(f.column)

    def test_column_ddl_required(self):
        f = Char(required=True)
        f.bind("m", "code")
        self.assertIn("NOT NULL", f.column_ddl())

    def test_empty_recordset_get_returns_default(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.m"
                note = Char(default="x")

        env = _env(reg)
        rec = M(env, ())
        self.assertEqual(rec.note, "x")

    def test_get_reads_from_cache(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.m2"
                note = Char()

        env = _env(reg)
        env.cache.set("test.m2", 1, "note", "cached")
        rec = M(env, (1,))
        self.assertEqual(rec.note, "cached")

    def test_get_triggers_read_on_miss(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.m3"
                note = Char()

        env = _env(reg)
        rec = M(env, (1,))

        def _fill(fields):
            for fname in fields:
                env.cache.set("test.m3", 1, fname, "db")

        with patch.object(rec, "_read", side_effect=_fill) as read:
            self.assertEqual(rec.note, "db")
        read.assert_called_once_with(["note"])

    def test_get_triggers_compute_on_miss(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.m4"
                total = Integer(compute="_compute_total", store=False)

                @depends("id")
                def _compute_total(self):
                    self.total = 42

        env = _env(reg)
        rec = M(env, (1,))
        self.assertEqual(rec.total, 42)

    def test_set_empty_recordset_is_noop(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.m5"
                note = Char()

        env = _env(reg)
        rec = M(env, ())
        M._fields["note"].__set__(rec, "x")  # no raise

    def test_set_inside_compute_updates_cache(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.m6"
                total = Integer(compute="_compute_total", store=False)

                @depends("id")
                def _compute_total(self):
                    pass

        env = _env(reg)
        env._in_compute = True
        rec = M(env, (1,))
        M._fields["total"].__set__(rec, 99)
        self.assertEqual(env.cache.get("test.m6", 1, "total"), 99)

    def test_base_to_python_passthrough(self):
        self.assertEqual(Field().to_python("raw"), "raw")

    def test_set_readonly_raises(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.m_ro"
                code = Char(readonly=True)

        env = _env(reg)
        rec = M(env, (1,))
        with self.assertRaises(ValueError):
            rec.code = "nope"

    def test_set_compute_outside_compute_raises(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.m_cmp"
                total = Integer(compute="_compute_total", store=True)

                @depends("id")
                def _compute_total(self):
                    self.total = 1

        env = _env(reg)
        rec = M(env, (1,))
        with self.assertRaises(ValueError):
            rec.total = 9

    def test_set_delegates_to_write(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.m7"
                note = Char()

        env = _env(reg)
        rec = M(env, (1,))
        with patch.object(rec, "write") as write:
            rec.note = "hello"
        write.assert_called_once_with({"note": "hello"})


class ScalarFieldCoercionTests(unittest.TestCase):
    def test_char_empty_and_choices(self):
        f = Char(choices=[("a", "Alpha"), "b"])
        self.assertIsNone(f.to_python(False))
        self.assertIsNone(f.to_sql_param(False))
        self.assertEqual(f.to_python("x"), "x")
        self.assertEqual(f.choices, [("a", "Alpha"), ("b", "b")])

    def test_code_language_and_empty(self):
        f = Code(language="python")
        f.bind("m", "body")
        self.assertEqual(f.language, "python")
        self.assertIsNone(f.to_python(""))
        self.assertIsNone(f.to_sql_param(""))
        self.assertEqual(f.to_python("print(1)"), "print(1)")
        self.assertEqual(f.to_sql_param("print(1)"), "print(1)")

    def test_code_unsupported_language(self):
        with self.assertRaises(ValueError):
            Code(language="brainfuck")

    def test_html_sanitizes(self):
        f = Html()
        self.assertIsNone(f.to_python(""))
        self.assertIsNone(f.to_sql_param(None))
        with patch("pyvelm.html_sanitizer.sanitize_html", return_value="<p>ok</p>"):
            self.assertEqual(f.to_python("<script>x</script>"), "<p>ok</p>")
            self.assertEqual(f.to_sql_param("x"), "<p>ok</p>")

    def test_integer_float_boolean(self):
        self.assertIsNone(Integer().to_python(None))
        self.assertEqual(Integer().to_python(3), 3)
        self.assertEqual(Float().to_python("1.5"), 1.5)
        self.assertTrue(Boolean().to_python(1))

    def test_datetime_date_time_params(self):
        dt = Datetime()
        self.assertIsNone(dt.to_sql_param(""))
        val = datetime(2026, 1, 2, 3, 4)
        self.assertEqual(dt.to_sql_param(val), val)
        self.assertEqual(dt.to_sql_param(date(2026, 1, 2)), datetime(2026, 1, 2, 0, 0))
        self.assertEqual(dt.to_sql_param("2026-01-02T03:04"), datetime(2026, 1, 2, 3, 4))
        self.assertEqual(Date().to_sql_param(date(2026, 1, 2)), date(2026, 1, 2))
        self.assertEqual(Date().to_sql_param(datetime(2026, 1, 2, 3, 4)), date(2026, 1, 2))
        self.assertEqual(Time().to_sql_param("08:30"), time(8, 30))
        self.assertEqual(Time().to_sql_param(datetime(2026, 1, 2, 8, 30)), time(8, 30))
        self.assertEqual(Time().to_sql_param("08:30:45"), time(8, 30, 45))

    def test_monetary_round_with_edges(self):
        m = Monetary(currency_field="currency_id")
        self.assertEqual(m.currency_field, "currency_id")
        cur = MagicMock()
        cur.rounding = 0.01
        self.assertAlmostEqual(Monetary.round_with(1.234, cur), 1.23)
        self.assertEqual(Monetary.round_with(None, cur), None)
        self.assertEqual(Monetary.round_with(5.0, None), 5.0)
        cur.rounding = 0
        self.assertEqual(Monetary.round_with(3.3, cur), 3.3)
        cur.rounding = -1
        self.assertEqual(Monetary.round_with(2.5, cur), 2.5)

    def test_datetime_date_time_ddl_and_to_python(self):
        dt = Datetime()
        dt.bind("m", "when")
        self.assertIn("timestamp", dt.column_ddl())
        self.assertEqual(dt.to_python(datetime(2026, 1, 1)), datetime(2026, 1, 1))
        d = Date(required=True)
        d.bind("m", "day")
        self.assertIn('"day" date', d.column_ddl())
        d2 = Date()
        d2.bind("m", "optional_day")
        self.assertIn(" NULL", d2.column_ddl())
        self.assertEqual(d.to_python(date(2026, 1, 2)), date(2026, 1, 2))
        self.assertEqual(d.to_sql_param(date(2026, 1, 2)), date(2026, 1, 2))
        self.assertEqual(
            d.to_sql_param(datetime(2026, 1, 2, 15, 30)),
            date(2026, 1, 2),
        )
        self.assertEqual(d.to_sql_param("2026-01-03"), date(2026, 1, 3))
        t = Time()
        t.bind("m", "at")
        self.assertIn("time", t.column_ddl())
        t2 = Time()
        t2.bind("m", "optional_at")
        self.assertIn(" NULL", t2.column_ddl())
        self.assertEqual(t.to_python(time(9, 0)), time(9, 0))
        self.assertIsNone(t.to_sql_param(""))
        self.assertEqual(t.to_sql_param(time(10, 0)), time(10, 0))
        self.assertEqual(t.to_sql_param("12:34:56"), time(12, 34, 56))


class Many2oneFieldTests(unittest.TestCase):
    def test_many2one_labels_and_sql_param(self):
        f = Many2one("res.partner")
        f.bind("sale.order", "partner_id")
        self.assertEqual(f.string, "Partner")
        f2 = Many2one("res.partner")
        f2.bind("x", "partner")
        self.assertEqual(f2.string, "Partner")
        empty_rs = MagicMock()
        empty_rs._ids = []
        self.assertIsNone(f.to_sql_param(empty_rs))
        self.assertIsNone(f.to_sql_param(None))
        rs = MagicMock()
        rs._ids = [7]
        self.assertEqual(f.to_sql_param(rs), 7)
        self.assertEqual(f.to_sql_param(7), 7)
        with self.assertRaises(ValueError):
            multi = MagicMock()
            multi._ids = [1, 2]
            f.to_sql_param(multi)

    def test_many2one_get_empty_and_cached(self):
        reg, Partner, Country, *_ = _stack_registry()
        env = _env(reg)
        empty = Partner(env, ())
        self.assertEqual(empty.country_id._ids, ())
        env.cache.set("test.partner", 1, "country_id", 5)
        env.cache.set("test.country", 5, "name", "BE")
        rec = Partner(env, (1,))
        country = rec.country_id
        self.assertEqual(country._ids, (5,))
        self.assertEqual(country.name, "BE")

    def test_many2one_get_reads_fk_and_null_fk(self):
        reg, Partner, Country, *_ = _stack_registry()
        env = _env(reg)
        rec = Partner(env, (1,))

        def _fill(fields):
            env.cache.set("test.partner", 1, "country_id", 3)

        with patch.object(rec, "_read", side_effect=_fill) as read:
            self.assertEqual(rec.country_id._ids, (3,))
        read.assert_called_with(["country_id"])
        env.cache.set("test.partner", 1, "country_id", None)
        self.assertEqual(rec.country_id._ids, ())

    def test_many2one_descriptor_on_class(self):
        reg, Partner, *_ = _stack_registry()
        f = Partner._fields["country_id"]
        self.assertIs(f.__get__(None, Partner), f)

    def test_many2one_related_delegates_to_field_get(self):
        reg, Partner, Country, *_ = _stack_registry()
        env = _env(reg)
        partner = Partner(env, (1,))
        f = Many2one("test.country")
        f.related = "country_id"
        f.comodel_name = "test.country"
        f.bind("test.partner", "mirror_country_id")
        with patch.object(Field, "__get__", return_value=Country(env, (2,))) as super_get:
            got = f.__get__(partner, Partner)
        super_get.assert_called_once()
        self.assertEqual(got._ids, (2,))


class RelatedFieldBehaviorTests(unittest.TestCase):
    def test_related_read_and_write(self):
        reg, Partner, Country, *_ = _stack_registry()
        env = _env(reg)
        env.cache.set("test.country", 2, "name", "France")
        env.cache.set("test.partner", 1, "country_id", 2)
        partner = Partner(env, (1,))
        self.assertEqual(partner.country_name, "France")
        with reg.activate():
            partner.country_name = "Belgium"
        self.assertEqual(env.cache.get("test.country", 2, "name"), "Belgium")

    def test_related_read_from_cache_slot(self):
        reg, Partner, *_ = _stack_registry()
        env = _env(reg)
        env.cache.set("test.partner", 1, "country_name", "Cached")
        partner = Partner(env, (1,))
        self.assertEqual(partner.country_name, "Cached")

    def test_related_set_missing_hop_raises(self):
        reg, Partner, *_ = _stack_registry()
        env = _env(reg)
        env.cache.set("test.partner", 1, "country_id", None)
        partner = Partner(env, (1,))
        with self.assertRaises(ValueError):
            partner.country_name = "X"

    def test_related_read_empty_hop_returns_default(self):
        reg, Partner, *_ = _stack_registry()
        env = _env(reg)
        env.cache.set("test.partner", 1, "country_id", None)
        partner = Partner(env, (1,))
        f = Partner._fields["country_name"]
        self.assertIsNone(f._read_related_value(partner))

    def test_related_get_empty_recordset(self):
        reg, Partner, *_ = _stack_registry()
        env = _env(reg)
        partner = Partner(env, ())
        self.assertIsNone(partner.country_name)

    def test_related_set_readonly_leaf_raises(self):
        reg = Registry()
        with reg.activate():

            class Country(BaseModel):
                _name = "test.country2"
                code = Char(readonly=True)

            class Partner(BaseModel):
                _name = "test.partner2"
                country_id = Many2one("test.country2")
                country_code = Char(related="country_id.code")

        env = _env(reg)
        env.cache.set("test.country2", 1, "code", "X")
        env.cache.set("test.partner2", 1, "country_id", 1)
        partner = Partner(env, (1,))
        with self.assertRaises(ValueError):
            partner.country_code = "Y"

    def test_related_empty_helpers(self):
        reg, Partner, Country, Line, Tag = _stack_registry()
        env = _env(reg)
        f_char = Partner._fields["country_name"]
        self.assertIsNone(f_char._related_empty(Partner(env, (1,))))
        f_m2o = Partner._fields["country_id"]
        empty = f_m2o._related_empty(Partner(env, (1,)))
        self.assertEqual(empty._ids, ())
        f_o2m = Partner._fields["line_ids"]
        self.assertEqual(f_o2m._related_empty(Partner(env, (1,)))._ids, ())
        f_m2m = Partner._fields["tag_ids"]
        self.assertEqual(f_m2m._related_empty(Partner(env, (1,)))._ids, ())

    def test_related_cache_value_many2one_variants(self):
        reg, Partner, *_ = _stack_registry()
        env = _env(reg)
        f = Partner._fields["country_id"]
        self.assertIsNone(f._related_cache_value(None))
        rs = Partner(env, (9,))
        self.assertEqual(f._related_cache_value(rs), 9)
        self.assertEqual(f._related_cache_value(9), 9)
        self.assertIsNone(f._related_cache_value(Partner(env, ())))
        o2m = Partner._fields["line_ids"]
        self.assertIsNone(o2m._related_cache_value(Partner(env, (1,)).line_ids))
        self.assertIsNone(
            Partner._fields["country_name"]._related_cache_value(
                MagicMock(_ids=(1,))
            )
        )

    def test_related_from_cache_many2one(self):
        reg, Partner, *_ = _stack_registry()
        env = _env(reg)
        f = Partner._fields["country_id"]
        empty = f._related_from_cache(Partner(env, (1,)), None)
        self.assertEqual(empty._ids, ())
        got = f._related_from_cache(Partner(env, (1,)), 3)
        self.assertEqual(got._ids, (3,))


class One2manyMany2manyTests(unittest.TestCase):
    def setUp(self):
        self.reg, self.Partner, self.Country, self.Line, self.Tag = _stack_registry()
        self.env = _env(self.reg)

    def test_collection_cache_helpers(self):
        cache = Cache()
        self.assertIsNone(_collection_ids_from_cache(cache, "m", 1, "x"))
        _store_collection_cache(cache, "m", 1, "x", (1, 2))
        cache.set("m", 1, "x", "not-a-tuple")
        self.assertIsNone(_collection_ids_from_cache(cache, "m", 1, "x"))
        cache.set("m", 1, "x", (3,))
        self.assertEqual(_collection_ids_from_cache(cache, "m", 1, "x"), (3,))

    def test_one2many_from_cache_and_sql(self):
        _store_collection_cache(self.env.cache, "test.partner", 1, "line_ids", (10, 11))
        partner = self.Partner(self.env, (1,))
        lines = partner.line_ids
        self.assertEqual(lines._ids, (10, 11))
        partner2 = self.Partner(self.env, (2,))
        self.env.conn.execute.return_value.fetchall.return_value = [(20,)]
        lines2 = partner2.line_ids
        self.assertEqual(lines2._ids, (20,))

    def test_one2many_cannot_assign_directly(self):
        partner = self.Partner(self.env, (1,))
        with self.assertRaises(NotImplementedError):
            partner.line_ids = [1, 2]

    def test_one2many_labels_and_no_column(self):
        f = One2many("test.line", "partner_id")
        f.bind("test.partner", "line_ids")
        self.assertEqual(f.string, "Lines")
        f2 = One2many("test.line", "partner_id")
        f2.bind("test.partner", "lines")
        self.assertEqual(f2.string, "Lines")
        with self.assertRaises(RuntimeError):
            f.column_ddl()
        with self.assertRaises(NotImplementedError):
            f.to_sql_param([])
        self.assertIs(One2many.__get__(f, None, object), f)
        empty = self.Partner(self.env, ())
        self.assertEqual(empty.line_ids._ids, ())

    def test_many2many_from_cache_and_sql(self):
        _store_collection_cache(self.env.cache, "test.partner", 1, "tag_ids", (4, 5))
        partner = self.Partner(self.env, (1,))
        tags = partner.tag_ids
        self.assertEqual(tags._ids, (4, 5))
        partner2 = self.Partner(self.env, (3,))
        self.env.conn.execute.return_value.fetchall.return_value = [(6,)]
        self.assertEqual(partner2.tag_ids._ids, (6,))

    def test_many2many_set_and_normalize(self):
        partner = self.Partner(self.env, (1,))
        with patch.object(partner, "write") as write:
            partner.tag_ids = [7, 8]
        write.assert_called_once()
        empty_partner = self.Partner(self.env, ())
        empty_partner.tag_ids = [1]  # no-op on empty recordset
        self.assertEqual(Many2many.normalize_ids(None), [])
        self.assertEqual(Many2many.normalize_ids(5), [5])
        rs = self.Tag(self.env, (3,))
        self.assertEqual(Many2many.normalize_ids(rs), [3])
        self.assertEqual(
            Many2many.normalize_ids([None, False, rs, 4]),
            [3, 4],
        )
        skip = MagicMock(_ids=())
        self.assertEqual(Many2many.normalize_ids([skip]), [])
        with self.assertRaises(ValueError):
            Many2many.normalize_ids([MagicMock(_ids=(1, 2))])

    def test_many2many_labels_and_to_sql_param(self):
        f = Many2many("test.tag")
        f.bind("test.partner", "tag_ids")
        self.assertEqual(f.string, "Tags")
        f2 = Many2many("test.tag")
        f2.bind("test.partner", "tags")
        self.assertEqual(f2.string, "Tags")
        with self.assertRaises(NotImplementedError):
            f.to_sql_param([])
        self.assertIs(Many2many.__get__(f, None, object), f)
        self.assertEqual(self.Partner(self.env, ()).tag_ids._ids, ())

    def test_many2many_self_without_relation_raises(self):
        reg = Registry()
        with reg.activate():

            class Node(BaseModel):
                _name = "test.node2"
                peer_ids = Many2many("test.node2")

        f = Node._fields["peer_ids"]
        with self.assertRaises(ValueError):
            f.resolve_spec(Node, reg)

    def test_many2many_self_explicit_relation(self):
        reg = Registry()
        with reg.activate():

            class Node(BaseModel):
                _name = "test.node"
                left_ids = Many2many(
                    "test.node",
                    relation="node_rel",
                    column1="src_id",
                    column2="dst_id",
                )

        rel, c1, c2, _, _ = Node._fields["left_ids"].resolve_spec(Node, reg)
        self.assertEqual(rel, "node_rel")
        self.assertEqual(c1, "src_id")
        self.assertEqual(c2, "dst_id")


class FinalizeRelatedTests(unittest.TestCase):
    def test_finalize_success_and_comodel_mismatch(self):
        reg = Registry()
        with reg.activate():

            class Other(BaseModel):
                _name = "test.other"

            class Country(BaseModel):
                _name = "test.c3"
                name = Char()
                other_id = Many2one("test.other")

            class Partner(BaseModel):
                _name = "test.p3"
                country_id = Many2one("test.c3")
                country_name = Char(related="country_id.name")
                other_id = Many2one("test.other", related="country_id.other_id")

        with reg.activate():
            finalize_related_field(Partner, Partner._fields["country_name"])
            self.assertEqual(
                Partner._fields["country_name"].depends_on,
                ("country_id.name",),
            )
            f = Partner._fields["other_id"]
            f.comodel_name = "wrong.model"
            with self.assertRaises(ValueError):
                finalize_related_field(Partner, f)

    def test_finalize_type_mismatch(self):
        reg = Registry()
        with reg.activate():

            class Country(BaseModel):
                _name = "test.c4"
                amount = Integer()

            with self.assertRaises(ValueError):

                class Partner(BaseModel):
                    _name = "test.p4"
                    country_id = Many2one("test.c4")
                    country_amount = Char(related="country_id.amount")

    def test_finalize_compute_and_related_conflict(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.m_fin"
                y = Char()

        f = Char(compute="_c", related="y")
        f.bind("test.m_fin", "x")
        with reg.activate(), self.assertRaises(ValueError):
            finalize_related_field(M, f)

    def test_finalize_related_rejects_non_m2o_path(self):
        reg = Registry()
        with reg.activate():

            class Partner(BaseModel):
                _name = "test.p5"
                country_name = Char()

        f = Partner._fields["country_name"]
        f.related = "tag_ids.name"
        with patch("pyvelm.paths.parse_path") as parse_path:
            parse_path.return_value = MagicMock(is_m2o_only=lambda: False)
            with reg.activate(), self.assertRaises(ValueError):
                finalize_related_field(Partner, f)

    def test_finalize_noop_without_related(self):
        f = Char()
        finalize_related_field(object(), f)


class SpecReadonlyTests(unittest.TestCase):
    def test_spec_readonly(self):
        f = Char(readonly=True)
        self.assertTrue(spec_readonly({"readonly": True}, f))
        self.assertFalse(spec_readonly({"readonly": False}, f))
        self.assertTrue(spec_readonly({}, f))


if __name__ == "__main__":
    unittest.main()
