"""Unit tests for ``pyvelm.mail_tracking`` (no database)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pyvelm import BaseModel, Char, Environment, Many2many, Many2one, Registry
from pyvelm import mail_tracking
from pyvelm.fields import Boolean, Field


def _mail_registry():
    reg = Registry()
    with reg.activate():
        from pyvelm.mail import MailThread
        from pyvelm.tests._mail import register_mail_message

        register_mail_message(reg)

        class Tag(BaseModel):
            _name = "test.track.tag"
            name = Char()

        class Doc(MailThread, BaseModel):
            _name = "test.track.doc"
            name = Char(tracking=True)
            partner_id = Many2one("test.track.partner", tracking=True)
            tag_ids = Many2many("test.track.tag", tracking=True)

        class Partner(BaseModel):
            _name = "test.track.partner"
            name = Char()

    return reg, Doc, Partner, Tag


class ModelHasMailThreadTests(unittest.TestCase):
    def test_plain_model(self):
        reg = Registry()
        with reg.activate():

            class Plain(BaseModel):
                _name = "plain"

        self.assertFalse(mail_tracking.model_has_mail_thread(Plain))

    def test_mail_thread_subclass(self):
        _reg, Doc, *_ = _mail_registry()
        self.assertTrue(mail_tracking.model_has_mail_thread(Doc))


class TrackedFieldNamesTests(unittest.TestCase):
    def test_skips_private_and_related(self):
        reg = Registry()
        with reg.activate():

            class Item(BaseModel):
                _name = "test.track.skip"
                name = Char(tracking=True)
                secret = Char(tracking=True)
                ref = Char(tracking=True)

            Item._fields["secret"].private = True
            Item._fields["ref"].related = "name"

        names = mail_tracking.tracked_field_names(Item, ["name", "secret", "ref"])
        self.assertEqual(names, ["name"])


class NormalizeAndCompareTests(unittest.TestCase):
    def test_many2one_ids(self):
        reg, Doc, Partner, _Tag = _mail_registry()
        env = Environment(None, reg, uid=1)
        field = Doc._fields["partner_id"]
        rec = Partner(env, (5,))
        self.assertEqual(mail_tracking._normalize_scalar(field, rec), 5)
        self.assertEqual(mail_tracking._normalize_scalar(field, None), None)

    def test_normalize_many2one_empty_ids(self):
        reg, Doc, Partner, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        field = Doc._fields["partner_id"]
        self.assertIsNone(
            mail_tracking._normalize_scalar(field, Partner(env, ()))
        )

    def test_normalize_boolean_and_scalar(self):
        reg = Registry()
        with reg.activate():

            class Item(BaseModel):
                _name = "test.track.bool"
                active = Boolean(tracking=True)
                qty = Char(tracking=True)

        self.assertIsNone(mail_tracking._normalize_scalar(Item._fields["active"], False))
        self.assertTrue(mail_tracking._normalize_scalar(Item._fields["active"], True))
        self.assertEqual(
            mail_tracking._normalize_scalar(Item._fields["qty"], ""), None
        )

    def test_many2many_equality(self):
        reg, Doc, _P, _T = _mail_registry()
        field = Doc._fields["tag_ids"]
        self.assertTrue(mail_tracking._values_equal(field, (1, 2), (2, 1)))
        self.assertFalse(mail_tracking._values_equal(field, (1,), (2,)))


class FormatFieldValueTests(unittest.TestCase):
    def test_many2one_and_many2many(self):
        reg, Doc, Partner, Tag = _mail_registry()
        env = Environment(None, reg, uid=1)
        env.cache.set("test.track.partner", 1, "id", 1)
        env.cache.set("test.track.partner", 1, "name", "Acme")
        env.cache.set("test.track.tag", 2, "id", 2)
        env.cache.set("test.track.tag", 2, "name", "VIP")

        m2o = Doc._fields["partner_id"]
        self.assertEqual(mail_tracking.format_field_value(env, m2o, 1), "Acme")
        self.assertEqual(mail_tracking.format_field_value(env, m2o, None), "(empty)")

        m2m = Doc._fields["tag_ids"]
        self.assertEqual(mail_tracking.format_field_value(env, m2m, (2,)), "VIP")
        self.assertEqual(mail_tracking.format_field_value(env, m2m, ()), "(empty)")

    def test_choices_label(self):
        reg = Registry()

        class Choice(Field):
            sql_type = "text"
            choices = (("a", "Alpha"), ("b", "Beta"))

        with reg.activate():

            class Item(BaseModel):
                _name = "test.track.choice"
                state = Choice(tracking=True)

        env = Environment(None, reg, uid=1)
        field = Item._fields["state"]
        self.assertEqual(mail_tracking.format_field_value(env, field, "a"), "Alpha")

    def test_format_m2o_none(self):
        reg, Doc, _Partner, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        field = Doc._fields["partner_id"]
        self.assertEqual(mail_tracking.format_field_value(env, field, None), "(empty)")

    def test_format_m2o_uses_display_name_or_raw_id(self):
        reg, Doc, Partner, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        env.cache.set("test.track.partner", 4, "id", 4)
        env.cache.set("test.track.partner", 4, "name", "Named")
        field = Doc._fields["partner_id"]
        self.assertEqual(mail_tracking.format_field_value(env, field, 4), "Named")
        env.cache.set("test.track.partner", 5, "id", 5)
        self.assertEqual(mail_tracking.format_field_value(env, field, 5), "5")

    def test_format_m2m_multiple_and_name_only(self):
        reg, Doc, _P, Tag = _mail_registry()
        env = Environment(None, reg, uid=1)
        env.cache.set("test.track.tag", 1, "id", 1)
        env.cache.set("test.track.tag", 1, "name", "A")
        env.cache.set("test.track.tag", 2, "id", 2)
        field = Doc._fields["tag_ids"]
        self.assertEqual(
            mail_tracking.format_field_value(env, field, (1, 2)), "A, 2"
        )

    def test_format_scalar_false_is_empty(self):
        reg = Registry()
        with reg.activate():

            class Item(BaseModel):
                _name = "test.track.empty"
                note = Char(tracking=True)

        env = Environment(None, reg, uid=1)
        self.assertEqual(
            mail_tracking.format_field_value(env, Item._fields["note"], False),
            "(empty)",
        )

    def test_tracked_field_names_ignores_unknown(self):
        reg, Doc, _P, _T = _mail_registry()
        names = mail_tracking.tracked_field_names(Doc, ["missing", "name"])
        self.assertEqual(names, ["name"])


class SnapshotTests(unittest.TestCase):
    def test_field_label_fallback(self):
        reg, Doc, _P, _T = _mail_registry()
        field = Doc._fields["partner_id"]
        field.string = None
        self.assertEqual(mail_tracking._field_label(field, "partner_id"), "Partner Id")

    def test_snapshot_before_write_columns(self):
        reg, Doc, _P, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        env.cache.set("test.track.doc", 1, "id", 1)
        env.cache.set("test.track.doc", 1, "name", "Before")
        rec = Doc(env, (1,))
        snap = mail_tracking.snapshot_before_write(rec, ["name"], [])
        self.assertEqual(snap[1]["name"], "Before")

    def test_snapshot_before_write_missing_cache_key(self):
        reg, Doc, _P, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        rec = Doc(env, (2,))
        with patch.object(rec, "_read"):
            snap = mail_tracking.snapshot_before_write(rec, ["name"], [])
        self.assertIsNone(snap[2]["name"])

    def test_snapshot_before_write_includes_m2m(self):
        reg, Doc, _P, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        rec = Doc(env, (1,))
        with patch.object(
            mail_tracking,
            "snapshot_m2m_per_record",
            return_value={1: frozenset({2})},
        ):
            snap = mail_tracking.snapshot_before_write(rec, [], ["tag_ids"])
        self.assertEqual(snap[1]["tag_ids"], frozenset({2}))

    def test_current_column_values_reads_missing(self):
        reg, Doc, _P, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        env.cache.set("test.track.doc", 1, "id", 1)
        rec = Doc(env, (1,))

        def _read(fields):
            env.cache.set("test.track.doc", 1, "name", "Loaded")

        with patch.object(Doc, "browse", return_value=MagicMock(_read=_read)):
            out = mail_tracking._current_column_values(rec, "name")
        self.assertEqual(out[1], "Loaded")

    def test_snapshot_m2m_via_conn(self):
        reg, Doc, _P, Tag = _mail_registry()
        env = MagicMock(registry=reg._models)
        env.conn.execute.return_value.fetchall.return_value = [(2,), (3,)]
        rec = Doc(env, (1,))
        out = mail_tracking.snapshot_m2m_per_record(rec, "tag_ids")
        self.assertEqual(out[1], frozenset({2, 3}))

    def test_snapshot_m2m_non_m2m_field(self):
        reg, Doc, _P, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        rec = Doc(env, (1,))
        self.assertEqual(
            mail_tracking.snapshot_m2m_per_record(rec, "name"), {}
        )


class PostWriteTrackingTests(unittest.TestCase):
    def test_skips_when_flag_set(self):
        reg, Doc, _P, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        env._mail_tracking_skip = True
        rec = Doc(env, (1,))
        with patch.object(rec, "message_post") as post:
            mail_tracking.post_write_tracking(rec, {"name": "x"}, {}, {1: {}})
        post.assert_not_called()

    def test_posts_tracking_lines(self):
        reg, Doc, _P, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        env.cache.set("test.track.doc", 1, "id", 1)
        env.cache.set("test.track.doc", 1, "name", "After")
        rec = Doc(env, (1,))
        before = {1: {"name": "Before"}}
        with patch.object(Doc, "message_post") as post:
            mail_tracking.post_write_tracking(
                rec, {"name": "After"}, {}, before
            )
        post.assert_called_once()
        body = post.call_args[0][0]
        self.assertIn("Name", body)
        self.assertIn("→", body)
        self.assertEqual(post.call_args[1]["subtype"], "mail_tracking")

    def test_m2m_unchanged_skips_line(self):
        reg, Doc, _P, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        env.cache.set("test.track.doc", 1, "id", 1)
        rec = Doc(env, (1,))
        tags = frozenset({1})
        before = {1: {"tag_ids": tags}}
        with (
            patch.object(
                mail_tracking,
                "snapshot_m2m_per_record",
                return_value={1: tags},
            ),
            patch.object(Doc, "message_post") as post,
        ):
            mail_tracking.post_write_tracking(rec, {}, {"tag_ids": [1]}, before)
        post.assert_not_called()

    def test_no_post_when_unchanged(self):
        reg, Doc, _P, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        env.cache.set("test.track.doc", 1, "id", 1)
        env.cache.set("test.track.doc", 1, "name", "Same")
        rec = Doc(env, (1,))
        before = {1: {"name": "Same"}}
        with patch.object(rec, "message_post") as post:
            mail_tracking.post_write_tracking(
                rec, {"name": "Same"}, {}, before
            )
        post.assert_not_called()

    def test_posts_m2m_tracking(self):
        reg, Doc, _P, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        env.cache.set("test.track.doc", 1, "id", 1)
        rec = Doc(env, (1,))
        before = {1: {"tag_ids": frozenset()}}
        with (
            patch.object(
                mail_tracking,
                "snapshot_m2m_per_record",
                return_value={1: frozenset({5})},
            ),
            patch.object(Doc, "message_post") as post,
        ):
            mail_tracking.post_write_tracking(
                rec, {}, {"tag_ids": [5]}, before
            )
        post.assert_called_once()

    def test_skips_non_mail_thread_model(self):
        reg = Registry()
        with reg.activate():

            class Plain(BaseModel):
                _name = "test.track.plain"
                name = Char(tracking=True)

        env = Environment(None, reg, uid=1)
        env.cache.set("test.track.plain", 1, "id", 1)
        rec = Plain(env, (1,))
        mail_tracking.post_write_tracking(
            rec, {"name": "X"}, {}, {1: {"name": "Y"}}
        )

    def test_skips_when_no_tracked_fields_in_vals(self):
        reg, Doc, _P, _T = _mail_registry()
        env = Environment(None, reg, uid=1)
        env.cache.set("test.track.doc", 1, "id", 1)
        rec = Doc(env, (1,))
        with patch.object(Doc, "message_post") as post:
            mail_tracking.post_write_tracking(rec, {"note": "x"}, {}, {1: {}})
        post.assert_not_called()

    def test_skips_without_mail_message_model(self):
        reg = Registry()
        with reg.activate():
            from pyvelm.mail import MailThread

            class Doc(MailThread, BaseModel):
                _name = "test.track.nomsg"
                name = Char(tracking=True)

        env = Environment(None, reg, uid=1)
        env.cache.set("test.track.nomsg", 1, "id", 1)
        rec = Doc(env, (1,))
        with patch.object(rec, "message_post") as post:
            mail_tracking.post_write_tracking(
                rec, {"name": "X"}, {}, {1: {"name": "Y"}}
            )
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
