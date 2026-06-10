"""Tests for :mod:`pyvelm.query` (Eloquent-style query builder)."""
from __future__ import annotations

import unittest

from pyvelm import (
    BaseModel,
    Boolean,
    Char,
    Environment,
    Integer,
    Many2many,
    Many2one,
    Page,
    Query,
    RecordNotFound,
    Registry,
    models,
)
from pyvelm.database import create_database_from_dsn
from pyvelm.domain import normalize_domain


class _QueryFixture(unittest.TestCase):
    """Shared sqlite registry with Post (+ _inherit ext) and Tag M2m."""

    reg: Registry
    db: object

    @classmethod
    def setUpClass(cls):
        cls.reg = Registry()
        with cls.reg.activate():

            class Tag(BaseModel):
                _name = "test.query.tag"
                _table = "test_query_tag"
                name = Char()

            class Post(BaseModel):
                _name = "test.query.post"
                _table = "test_query_post"
                title = Char()
                score = Integer()
                active = Boolean(default=True)
                tag_ids = Many2many("test.query.tag")

        with cls.reg.activate():

            class PostExt(models.Model):
                _inherit = "test.query.post"
                featured = Boolean(default=False)

        cls.db = create_database_from_dsn("sqlite:///:memory:", pool_size=2)
        conn = cls.db.open_connection()
        try:
            cls.reg.init_db(conn)
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.db.dispose()

    def _env(self) -> Environment:
        conn = self.db.open_connection()
        self.addCleanup(conn.close)
        env = Environment(conn, registry=self.reg, uid=1)
        env._acl_bypass = True
        return env

    def _clear(self, env: Environment) -> None:
        with self.reg.activate():
            env["test.query.post"].search([]).unlink()
            env["test.query.tag"].search([]).unlink()

    def _seed(self, env: Environment) -> None:
        self._clear(env)
        with self.reg.activate():
            Tag = env["test.query.tag"]
            Post = env["test.query.post"]
            vip = Tag.create({"name": "VIP"})
            Tag.create({"name": "News"})
            Post.create({"title": "Low", "score": 10, "active": True})
            high = Post.create(
                {
                    "title": "High",
                    "score": 90,
                    "active": True,
                    "featured": True,
                }
            )
            high.write({"tag_ids": [vip.id]})
            Post.create({"title": "Off", "score": 50, "active": False})


class QueryValidationTests(unittest.TestCase):
    def test_where_missing_value_raises(self):
        q = Query.for_model(object(), Environment(object(), Registry()))
        with self.assertRaises(TypeError):
            q.where("name")
        with self.assertRaises(TypeError):
            q.where("age", ">")

    def test_invalid_field_and_order_direction(self):
        reg = Registry()
        with reg.activate():

            class M(BaseModel):
                _name = "test.query.validate"
                _table = "test_query_validate"
                name = Char()

        env = Environment(object(), reg)
        q = Query.for_model(reg["test.query.validate"], env)
        with self.assertRaises(ValueError):
            q.where("bad-field!", "=", 1)
        with self.assertRaises(ValueError):
            q.order_by("name", "sideways")
        with self.assertRaises(ValueError):
            q.limit(-1)
        with self.assertRaises(ValueError):
            q.offset(-1)

    def test_page_last_page_edge_cases(self):
        self.assertEqual(Page(items=object(), total=0, page=1, per_page=15).last_page, 1)
        self.assertEqual(Page(items=object(), total=10, page=1, per_page=0).last_page, 1)
        p = Page(items=object(), total=25, page=2, per_page=10)
        self.assertEqual(p.last_page, 3)
        self.assertTrue(p.has_more)
        last = Page(items=object(), total=25, page=3, per_page=10)
        self.assertFalse(last.has_more)


