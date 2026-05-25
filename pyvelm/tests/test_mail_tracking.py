"""Field tracking (tracking=True) on MailThread models."""
from __future__ import annotations

import os
import unittest

from pyvelm import BaseModel, Char, Environment, Many2one, Registry
from pyvelm import mail_tracking

DSN = os.environ.get("PYVELM_DSN")

try:
    import psycopg
except ImportError:
    psycopg = None


class TrackingFieldTests(unittest.TestCase):
    def test_tracking_defaults_false(self):
        reg = Registry()
        with reg.activate():

            class Item(BaseModel):
                _name = "test.track.field"
                name = Char()

        self.assertFalse(Item._fields["name"].tracking)

    def test_tracking_true_on_field(self):
        reg = Registry()
        with reg.activate():

            class Item(BaseModel):
                _name = "test.track.field2"
                name = Char(tracking=True)
                note = Char(tracking=False)

        self.assertTrue(Item._fields["name"].tracking)
        self.assertFalse(Item._fields["note"].tracking)

    def test_tracked_field_names_skips_non_stored_compute(self):
        from pyvelm import depends

        reg = Registry()
        with reg.activate():

            class Item(BaseModel):
                _name = "test.track.compute"
                name = Char(tracking=True)
                label = Char(compute="_compute_label", tracking=True)

                @depends("name")
                def _compute_label(self):
                    for r in self:
                        r.label = r.name or ""

        names = mail_tracking.tracked_field_names(Item, ["label", "name"])
        self.assertEqual(names, ["name"])


class TrackingFormatTests(unittest.TestCase):
    def test_format_empty_and_boolean(self):
        reg = Registry()
        from pyvelm import Boolean

        with reg.activate():

            class Item(BaseModel):
                _name = "test.track.fmt"
                active = Boolean(tracking=True)

        field = Item._fields["active"]
        env = Environment(object(), reg, uid=1)
        self.assertEqual(
            mail_tracking.format_field_value(env, field, None), "(empty)"
        )
        self.assertEqual(
            mail_tracking.format_field_value(env, field, True), "Yes"
        )


@unittest.skipUnless(DSN and psycopg, "needs postgres")
class TrackingWriteTests(unittest.TestCase):
    def test_write_posts_tracking_message(self):
        from pyvelm.mail import MailThread, Message

        reg = Registry()
        with reg.activate():

            class TrackDoc(MailThread, BaseModel):
                _name = "test.track.doc"
                name = Char(tracking=True)
                note = Char()

            reg.register(Message)

        with psycopg.connect(DSN) as conn:
            reg.init_db(conn)
            conn.commit()
            env = Environment(conn, reg, uid=1)
            doc = env["test.track.doc"].create(
                {"name": "Alpha", "note": "quiet"}
            )
            doc.write({"name": "Beta"})
            msgs = env["mail.message"].search(
                [("model", "=", "test.track.doc"), ("res_id", "=", doc.id)]
            )
            tracking = [
                m
                for m in msgs
                if getattr(m, "subtype", None) == "mail_tracking"
            ]
            self.assertEqual(len(tracking), 1)
            self.assertIn("Name", tracking[0].body)
            self.assertIn("Alpha", tracking[0].body)
            self.assertIn("Beta", tracking[0].body)
            self.assertIn("→", tracking[0].body)

            doc.write({"note": "changed"})
            tracking2 = env["mail.message"].search(
                [
                    ("model", "=", "test.track.doc"),
                    ("res_id", "=", doc.id),
                    ("subtype", "=", "mail_tracking"),
                ]
            )
            self.assertEqual(len(tracking2), 1)

    def test_non_mail_thread_skips_tracking(self):
        from pyvelm.mail import Message

        reg = Registry()
        with reg.activate():

            class Plain(BaseModel):
                _name = "test.track.plain"
                name = Char(tracking=True)

            reg.register(Message)

        with psycopg.connect(DSN) as conn:
            reg.init_db(conn)
            conn.commit()
            env = Environment(conn, reg, uid=1)
            rec = env["test.track.plain"].create({"name": "A"})
            rec.write({"name": "B"})
            count = env["mail.message"].search_count(
                [("model", "=", "test.track.plain")]
            )
            self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
