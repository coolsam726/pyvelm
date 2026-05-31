"""Tests for stateless session cookies on serverless hosts."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from pyvelm import BaseModel, Char, Environment, Registry
from pyvelm.session_auth import (
    establish_session,
    mint_session_cookie,
    resolve_session_uid,
    revoke_session,
    uses_stateless_sessions,
    verify_session_cookie,
)


def _vercel_env(**extra: str):
    env = {"VERCEL": "1", "PYVELM_SECRET_KEY": "test-secret", **extra}
    return mock.patch.dict(os.environ, env, clear=False)


class SessionAuthTests(unittest.TestCase):
    def setUp(self):
        uses_stateless_sessions.cache_clear()

    def tearDown(self):
        uses_stateless_sessions.cache_clear()
    def test_stateless_roundtrip(self):
        with _vercel_env():
            token = mint_session_cookie(42)
            self.assertEqual(verify_session_cookie(token), 42)

    def test_tampered_cookie_rejected(self):
        with _vercel_env():
            token = mint_session_cookie(1)
            bad = token[:-4] + "xxxx"
            self.assertIsNone(verify_session_cookie(bad))

    def test_expired_cookie_rejected(self):
        with _vercel_env():
            token = mint_session_cookie(1, now=0)
            self.assertIsNone(verify_session_cookie(token, now=10_000_000))

    def test_explicit_env_flag_without_vercel(self):
        with mock.patch.dict(
            os.environ,
            {"PYVELM_STATELESS_SESSIONS": "1", "PYVELM_SECRET_KEY": "k"},
            clear=False,
        ):
            uses_stateless_sessions.cache_clear()
            self.assertTrue(uses_stateless_sessions())
            token = mint_session_cookie(3)
            self.assertEqual(verify_session_cookie(token), 3)

    def test_postgres_on_serverless_uses_db_sessions(self):
        with mock.patch.dict(
            os.environ,
            {
                "VERCEL": "1",
                "PYVELM_DSN": "postgresql://u:p@db.example.com:5432/demo",
            },
            clear=False,
        ):
            uses_stateless_sessions.cache_clear()
            self.assertFalse(uses_stateless_sessions())

    def test_establish_session_skips_db_on_serverless(self):
        reg = Registry()
        with reg.activate():

            class Users(BaseModel):
                _name = "res.users"
                name = Char()
                login = Char()

            reg.register(Users)
        conn = mock.Mock()
        conn.execute = mock.Mock()
        env = Environment(conn, reg, uid=1)
        env.transaction = mock.Mock(return_value=mock.MagicMock(
            __enter__=mock.Mock(return_value=None),
            __exit__=mock.Mock(return_value=None),
        ))
        env.sudo = mock.Mock(return_value=env)
        env.__getitem__ = mock.Mock()

        with _vercel_env():
            token = establish_session(env, 7)
            self.assertTrue(token.startswith("v1."))
            env.__getitem__.assert_not_called()

    def test_resolve_session_uid_db_mode(self):
        self.assertFalse(uses_stateless_sessions())
        reg = Registry()
        with reg.activate():

            class Users(BaseModel):
                _name = "res.users"

        conn = mock.Mock()
        env = Environment(conn, reg, uid=None)
        rs = mock.Mock()
        rs.__bool__ = mock.Mock(return_value=True)
        rs.ensure_one = mock.Mock()
        rs.id = 5
        model = mock.Mock()
        model.search = mock.Mock(return_value=rs)
        sudo_env = mock.Mock()
        sudo_env.__getitem__ = mock.Mock(return_value=model)
        env.sudo = mock.Mock(return_value=sudo_env)

        uid = resolve_session_uid(env, "db-token-abc")
        self.assertEqual(uid, 5)
        model.search.assert_called_once_with(
            [("session_token", "=", "db-token-abc"), ("active", "=", True)],
            limit=1,
        )

    def test_resolve_session_uid_stateless_verifies_user(self):
        reg = Registry()
        with reg.activate():

            class Users(BaseModel):
                _name = "res.users"
                name = Char()
                active = Char(default="True")

        conn = mock.Mock()
        env = Environment(conn, reg, uid=None)
        rs = mock.Mock()
        rs.__bool__ = mock.Mock(return_value=True)
        rs.ensure_one = mock.Mock()
        rs.id = 1
        model = mock.Mock()
        model.search = mock.Mock(return_value=rs)
        sudo_env = mock.Mock()
        sudo_env.__getitem__ = mock.Mock(return_value=model)
        env.sudo = mock.Mock(return_value=sudo_env)

        with _vercel_env():
            token = mint_session_cookie(1)
            uid = resolve_session_uid(env, token)
        self.assertEqual(uid, 1)
        model.search.assert_called_once_with(
            [("id", "=", 1), ("active", "=", True)], limit=1
        )

    def test_revoke_session_noop_on_serverless(self):
        reg = Registry()
        conn = mock.Mock()
        env = Environment(conn, reg, uid=None)
        with mock.patch.dict(os.environ, {"VERCEL": "1"}, clear=False):
            revoke_session(env, "anything")
        conn.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
