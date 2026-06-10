"""Tests for :mod:`pyvelm.query` (Eloquent-style query builder)."""
from __future__ import annotations

import unittest

from pyvelm import (
    BaseModel,
    Boolean,
    Char,
    Environment,
    Integer,
    Query,
    RecordNotFound,
    Registry,
    models,
)
from pyvelm.database import create_database_from_dsn


class QueryBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = Registry()
        with cls.reg.activate():

            class Post(BaseModel):
                _name = "test.query.post"
                _table = "test_query_post"
                title = Char()
                score = Integer()
                active = Boolean(default=True)

        with cls.reg.activate():

            class PostExt(models.Model):
                _inherit = "test.query.post"
                featured = Boolean(default=False)

        cls.db = create_database_from_dsn("sqlite:///:memory:", pool_size=1)
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

    def _seed(self, env: Environment):
        self._clear(env)
        with self.reg.activate():
            Post = env["test.query.post"]
            Post.create({"title": "Low", "score": 10, "active": True})
            Post.create(
                {"title": "High", "score": 90, "active": True, "featured": True}
            )
            Post.create({"title": "Off", "score": 50, "active": False})

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
        titles = [r.title for r in rows]
        self.assertEqual(titles, ["High", "Off"])

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

    def test_first_find_count_exists(self):
        env = self._env()
        self._seed(env)
        first = env["test.query.post"].query().where("title", "High").first()
        self.assertEqual(len(first), 1)
        self.assertEqual(first.title, "High")

        missing = env["test.query.post"].query().where("title", "Nope").first()
        self.assertEqual(len(missing), 0)

        found = env.query("test.query.post").find(first.id)
        self.assertEqual(found.title, "High")

        with self.assertRaises(RecordNotFound):
            env.query("test.query.post").find_or_fail(99999)

        self.assertEqual(
            env["test.query.post"].query().where("active", True).count(),
            2,
        )
        self.assertTrue(env["test.query.post"].query().where("featured", True).exists())
        self.assertFalse(env["test.query.post"].query().where("title", "Nope").exists())

    def test_paginate_and_chunk(self):
        env = self._env()
        self._seed(env)
        page = env["test.query.post"].query().order_by("id").paginate(page=1, per_page=2)
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.items), 2)
        self.assertEqual(page.last_page, 2)
        self.assertTrue(page.has_more)

        chunks = list(
            env["test.query.post"].query().order_by("id").chunk(2)
        )
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 2)
        self.assertEqual(len(chunks[1]), 1)

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


if __name__ == "__main__":
    unittest.main()
