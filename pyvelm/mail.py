"""Mail thread mixin and message model (Stage 6 Slice D).

Two things ship here:

1. `mail.message` — a concrete model that stores every message/log entry.
   Keyed by (model, res_id) so messages are associated with any record
   on any model.  No foreign-key constraint on (model, res_id) because
   the target model/table is dynamic.

2. `MailThread` — a mixin base class.  Mix it into any model to get:
     record.message_post(body, message_type, subtype)
     record.message_ids   -> list of mail.message ids (read-only property)

Fields on mail.message
-----------------------
model          _name of the owning model (e.g. "res.partner")
res_id         Primary key of the owning record.
author_id      Many2one to res.users (nullable — system messages use None).
body           Text body (plain text or HTML; no enforcement here).
message_type   "comment" | "notification" | "email" (default "comment").
subtype        Free-form subtype label (e.g. "note", "done").
date           UTC naive datetime of posting.

Example
-------
    class Partner(MailThread, BaseModel):
        _name = "res.partner"
        ...

    partner.message_post("Hello!", message_type="comment")
    msgs = partner.message_ids  # list of mail.message ids
"""
from __future__ import annotations

from datetime import datetime

from pyvelm import BaseModel, Char, Integer, Many2one, Text
from pyvelm.cron import _DatetimeField  # reuse the datetime field from cron


class Message(BaseModel):
    _name = "mail.message"

    model = Char()
    res_id = Integer()
    author_id = Many2one("res.users", ondelete="SET NULL")
    body = Text()
    message_type = Char(default="comment")   # comment / notification / email
    subtype = Char()
    date = _DatetimeField()

    @property
    def display_name(self) -> str:
        self.ensure_one()
        return self.body[:60] if self.body else ""


class MailThread:
    """Mixin that adds chatter / message-thread capability to any model.

    Must appear before `BaseModel` in the MRO so that its `__init__`
    still delegates upward correctly:

        class MyModel(MailThread, BaseModel):
            _name = "my.model"
    """

    def message_post(
        self,
        body: str,
        *,
        message_type: str = "comment",
        subtype: str = "",
    ) -> "Message":
        """Create a new `mail.message` record associated with this record.

        Returns the new Message singleton.  Caller is responsible for
        wrapping in a transaction if needed.
        """
        self.ensure_one()
        if "mail.message" not in self.env.registry:
            raise RuntimeError(
                "mail.message model is not loaded — make sure the base "
                "module (which defines it) is installed."
            )
        vals: dict = {
            "model": self._name,
            "res_id": self.id,
            "body": body,
            "message_type": message_type,
            "date": datetime.utcnow(),
        }
        if subtype:
            vals["subtype"] = subtype
        if self.env.uid is not None and "res.users" in self.env.registry:
            vals["author_id"] = self.env.uid
        return self.env["mail.message"].create(vals)

    @property
    def message_ids(self) -> list[int]:
        """Return the ids of all messages attached to this record."""
        self.ensure_one()
        if "mail.message" not in self.env.registry:
            return []
        msgs = self.env["mail.message"].search([
            ("model", "=", self._name),
            ("res_id", "=", self.id),
        ])
        return msgs.ids