class QueryBuilderTests(_QueryFixture):
    def test_env_query_uses_registry_class(self):
        env = self._env()
        qb = env.query("test.query.post")
        self.assertIs(qb._model_cls, env.registry["test.query.post"])
        self.assertIn("featured", qb._model_cls._fields)

    def test_recordset_query_matches_env_query(self):
        env = self._env()
        rs_q = env["test.query.post"].query()
        env_q = env.query("test.query.post")
        self.assertIs(rs_q._model_cls, env_q._model_cls)

    def test_where_get_and_order_by(self):
        env = self._env()
        self._seed(env)
        rows = (
            env["test.query.post"]
            .query()
            .where("score", ">", 40)
            .order_by("score", "desc")
            .get()
        )
        self.assertEqual([r.title for r in rows], ["High", "Off"])

    def test_where_sugar_and_pluck(self):
        env = self._env()
        self._seed(env)
        names = (
            env.query("test.query.post")
            .where("active", True)
            .order_by("id")
            .pluck("title")
        )
        self.assertEqual(names, ["Low", "High"])

    def test_where_in_not_in_null_filters(self):
        env = self._env()
        self._seed(env)
        q = env["test.query.post"].query()
        titles = (
            q.where_in("title", ["Low", "Off"])
            .order_by("id")
            .pluck("title")
        )
        self.assertEqual(titles, ["Low", "Off"])

        active_only = (
            env["test.query.post"]
            .query()
            .where_not_in("title", ["Off"])
            .where_not_null("title")
            .order_by("id")
            .pluck("title")
        )
        self.assertEqual(active_only, ["Low", "High"])

    def test_or_where_empty_domain_and_all_flag(self):
        env = self._env()
        self._seed(env)
        first = (
            env["test.query.post"]
            .query()
            .or_where("title", "Low")
            .pluck("title")
        )
        self.assertEqual(first, ["Low"])
        q = env["test.query.post"].query().or_where(
            "tag_ids.name", "=", "VIP", all=True
        )
        self.assertEqual(q.domain[0][-1], {"all": True})

    def test_where_null_and_where_any_edges(self):
        env = self._env()
        self._seed(env)
        Post = env["test.query.post"]
        self.assertEqual(Post.query().where_any([]).count(), 3)
        merged = Post.query().where("active", True).where_any([("title", "=", "Off")])
        self.assertTrue(len(merged.domain) > 1)
        null_q = Post.query().where_null("title")
        self.assertIn(("title", "=", None), null_q.domain)
        self.assertEqual(Post.query().where_not_null("title").count(), 3)

    def test_parse_predicate_two_arg_form(self):
        env = self._env()
        self._seed(env)
        rows = env["test.query.post"].query().where("title", "High").pluck("title")
        self.assertEqual(rows, ["High"])

    def test_parse_predicate_three_arg_explicit_eq(self):
        env = self._env()
        self._seed(env)
        rows = (
            env["test.query.post"]
            .query()
            .where("title", "=", "High")
            .pluck("title")
        )
        self.assertEqual(rows, ["High"])

    def test_chunk_stops_on_empty_batch(self):
        env = self._env()
        self._seed(env)
        batches = list(
            env["test.query.post"].query().where("title", "Nope").chunk(2)
        )
        self.assertEqual(batches, [])

    def test_or_where_and_where_any(self):
        env = self._env()
        self._seed(env)
        via_or = (
            env["test.query.post"]
            .query()
            .where("score", "<", 20)
            .or_where("featured", True)
            .order_by("id")
            .pluck("title")
        )
        self.assertEqual(via_or, ["Low", "High"])

        via_any = (
            env["test.query.post"]
            .query()
            .where_any([("title", "=", "Off"), ("score", ">", 80)])
            .order_by("id")
            .pluck("title")
        )
        self.assertEqual(via_any, ["High", "Off"])

    def test_or_where_with_three_and_conditions(self):
        env = self._env()
        self._seed(env)
        rows = (
            env["test.query.post"]
            .query()
            .where("active", True)
            .where("score", ">", 5)
            .or_where("title", "Off")
            .order_by("id")
            .pluck("title")
        )
        self.assertEqual(sorted(rows), ["High", "Low", "Off"])

    def test_collection_path_any_and_all_quantifier(self):
        env = self._env()
        self._seed(env)
        any_vip = (
            env["test.query.post"]
            .query()
            .where("tag_ids.name", "=", "VIP")
            .pluck("title")
        )
        self.assertEqual(any_vip, ["High"])

        not_all_vip = (
            env["test.query.post"]
            .query()
            .where("tag_ids.name", "!=", "VIP", all=True)
            .order_by("id")
            .pluck("title")
        )
        self.assertEqual(not_all_vip, ["Low", "Off"])

    def test_first_find_count_exists_value(self):
        env = self._env()
        self._seed(env)
        Post = env["test.query.post"]

        first = Post.query().where("title", "High").first()
        self.assertEqual(len(first), 1)
        self.assertEqual(first.title, "High")

        self.assertEqual(len(Post.query().where("title", "Nope").first()), 0)

        found = env.query("test.query.post").find(first.id)
        self.assertEqual(found.title, "High")

        with self.assertRaises(RecordNotFound):
            env.query("test.query.post").find_or_fail(99999)

        self.assertEqual(
            env.query("test.query.post").find_or_fail(first.id).title,
            "High",
        )

        self.assertEqual(Post.query().where("active", True).count(), 2)
        self.assertTrue(Post.query().where("featured", True).exists())
        self.assertFalse(Post.query().where("title", "Nope").exists())
        self.assertEqual(
            Post.query().where("title", "High").value("score"),
            90,
        )
        self.assertIsNone(Post.query().where("title", "Nope").value("score"))

    def test_paginate_and_chunk(self):
        env = self._env()
        self._seed(env)
        base = env["test.query.post"].query().order_by("id")

        page1 = base.paginate(page=1, per_page=2)
        self.assertEqual(page1.total, 3)
        self.assertEqual(len(page1.items), 2)
        self.assertEqual(page1.last_page, 2)
        self.assertTrue(page1.has_more)

        page2 = base.paginate(page=2, per_page=2)
        self.assertEqual(len(page2.items), 1)
        self.assertFalse(page2.has_more)

        chunks = list(base.chunk(2))
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 2)
        self.assertEqual(len(chunks[1]), 1)

    def test_query_immutable_after_first_and_paginate(self):
        env = self._env()
        self._seed(env)
        q = env["test.query.post"].query().where("active", True).order_by("id")
        q.first()
        self.assertEqual(q.pluck("title"), ["Low", "High"])
        q.paginate(page=1, per_page=1)
        self.assertEqual(q.count(), 2)

    def test_limit_offset_and_empty_domain(self):
        env = self._env()
        self._seed(env)
        self.assertEqual(
            env["test.query.post"].query().limit(0).count(),
            3,
        )
        page = (
            env["test.query.post"]
            .query()
            .order_by("id")
            .offset(1)
            .limit(1)
            .pluck("title")
        )
        self.assertEqual(page, ["High"])

    def test_domain_property_matches_search(self):
        env = self._env()
        self._seed(env)
        q = (
            env["test.query.post"]
            .query()
            .where("score", ">", 40)
            .where("active", True)
        )
        built = q.domain
        self.assertEqual(
            normalize_domain(built),
            normalize_domain([("score", ">", 40), ("active", "=", True)]),
        )

    def test_search_equivalence(self):
        env = self._env()
        self._seed(env)
        domain = [("score", ">", 40), ("active", "=", True)]
        via_search = env["test.query.post"].search(domain, order='"score" DESC')
        via_query = (
            env["test.query.post"]
            .query()
            .where("score", ">", 40)
            .where("active", True)
            .order_by("score", "desc")
            .get()
        )
        self.assertEqual(via_search._ids, via_query._ids)

    def test_like_and_limit_on_get(self):
        env = self._env()
        self._seed(env)
        rows = (
            env["test.query.post"]
            .query()
            .where("title", "like", "%igh%")
            .order_by("title")
            .limit(1)
            .get()
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.title, "High")


if __name__ == "__main__":
    unittest.main()
