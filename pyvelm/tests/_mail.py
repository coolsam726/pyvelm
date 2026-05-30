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


def _placeholder_value(data_type: str):
    t = (data_type or "").lower()
    if any(k in t for k in ("int", "serial")):
        return 0
    if "bool" in t:
        return False
    if "timestamp" in t or "datetime" in t:
        from datetime import datetime

        return datetime(2020, 1, 1)
    if t == "date":
        from datetime import date

        return date(2020, 1, 1)
    if any(k in t for k in ("numeric", "double", "real", "float", "decimal")):
        return 0
    if "json" in t:
        return "{}"
    return "tester"


def seed_author(env, uid: int = 1) -> None:
    """Ensure a ``res.users`` row ``uid`` exists.

    Mail messages set ``author_id = env.uid``; Postgres enforces the
    ``mail_message.author_id`` FK, so tests running as ``uid=1`` need a
    matching ``res_users`` row (SQLite silently skipped this). The live
    ``res_users`` table may carry more NOT NULL columns than the minimal test
    registry knows about (earlier integration tests can leave the real schema
    behind on a shared database), so introspect it and fill every required
    column.
    """
    cap = getattr(env.conn, "capabilities", None)
    is_pg = cap is not None and cap.name == "postgresql"
    values: dict[str, object] = {"id": uid}
    if is_pg:
        rows = env.conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'res_users' "
            "AND is_nullable = 'NO' AND column_default IS NULL "
            "AND column_name <> 'id'"
        ).fetchall()
        for name, data_type in rows:
            values[name] = _placeholder_value(data_type)
    else:
        for row in env.conn.execute('PRAGMA table_info("res_users")').fetchall():
            _cid, name, col_type, notnull, dflt, _pk = row
            if name == "id" or not notnull or dflt is not None:
                continue
            values[name] = _placeholder_value(col_type)

    cols = ", ".join(f'"{c}"' for c in values)
    marks = ", ".join(["%s"] * len(values))
    conflict = ' ON CONFLICT ("id") DO NOTHING' if is_pg else ""
    env.conn.execute(
        f'INSERT INTO "res_users" ({cols}) VALUES ({marks}){conflict}',
        tuple(values.values()),
    )
    if is_pg:
        env.conn.execute(
            "SELECT setval(pg_get_serial_sequence('res_users', 'id'), "
            "GREATEST((SELECT MAX(id) FROM res_users), 1))"
        )
