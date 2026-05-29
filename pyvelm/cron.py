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


# Spacing between successive runs, derived from (interval_number,
# interval_type). Two semantic families share the field:
#
# * "every N <unit>" — minutes / hours / days / weeks / months / years.
#   Months and years are approximated (30 / 365 days) — for calendar-
#   exact recurrence, operators tweak ``nextcall`` by hand.
# * "<N> times per <unit>" — per_hour / per_day / per_week / per_month.
#   Spacing is ``unit / N`` (e.g. ``per_day=3`` → 8h between runs).
_INTERVAL_DELTAS = {
    "minutes": lambda n: timedelta(minutes=n),
    "hours": lambda n: timedelta(hours=n),
    "days": lambda n: timedelta(days=n),
    "weeks": lambda n: timedelta(weeks=n),
    "months": lambda n: timedelta(days=30 * n),
    "years": lambda n: timedelta(days=365 * n),
    "per_hour": lambda n: timedelta(hours=1) / max(n, 1),
    "per_day": lambda n: timedelta(days=1) / max(n, 1),
    "per_week": lambda n: timedelta(weeks=1) / max(n, 1),
    "per_month": lambda n: timedelta(days=30) / max(n, 1),
}


from .fields import Datetime as _DatetimeField  # noqa: E402,F401


class CronJob(BaseModel):
    _name = "ir.cron"

    name = Char(required=True)
    action_id = Many2one("ir.actions.server", ondelete="CASCADE")
    interval_number = Integer(default=1, string="Interval")
    interval_type = Char(
        default="hours",
        string="Unit",
        # Two families: "every N <unit>" and "<N> times per <unit>".
        # The cron runner picks the right spacing via _INTERVAL_DELTAS.
        choices=[
            ("minutes", "Minutes"),
            ("hours", "Hours"),
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
            ("years", "Years"),
            ("per_hour", "Times / hour"),
            ("per_day", "Times / day"),
            ("per_week", "Times / week"),
            ("per_month", "Times / month"),
        ],
    )
    nextcall = _DatetimeField(string="Next call")
    # Stamped by `run_due` (and by the "Run Now" admin button) every
    # time the job's action executes, regardless of outcome. Operators
    # use this to confirm a job is actually firing.
    lastcall = _DatetimeField(string="Last call")
    active = Boolean(default=True)

    def run_now(self):
        """Execute this job's action immediately.

        Stamps ``lastcall`` and advances ``nextcall`` by the configured
        interval — so manually triggering a job resets its schedule the
        same way the periodic runner would. Re-raises any exception
        from the action so the caller can surface it (the schedule
        still advances; we don't want a flaky job to wedge the queue).
        """
        self.ensure_one()
        env = self.env
        if not self.action_id:
            raise RuntimeError(f"Cron {self.name!r} has no action_id")
        action = env["ir.actions.server"].browse(self.action_id.id)
        if not action.target_model_available():
            raise RuntimeError(
                f"Cron {self.name!r}: action {action.name!r} targets "
                f"{action.model!r}, which is not installed"
            )
        prev_bypass = env._acl_bypass
        env._acl_bypass = True
        try:
            try:
                action.run(env[action.model].search([]))
            finally:
                now = datetime.utcnow()
                updates: dict = {"lastcall": now}
                delta_fn = _INTERVAL_DELTAS.get(self.interval_type or "hours")
                if delta_fn:
                    updates["nextcall"] = now + delta_fn(self.interval_number or 1)
                with env.transaction():
                    self.write(updates)
        finally:
            env._acl_bypass = prev_bypass

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
                if not action.target_model_available():
                    import sys
                    print(
                        f"[cron] {job.name!r} skipped: action {action.name!r} "
                        f"targets {action.model!r}, which is not installed",
                        file=sys.stderr,
                    )
                    # Drop known smoke-test rows so the warning does not repeat.
                    if job.name == "Test cron":
                        with env.transaction():
                            job.unlink()
                        if action.name == "Cron tick":
                            with env.transaction():
                                action.unlink()
                        continue
                    interval_n = job.interval_number or 1
                    interval_t = job.interval_type or "hours"
                    delta_fn = _INTERVAL_DELTAS.get(interval_t)
                    updates: dict = {"lastcall": now}
                    if delta_fn:
                        updates["nextcall"] = (nextcall or now) + delta_fn(interval_n)
                    with env.transaction():
                        job.write(updates)
                    continue
                try:
                    action.run(env[action.model].search([]))
                    executed.append(job.name)
                except Exception as exc:  # noqa: BLE001
                    import sys
                    print(
                        f"[cron] {job.name!r} failed: {exc}",
                        file=sys.stderr,
                    )
                # Advance nextcall regardless of success so we don't tight-loop.
                # Stamp lastcall in the same write so operators can confirm
                # the job actually fired.
                interval_n = job.interval_number or 1
                interval_t = job.interval_type or "hours"
                delta_fn = _INTERVAL_DELTAS.get(interval_t)
                updates: dict = {"lastcall": now}
                if delta_fn:
                    updates["nextcall"] = (nextcall or now) + delta_fn(interval_n)
                with env.transaction():
                    job.write(updates)
        finally:
            env._acl_bypass = prev_bypass

        return executed
