"""pyvelm command-line entry points.

A single ``pyvelm`` command dispatches subcommands:

    pyvelm cron            Background cron + mail-dispatcher worker.
    pyvelm init <name>     Scaffold a new pyvelm project.
    pyvelm new <module>    Drop a runnable module skeleton into a project.

The legacy ``pyvelm-cron`` entry point keeps working — it's a thin
alias for ``pyvelm cron`` so existing docker-compose files and
systemd units don't need editing during upgrades.

Configuration is env-driven (CLI flags override). Most apps set
these in their ``.env``:

    PYVELM_DSN              Postgres DSN. Required for ``cron``.
    PYVELM_MODULE_ROOTS     Colon-separated module directories.
                            ``cron`` defaults to ``PYVELM_MODULE_ROOTS``.
    PYVELM_CRON_INTERVAL    Seconds between cron ticks. Default 60.
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


# ---------------------------------------------------------------------------
# cron subcommand
# ---------------------------------------------------------------------------

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


def _add_cron_args(parser: argparse.ArgumentParser) -> None:
    """Attach the cron-runner flags. Shared between ``pyvelm cron``
    (as a subparser) and the legacy ``pyvelm-cron`` (top-level)."""
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
            "separated PYVELM_MODULE_ROOTS env var. The framework's "
            "BUILTIN_MODULE_ROOTS are always prepended automatically."
        ),
    )


def _run_cron(args: argparse.Namespace) -> None:
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


# ---------------------------------------------------------------------------
# init / new subcommands (real implementations in slices 2 + 3)
# ---------------------------------------------------------------------------

def _run_init(args: argparse.Namespace) -> None:
    from .scaffolder import (
        echo_next_steps_for_init,
        materialise,
        valid_name,
    )

    name = args.name
    if not valid_name(name):
        sys.exit(
            f"Invalid project name {name!r}. Use a Python-identifier-"
            f"shaped name: letters, digits, and underscores; starts "
            f"with a letter."
        )
    target = Path.cwd() / name
    try:
        materialise("project", target, variables={"name": name})
    except FileExistsError:
        sys.exit(f"{target} already exists — pick a different name.")
    echo_next_steps_for_init(name)


def _run_new(_args: argparse.Namespace) -> None:
    sys.exit(
        "`pyvelm new` not yet implemented. Coming in the next release; "
        "for now, hand-author a module directory under your app's "
        "module root — see docs/modules.md for the on-disk shape."
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyvelm",
        description=(
            "pyvelm command-line tool. Subcommands: `cron` (background "
            "worker), `init` (scaffold a project), `new` (scaffold a "
            "module)."
        ),
    )
    subs = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    cron = subs.add_parser(
        "cron",
        help="Run the background cron + mail-dispatcher worker.",
        description=(
            "Long-running loop that ticks CronJob.run_due against a "
            "connection pool. SIGTERM/SIGINT exits gracefully."
        ),
    )
    _add_cron_args(cron)
    cron.set_defaults(func=_run_cron)

    init = subs.add_parser(
        "init",
        help="Scaffold a new pyvelm project (coming soon).",
    )
    init.add_argument(
        "name",
        help="Project directory to create.",
    )
    init.set_defaults(func=_run_init)

    new = subs.add_parser(
        "new",
        help="Scaffold a new module inside the current project (coming soon).",
    )
    new.add_argument(
        "name",
        help="Module name (also becomes the directory name).",
    )
    new.add_argument(
        "--in", dest="modules_root", default=None,
        help=(
            "Modules root directory. Defaults to auto-detection via "
            "pyvelm.toml in cwd or any parent."
        ),
    )
    new.set_defaults(func=_run_new)

    return parser


def main() -> None:
    """``pyvelm`` entry point — subcommand dispatch."""
    load_dotenv(".env")
    parser = _build_parser()
    args = parser.parse_args()
    args.func(args)


def cron_main() -> None:
    """``pyvelm-cron`` legacy entry point.

    Same shape as the old ``pyvelm-cron`` command (``--interval``,
    ``--roots``), still works without subcommand prefix. Kept so
    existing docker-compose files and systemd units survive a
    pyvelm upgrade without edits.
    """
    load_dotenv(".env")
    parser = argparse.ArgumentParser(
        prog="pyvelm-cron",
        description=(
            "Legacy entry; same as `pyvelm cron`. Kept for "
            "backward-compat with existing deployment configs."
        ),
    )
    _add_cron_args(parser)
    args = parser.parse_args()
    _run_cron(args)


if __name__ == "__main__":  # pragma: no cover
    main()
