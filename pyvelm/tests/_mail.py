"""Helpers for mail-related unit tests (minimal registry, no ``base`` module)."""
from __future__ import annotations

from pyvelm import BaseModel, Char, Registry


def register_res_users(reg: Registry) -> None:
    if "res.users" in reg:
        return

    class Users(BaseModel):
        _name = "res.users"
        name = Char()

    reg.register(Users)


def register_mail_message(reg: Registry) -> None:
    from pyvelm.mail import Message
    from pyvelm.mail_template import MailTemplate

    register_res_users(reg)
    if "mail.template" not in reg:
        reg.register(MailTemplate)
    reg.register(Message)


def register_mail_template(reg: Registry) -> None:
    from pyvelm.mail_template import MailTemplate

    register_mail_message(reg)
    reg.register(MailTemplate)
