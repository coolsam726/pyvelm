"""pyvelm command-line entry points.

Today this ships a single command — ``pyvelm-cron`` — but the file is
intentionally `cli` (not `cron_cli`) so additional commands can land
here without churning the entry-point table.

The cron runner is a thin loop around ``CronJob.run_due``:

    ┌──────────── boot (once) ────────────┐
    │   pool = ConnectionPool(...)         │
    │   reg  = Registry();                 │
    │   loader.load_and_install(roots,…)   │
    └──────────────────────────────────────┘
                  │
                  ▼
    ┌──────── steady-state (tick) ─────────┐
    │   with pool.connection() as conn:    │
    │     env = Environment(conn, reg)     │
    │     CronJob.run_due(env)             │
    │   sleep(interval)                    │
    └──────────────────────────────────────┘

Concurrency caveat: ``CronJob.run_due`` does a plain SELECT-then-
UPDATE, so running multiple cron workers against the same database
will occasionally double-fire jobs at exactly their due time. Until a
``SELECT … FOR UPDATE SKIP LOCKED`` lands, the rule is **one cron
worker per DB**. Configure ``GUNICORN_WORKERS=1`` if you're rolling
the cron loop inside the web container (not the recommended layout);
the better pattern is the dedicated ``cron`` service in
``docker-compose.yml`` which runs exactly one replica.

Configuration is env-driven (with CLI overrides):

    PYVELM_DSN              Postgres DSN. Required.
    PYVELM_MODULE_ROOTS     Colon-separated module directories. Required.
                            Override with ``--roots``.
    PYVELM_CRON_INTERVAL    Seconds between ticks. Default 60.
                            Override with ``--interval``.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

from .env import Environment
from . import loader
from .registry import Registry

log = logging.getLogger("pyvelm.cron")


def _parse_roots(value: str) -> list[Path]:
    return [Path(p) for p in (value or "").split(":") if p]


def cron_loop(*, dsn: str, roots: list[Path], interval: float) -> None:
    """Boot the registry against `dsn` + `roots`, then loop forever.

    SIGTERM / SIGINT flip a shutdown flag and the loop exits cleanly
    after the current tick — useful for graceful container restarts.
    """
    registry = Registry()
    # Install pass on boot. The install is idempotent for an already-
    # migrated database, so this is safe to run on every cron-worker
    # restart and doubles as a "the DB schema matches the on-disk
    # manifests" check.
    with psycopg.connect(dsn, autocommit=True) as conn:
        env = Environment(conn, registry=registry)
        loader.load_and_install(roots, env)
        log.info("loaded modules; cron runner ready")

    pool = ConnectionPool(dsn, min_size=1, max_size=2, open=True)

    shutdown = False

    def _sig(_signum, _frame):
        nonlocal shutdown
        shutdown = True
        log.info("shutdown signal received")

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    try:
        while not shutdown:
            try:
                _tick(pool, registry)
            except Exception:  # noqa: BLE001
                # Don't kill the runner on a single failed tick — log
                # and try again next interval.
                log.exception("cron tick failed")
            # Sleep in 1-second slices so the signal handler can pre-empt.
            elapsed = 0.0
            while elapsed < interval and not shutdown:
                time.sleep(min(1.0, interval - elapsed))
                elapsed += 1.0
    finally:
        pool.close()


def _tick(pool, registry: Registry) -> None:
    """One iteration of the loop — checked out into its own connection
    so the failure of one tick can't leak across ticks."""
    from .cron import CronJob

    with pool.connection() as conn:
        env = Environment(conn, registry=registry)
        executed = CronJob.run_due(env)
        if executed:
            log.info("ran %d job(s): %s", len(executed), executed)


def main() -> None:
    load_dotenv(".env")

    parser = argparse.ArgumentParser(
        prog="pyvelm-cron",
        description="pyvelm background cron runner",
    )
    parser.add_argument(
        "--interval", type=float,
        default=float(os.environ.get("PYVELM_CRON_INTERVAL", "60")),
        help="Seconds between ticks (default: PYVELM_CRON_INTERVAL or 60).",
    )
    parser.add_argument(
        "--roots", nargs="*",
        default=_parse_roots(os.environ.get("PYVELM_MODULE_ROOTS", "")),
        help=(
            "One or more module-discovery roots. Defaults to the colon-"
            "separated PYVELM_MODULE_ROOTS env var."
        ),
    )
    args = parser.parse_args()

    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN not set")

    # Framework-bundled modules always come first — the loader install
    # order matters (deps before dependants) and built-ins are
    # depended on by app modules. Caller-supplied roots are appended.
    from . import BUILTIN_MODULE_ROOTS
    all_roots = list(BUILTIN_MODULE_ROOTS) + [Path(p) for p in args.roots]

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    log.info(
        "starting cron runner: interval=%ss roots=%s",
        args.interval, [str(p) for p in all_roots],
    )
    cron_loop(
        dsn=dsn,
        roots=all_roots,
        interval=args.interval,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
