"""Unit tests for ``pyvelm.mail_compose`` (no database)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Many2one, Registry
from pyvelm.env import Cache
from pyvelm.tests._mail import register_mail_message, register_mail_template


class _Env:
    def __init__(self, registry, models: dict | None = None, *, uid=1, company_id=None):
        self.registry = registry._models if hasattr(registry, "_models") else registry
        self.uid = uid
        self.company_id = company_id
        self.cache = Cache()
        self._models = models or {}

    def check_access(self, *_a, **_k):
        return None

    def __getitem__(self, name: str):
        if name in self._models:
            model = self._models[name]
            if isinstance(model, type):
                return model(self, ())
            return model
        if name in self.registry:
            return self.registry[name](self, ())
        raise KeyError(name)


def _partner_registry():
    reg = Registry()
    with reg.activate():
        from pyvelm.mail import MailThread
        from pyvelm.mail_compose import MailCompose, _resolve_default_to

        register_mail_message(reg)
        register_mail_template(reg)

        class User(BaseModel):
            _name = "res.users"
            login = Char()

        class Partner(MailThread, BaseModel):
            _name = "test.compose.unit"
            name = Char()
            email = Char()
            partner_id = Many2one("test.compose.unit")

        reg.register(User)
    return reg, Partner, MailCompose, _resolve_default_to


def _mock_compose_env(reg, Partner, *, created=None, target_model: str | None = None):
    created = created or []
    target_model = target_model or getattr(Partner, "_name", "test.compose.unit")

    def _create(vals):
        c = MagicMock()
        c.id = len(created) + 1
        for k, v in vals.items():
            setattr(c, k, v)
        created.append(c)
        return c

    compose_model = MagicMock()
    compose_model.create.side_effect = _create

    msg_model = MagicMock()
    msg_created = []

    def _msg_create(vals):
        m = MagicMock()
        m.id = len(msg_created) + 1
        for k, v in vals.items():
            setattr(m, k, v)
        msg_created.append(m)
        return m

    msg_model.create.side_effect = _msg_create

    tpl_model = MagicMock()
    att_model = MagicMock()

    env = _Env(
        reg,
        {
            "mail.compose.message": compose_model,
            "mail.message": msg_model,
            "mail.template": tpl_model,
            "ir.attachment": att_model,
            "res.users": MagicMock(),
            target_model: reg[target_model],
        },
        uid=1,
    )
    return env, compose_model, msg_model, tpl_model, created, msg_created


class ResolveDefaultToTests(unittest.TestCase):
    def test_direct_email_field(self):
        reg, Partner, _Mc, resolve = _partner_registry()
        env = _Env(reg, {})
        env.cache.set("test.compose.unit", 1, "id", 1)
        env.cache.set("test.compose.unit", 1, "email", "a@b.c")
        rec = Partner(env, (1,))
        self.assertEqual(resolve(rec), "a@b.c")

    def test_many2one_email_path(self):
        reg, Partner, _Mc, resolve = _partner_registry()
        env = _Env(reg, {})
        env.cache.set("test.compose.unit", 1, "id", 1)
        env.cache.set("test.compose.unit", 2, "id", 2)
        env.cache.set("test.compose.unit", 2, "email", "via@b.c")
        env.cache.set("test.compose.unit", 1, "partner_id", 2)
        rec = Partner(env, (1,))
        self.assertEqual(resolve(rec), "via@b.c")

    def test_empty_when_no_email(self):
        reg, Partner, _Mc, resolve = _partner_registry()
        env = _Env(reg, {})
        env.cache.set("test.compose.unit", 1, "id", 1)
        rec = Partner(env, (1,))
        self.assertEqual(resolve(rec), "")


class MailComposeLaunchTests(unittest.TestCase):
    def test_launch_minimal_draft(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        env, *_ = _mock_compose_env(reg, Partner)
        draft = MagicMock(state="draft")
        with reg.activate(), patch.object(MailCompose, "create", return_value=draft) as create:
            out = MailCompose.launch(env)
        create.assert_called_once()
        self.assertEqual(create.call_args[0][0]["state"], "draft")
        self.assertIs(out, draft)

    def test_launch_autofills_to_and_template(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        env = _Env(
            reg,
            {
                "mail.compose.message": MagicMock(),
                "mail.template": MagicMock(),
                "test.compose.unit": reg["test.compose.unit"],
            },
            uid=1,
        )
        env.cache.set("test.compose.unit", 5, "id", 5)
        env.cache.set("test.compose.unit", 5, "email", "to@test")
        tpl = MagicMock()
        tpl._ids = (9,)
        tpl.id = 9
        tpl.subject = "Hi"
        tpl.body_html = "<p>x</p>"
        tpl._render_for_record.return_value = ("Hello", "<p>Hi</p>")
        tpl_model = MagicMock()
        tpl_model.browse.return_value = tpl
        compose_created = []

        def _create(vals):
            c = MagicMock(id=1, **vals)
            compose_created.append(c)
            return c

        compose_model = MagicMock()
        compose_model.create.side_effect = _create
        env._models.update({
            "mail.compose.message": compose_model,
            "mail.template": tpl_model,
        })
        created = MagicMock()
        with reg.activate(), patch.object(MailCompose, "create", return_value=created) as m_create:
            MailCompose.launch(
                env, model="test.compose.unit", res_id=5, template_id=9
            )
        vals = m_create.call_args[0][0]
        self.assertEqual(vals["recipient_to"], "to@test")
        self.assertEqual(vals["subject"], "Hello")

    def test_launch_template_render_failure_uses_static(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        env = _Env(
            reg,
            {
                "mail.compose.message": MagicMock(),
                "mail.template": MagicMock(),
                "test.compose.unit": reg["test.compose.unit"],
            },
            uid=1,
        )
        env.cache.set("test.compose.unit", 1, "id", 1)
        tpl = MagicMock(_ids=(1,), id=1, subject="S", body_html="B")
        tpl._render_for_record.side_effect = RuntimeError("nope")
        tpl_model = MagicMock(browse=MagicMock(return_value=tpl))
        compose_model = MagicMock(create=MagicMock(return_value=MagicMock()))
        env._models.update({
            "mail.compose.message": compose_model,
            "mail.template": tpl_model,
        })
        with reg.activate(), patch.object(MailCompose, "create", return_value=MagicMock()) as m_create:
            MailCompose.launch(env, model="test.compose.unit", res_id=1, template_id=1)
        vals = m_create.call_args[0][0]
        self.assertEqual(vals["subject"], "S")


class MailComposeActionTests(unittest.TestCase):
    def _composer(self, reg, Partner, env, **attrs):
        c = MagicMock()
        c.id = 99
        c.env = env
        c.model = attrs.get("model", "test.compose.unit")
        c.res_id = attrs.get("res_id", 1)
        c.recipient_to = attrs.get("recipient_to", "to@test")
        c.recipient_cc = attrs.get("recipient_cc", None)
        c.recipient_bcc = attrs.get("recipient_bcc", None)
        c.reply_to = attrs.get("reply_to", None)
        c.subject = attrs.get("subject", "Subj")
        c.body_html = attrs.get("body_html", "<p>Hi</p>")
        c.template_id = attrs.get("template_id", MagicMock(_ids=()))
        c.attachment_ids = attrs.get("attachment_ids", MagicMock(_ids=()))
        c.state = "draft"
        c.error = None
        c.write = MagicMock()
        c.ensure_one = lambda: None
        return c

    def test_apply_template_without_record(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        env, *_ = _mock_compose_env(reg, Partner)
        tpl = MagicMock(subject="T", body_html="<b>")
        c = self._composer(reg, Partner, env, model=None, res_id=None)
        c.template_id = tpl
        with reg.activate():
            out = MailCompose.action_apply_template(c)
        c.write.assert_called_once_with({"subject": "T", "body_html": "<b>"})
        self.assertIs(out, c)

    def test_apply_template_no_template_is_noop(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        env, *_ = _mock_compose_env(reg, Partner)
        c = self._composer(reg, Partner, env)
        c.template_id = None
        with reg.activate():
            self.assertIs(MailCompose.action_apply_template(c), c)
        c.write.assert_not_called()

    def test_apply_template_renders_for_record(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        env = _Env(reg, {"test.compose.unit": reg["test.compose.unit"]}, uid=1)
        env.cache.set("test.compose.unit", 1, "id", 1)
        tpl = MagicMock(_render_for_record=MagicMock(return_value=("S", "<p>B</p>")))
        c = self._composer(reg, Partner, env)
        c.template_id = tpl
        with reg.activate():
            MailCompose.action_apply_template(c)
        c.write.assert_called_with({"subject": "S", "body_html": "<p>B</p>"})

    def test_apply_template_missing_record_uses_static(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        env = _Env(reg, {"test.compose.unit": reg["test.compose.unit"]}, uid=1)
        tpl = MagicMock(subject="T", body_html="<b>")
        c = self._composer(reg, Partner, env, res_id=999)
        c.template_id = tpl
        with reg.activate(), patch.object(
            Partner, "browse", return_value=Partner(env, ())
        ):
            MailCompose.action_apply_template(c)
        c.write.assert_called_with({"subject": "T", "body_html": "<b>"})

    def test_send_requires_to(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        env, *_ = _mock_compose_env(reg, Partner)
        c = self._composer(reg, Partner, env, recipient_to="  ")
        with reg.activate():
            with self.assertRaises(ValueError):
                MailCompose.action_send(c)

    def test_send_via_mail_thread(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        from pyvelm.env import Environment

        env = Environment(None, reg, uid=1)
        env.cache.set("test.compose.unit", 1, "id", 1)
        with patch.object(Partner, "_send_rendered_mail") as send_mail:
            c = self._composer(reg, Partner, env)
            c.model = "test.compose.unit"
            c.res_id = 1
            c.env = env
            with reg.activate():
                MailCompose.action_send(c)
        send_mail.assert_called_once()
        c.write.assert_called_with({"state": "sent", "error": None})

    def test_send_fallback_creates_message(self):
        reg = Registry()
        with reg.activate():
            from pyvelm.mail_compose import MailCompose

            register_mail_message(reg)

            class Plain(BaseModel):
                _name = "plain.model"
                name = Char()

        env, _c, msg_model, *_ = _mock_compose_env(reg, Plain, target_model="plain.model")
        composer = self._composer(reg, Plain, env)
        composer.model = "plain.model"
        composer.res_id = 0
        with reg.activate():
            MailCompose.action_send(composer)
        msg_model.create.assert_called_once()
        composer.write.assert_called_with({"state": "sent", "error": None})

    def test_send_failure_marks_failed(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        from pyvelm.env import Environment

        env = Environment(None, reg, uid=1)
        env.cache.set("test.compose.unit", 1, "id", 1)
        with patch.object(
            Partner, "_send_rendered_mail", side_effect=RuntimeError("smtp")
        ):
            c = self._composer(reg, Partner, env)
            c.model = "test.compose.unit"
            c.res_id = 1
            c.env = env
            with reg.activate():
                with self.assertRaises(RuntimeError):
                    MailCompose.action_send(c)
        c.write.assert_any_call({"state": "failed", "error": "smtp"})

    def test_save_as_template_validation(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        env, *_ = _mock_compose_env(reg, Partner)
        c = self._composer(reg, Partner, env)
        with reg.activate():
            with self.assertRaises(ValueError):
                MailCompose.action_save_as_template(c, name="")
        c.model = None
        with reg.activate():
            with self.assertRaises(ValueError):
                MailCompose.action_save_as_template(c, name="T")

    def test_save_as_template_creates_row(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        env, *_rest = _mock_compose_env(reg, Partner)
        tpl_model = env._models["mail.template"]
        tpl_model.create.return_value = MagicMock(name="Saved")
        c = self._composer(reg, Partner, env)
        c.model = "test.compose.unit"
        saved = MagicMock(name="Saved")
        tpl_model.create.return_value = saved
        with reg.activate():
            out = MailCompose.action_save_as_template(c, name="My tpl")
        tpl_model.create.assert_called_once()
        self.assertIs(out, saved)

    def test_launch_resolve_to_exception(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        env = _Env(
            reg,
            {"test.compose.unit": reg["test.compose.unit"]},
            uid=1,
        )

        class _Broken:
            def browse(self, _id):
                raise RuntimeError("boom")

        env._models["test.compose.unit"] = _Broken()
        with reg.activate(), patch.object(MailCompose, "create", return_value=MagicMock()):
            MailCompose.launch(env, model="test.compose.unit", res_id=1)

    def test_launch_template_without_bound_record(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        tpl = MagicMock(_ids=(1,), subject="S", body_html="B")
        env = _Env(
            reg,
            {"mail.template": MagicMock(browse=MagicMock(return_value=tpl))},
            uid=1,
        )
        with reg.activate(), patch.object(MailCompose, "create", return_value=MagicMock()) as m_create:
            MailCompose.launch(env, template_id=1)
        vals = m_create.call_args[0][0]
        self.assertEqual(vals["subject"], "S")

    def test_send_queues_with_attachments(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        env, _c, msg_model, *_ = _mock_compose_env(reg, Partner)
        att = MagicMock(id=3)
        c = self._composer(reg, Partner, env)
        c.model = "missing.model"
        c.res_id = 0
        c.attachment_ids = [att]
        with reg.activate(), patch("pyvelm.mail._link_attachments") as link:
            MailCompose.action_send(c)
        msg_model.create.assert_called_once()
        link.assert_called_once()

    def test_save_as_template_missing_model_in_registry(self):
        reg, Partner, MailCompose, _ = _partner_registry()
        env = _Env(reg, {}, uid=1)
        c = self._composer(reg, Partner, env)
        c.model = "test.compose.unit"
        reg._models.pop("mail.template", None)
        with reg.activate():
            with self.assertRaises(RuntimeError):
                MailCompose.action_save_as_template(c, name="X")

    def test_resolve_default_to_related_error(self):
        _reg, Partner, _Mc, resolve = _partner_registry()

        class _Stub:
            _fields = {"partner_id": Partner._fields["partner_id"]}

            @property
            def partner_id(self):
                raise RuntimeError("nope")

        self.assertEqual(resolve(_Stub()), "")

    def test_resolve_default_to_empty_related(self):
        _reg, Partner, _Mc, resolve = _partner_registry()

        class _Rel:
            _ids = ()

        class _Stub:
            _fields = {"partner_id": Partner._fields["partner_id"]}
            partner_id = _Rel()

        self.assertEqual(resolve(_Stub()), "")


if __name__ == "__main__":
    unittest.main()
