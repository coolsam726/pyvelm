"""Register sqlite3 date/time adapters (Python 3.12+ deprecation fix).

The stdlib default datetime adapter is deprecated; SQLAlchemy and our
text-SQL path may still pass ``datetime`` objects to sqlite3. Register
ISO-8601 adapters once per process (same format as
:func:`pyvelm.database.dialects.sqlite.bind_params`).
"""
from __future__ import annotations

from datetime import date, datetime, time

_REGISTERED = False


def adapt_datetime_iso(val: datetime) -> str:
    return val.isoformat(sep=" ")


def adapt_date_iso(val: date) -> str:
    return val.isoformat()


def adapt_time_iso(val: time) -> str:
    return val.isoformat()


def register_sqlite3_datetime_adapters() -> None:
    """Idempotent registration of sqlite3 adapters for date/time types."""
    global _REGISTERED
    if _REGISTERED:
        return
    import sqlite3

    sqlite3.register_adapter(datetime, adapt_datetime_iso)
    sqlite3.register_adapter(date, adapt_date_iso)
    sqlite3.register_adapter(time, adapt_time_iso)
    _REGISTERED = True
