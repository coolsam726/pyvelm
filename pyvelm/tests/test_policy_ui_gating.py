from __future__ import annotations

import unittest


class _FakeRecord:
    _name = "x.demo"

    def __init__(self, rid: int):
        self._ids = (rid,)


class _FakeEnv:
    def __init__(self, *, access: dict[tuple[str, str], bool], policy: dict[str, bool]):
        self._access = access
        self._policy = policy

    def has_access(self, model: str, perm: str) -> bool:
        return bool(self._access.get((model, perm), False))

    def can(self, _record, action: str, *, _perm: str | None = None, **_kw) -> bool:
        # For this unit test, assume perm gating already happened via has_access.
        return bool(self._policy.get(action, False))

    def __getitem__(self, model_name: str):
        class _Browse:
            def browse(self, rid):
                return _FakeRecord(int(rid))

        return _Browse()


class HeaderActionPolicyGatingTests(unittest.TestCase):
    def test_hides_action_when_policy_denies(self):
        from pyvelm.render import _resolve_header_actions

        env = _FakeEnv(access={("x.demo", "write"): True}, policy={"approve": False})
        actions = [
            {"label": "Approve", "url": "/web/x/{id}/approve", "method": "POST", "perm": "write", "policy": "approve"},
        ]
        out = _resolve_header_actions(
            actions,
            env,
            model="x.demo",
            module="x",
            name="demo.form",
            record_id=7,
            record=_FakeRecord(7),
        )
        self.assertEqual(out, [])

    def test_shows_action_when_policy_allows(self):
        from pyvelm.render import _resolve_header_actions

        env = _FakeEnv(access={("x.demo", "write"): True}, policy={"approve": True})
        actions = [
            {"label": "Approve", "url": "/web/x/{id}/approve", "method": "POST", "perm": "write", "policy": "approve"},
        ]
        out = _resolve_header_actions(
            actions,
            env,
            model="x.demo",
            module="x",
            name="demo.form",
            record_id=7,
            record=_FakeRecord(7),
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["label"], "Approve")
        self.assertIn("/web/x/7/approve", out[0]["url"])

