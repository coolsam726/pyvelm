"""Unit tests for ``pyvelm.mail_template`` (no database)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Registry
from pyvelm.env import Environment
from pyvelm.tests._mail import register_mail_template


def _registry():
    reg = Registry()
    with reg.activate():
        from pyvelm.mail import MailThread
        from pyvelm.mail_template import MailTemplate

        register_mail_template(reg)

        class Partner(MailThread, BaseModel):
            _name = "test.tpl.partner"
            name = Char()

    return reg, Partner, MailTemplate


class MailTemplateModelTests(unittest.TestCase):
    def test_compute_display_name(self):
        _reg, _Partner, MailTemplate = _registry()

        class _Row:
            def __init__(self, name: str, id: int):
                self.name = name
                self.id = id
                self.display_name = ""

        r1, r2 = _Row("Welcome", 3), _Row("", 5)
        MailTemplate._compute_display_name([r1, r2])
        self.assertEqual(r1.display_name, "Welcome")
        self.assertEqual(r2.display_name, "mail.template #5")

    def test_render_for_record_model_mismatch(self):
        reg, Partner, MailTemplate = _registry()
        env = Environment(None, reg, uid=1)
        tpl = MagicMock(model="other.model", name="T")
        tpl.ensure_one = lambda: None
        tpl.env = env
        rec = Partner(env, (1,))
        with reg.activate():
            with self.assertRaises(ValueError):
                MailTemplate._render_for_record(tpl, rec)

    def test_render_for_record_success(self):
        reg, Partner, MailTemplate = _registry()
        env = Environment(None, reg, uid=1)
        env.cache.set("test.tpl.partner", 1, "id", 1)
        env.cache.set("test.tpl.partner", 1, "name", "Acme")
        tpl = MagicMock(
            model="test.tpl.partner",
            name="T",
            subject="Hi {{ object.name }}",
            body_html="<p>{{ object.name }}</p>",
        )
        tpl.ensure_one = lambda: None
        tpl.env = env
        rec = Partner(env, (1,))
        with reg.activate():
            subject, body = MailTemplate._render_for_record(tpl, rec)
        self.assertIn("Acme", subject)
        self.assertIn("Acme", body)

    def test_render_preview_unknown_model(self):
        _reg, _Partner, MailTemplate = _registry()
        tpl = MagicMock(model="missing.model")
        tpl.ensure_one = lambda: None
        tpl.env = MagicMock(registry={})
        with self.assertRaises(ValueError):
            MailTemplate.render_preview(tpl)

    def test_render_preview_no_record_uses_empty(self):
        reg, Partner, MailTemplate = _registry()
        env = MagicMock(registry=reg._models)
        Model = MagicMock()
        Model.search.return_value = Partner(env, ())
        env.__getitem__ = MagicMock(return_value=Model)
        tpl = MagicMock(model="test.tpl.partner")
        tpl.ensure_one = lambda: None
        tpl.env = env
        tpl._render_for_record = MagicMock(return_value=("S", "B"))
        with reg.activate():
            out = MailTemplate.render_preview(tpl, res_id=None)
        self.assertEqual(out, {"subject": "S", "body_html": "B"})

    def test_render_preview_missing_res_id_raises(self):
        reg, Partner, MailTemplate = _registry()
        env = MagicMock(registry=reg._models)
        Model = MagicMock()
        Model.browse.return_value = Partner(env, ())
        env.__getitem__ = MagicMock(return_value=Model)
        tpl = MagicMock(model="test.tpl.partner")
        tpl.ensure_one = lambda: None
        tpl.env = env
        with reg.activate(), self.assertRaises(ValueError):
            MailTemplate.render_preview(tpl, res_id=999)

    def test_send_mail_inactive(self):
        _reg, _Partner, MailTemplate = _registry()
        tpl = MagicMock(active=False, name="T")
        tpl.ensure_one = lambda: None
        with self.assertRaises(ValueError):
            MailTemplate.send_mail(tpl, MagicMock(), to="a@b.c")

    def test_send_mail_requires_recipient(self):
        _reg, _Partner, MailTemplate = _registry()
        tpl = MagicMock(active=True, name="T")
        tpl.ensure_one = lambda: None
        rec = MagicMock()
        rec.ensure_one = lambda: None
        with self.assertRaises(ValueError):
            MailTemplate.send_mail(tpl, rec, to="  ")

    def test_send_mail_requires_mail_thread(self):
        _reg, _Partner, MailTemplate = _registry()
        tpl = MagicMock(active=True, name="T", id=1)
        tpl.ensure_one = lambda: None
        tpl._render_for_record = MagicMock(return_value=("S", "<p>B</p>"))
        rec = type("Plain", (), {"ensure_one": lambda self: None, "_name": "plain"})()
        with self.assertRaises(TypeError):
            MailTemplate.send_mail(tpl, rec, to="a@b.c")

    def test_send_mail_delegates(self):
        _reg, _Partner, MailTemplate = _registry()
        tpl = MagicMock(active=True, name="T", id=2)
        tpl.ensure_one = lambda: None
        tpl._render_for_record = MagicMock(return_value=("Subj", "<p>Body</p>"))
        rec = MagicMock(_name="x")
        rec.ensure_one = lambda: None
        rec._send_rendered_mail = MagicMock(return_value=MagicMock(id=9))
        out = MailTemplate.send_mail(
            tpl, rec, to="a@b.c", cc="c@b.c", bcc="b@b.c", reply_to="r@b.c"
        )
        rec._send_rendered_mail.assert_called_once()
        self.assertEqual(out.id, 9)


if __name__ == "__main__":
    unittest.main()
