"""Scheduled-job model (Stage 6 Slice C).

`ir.cron` records describe periodic jobs.  Each job references an
`ir.actions.server` via `action_id`; the host is responsible for
calling `CronJob.run_due(env)` at whatever cadence it wants (a
system cron, APScheduler, a startup thread, etc.).  pyvelm itself
ships no daemon thread — keeping async/threading out of the ORM core
was an explicit decision.

Fields
------
name           Human-readable label.
action_id      The server action to execute.
interval_number Number of units between runs (e.g. 1, 5, 30).
interval_type   Unit: 'minutes' | 'hours' | 'days' | 'weeks'.
nextcall        Timestamp of the next scheduled run (UTC naive).
active          Inactive jobs are skipped even if overdue.

Usage
-----
    from pyvelm.cron import CronJob
    CronJob.run_due(env)   # call periodically from your scheduler
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from pyvelm import BaseModel, Boolean, Char, Integer, Many2one
from pyvelm.fields import Field


_INTERVAL_DELTAS = {
    "minutes": lambda n: timedelta(minutes=n),
    "hours": lambda n: timedelta(hours=n),
    "days": lambda n: timedelta(days=n),
    "weeks": lambda n: timedelta(weeks=n),
}


class _DatetimeField(Field):
    """Minimal datetime field — stored as TIMESTAMP, Python datetime."""

    sql_type = "timestamp"
    python_type = datetime

    def column_ddl(self) -> str:
        null = "" if self.required else " NULL"
        return f'"{self.column}" timestamp{null}'

    def to_sql_param(self, value):
        if value is None or value is False:
            return None
        if isinstance(value, datetime):
            return value
        # Accept ISO 8601 strings.
        return datetime.fromisoformat(str(value))

    def to_python(self, value):
        return value  # psycopg returns datetime already


class CronJob(BaseModel):
    _name = "ir.cron"

    name = Char(required=True)
    action_id = Many2one("ir.actions.server", ondelete="CASCADE")
    interval_number = Integer(default=1)
    interval_type = Char(default="hours")   # minutes/hours/days/weeks
    nextcall = _DatetimeField()
    active = Boolean(default=True)

    @classmethod
    def run_due(cls, env) -> list[str]:
        """Execute every active cron job whose `nextcall` is in the past.

        Advances `nextcall` by the configured interval after each run.
        Returns the names of jobs that were executed.
        Returns early (empty list) if ir.cron is not in the registry.
        """
        if "ir.cron" not in env.registry:
            return []

        now = datetime.utcnow()
        prev_bypass = env._acl_bypass
        env._acl_bypass = True
        executed = []
        try:
            jobs = env["ir.cron"].search([("active", "=", True)])
            for job in jobs:
                nextcall = job.nextcall
                if nextcall is not None and nextcall > now:
                    continue  # not due yet
                if not job.action_id:
                    continue

                action = env["ir.actions.server"].browse(job.action_id.id)
                try:
                    action.run()
                    executed.append(job.name)
                except Exception as exc:  # noqa: BLE001
                    import sys
                    print(
                        f"[cron] {job.name!r} failed: {exc}",
                        file=sys.stderr,
                    )
                # Advance nextcall regardless of success so we don't tight-loop.
                interval_n = job.interval_number or 1
                interval_t = job.interval_type or "hours"
                delta_fn = _INTERVAL_DELTAS.get(interval_t)
                if delta_fn:
                    new_next = (nextcall or now) + delta_fn(interval_n)
                    with env.transaction():
                        job.write({"nextcall": new_next})
        finally:
            env._acl_bypass = prev_bypass

        return executed
