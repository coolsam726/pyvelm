"""pyvelm command-line entry points.

A single ``pyvelm`` command dispatches subcommands:

    pyvelm cron                Background cron + mail-dispatcher worker.
    pyvelm init <name>         Scaffold a new pyvelm project.
    pyvelm new <module>        Drop a runnable module skeleton into a project.
    pyvelm db diff <module>    Print the schema delta for a module.
    pyvelm db autogen <module> Write an additive migration file.

The legacy ``pyvelm-cron`` entry point keeps working — it's a thin
alias for ``pyvelm cron`` so existing docker-compose files and
systemd units don't need editing during upgrades.

Configuration is env-driven (CLI flags override). Most apps set
these in their ``.env``:

    PYVELM_DSN              Postgres DSN. Required for ``cron``/``db``.
    PYVELM_MODULE_ROOTS     Colon-separated module directories.
                            ``cron``/``db`` default to PYVELM_MODULE_ROOTS.
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


def _run_new(args: argparse.Namespace) -> None:
    from .scaffolder import (
        echo_next_steps_for_new,
        find_modules_root,
        materialise,
        valid_name,
    )

    name = args.name
    if not valid_name(name):
        sys.exit(
            f"Invalid module name {name!r}. Use a Python-identifier-"
            f"shaped name: letters, digits, and underscores; starts "
            f"with a letter."
        )

    # Find the modules root: explicit --in wins, otherwise walk up
    # from cwd looking for `pyvelm.toml`.
    if args.modules_root is not None:
        modules_root = Path(args.modules_root).resolve()
    else:
        modules_root = find_modules_root()
        if modules_root is None:
            sys.exit(
                "Couldn't find a pyvelm.toml in cwd or any parent. "
                "Run this from inside a `pyvelm init`'d project, or "
                "pass `--in <path>` pointing at the modules directory."
            )

    # The modules root may not exist yet if the user is bootstrapping
    # outside the scaffolder's tree. Create the directory chain so the
    # module's parent is in place; the module itself must not exist.
    modules_root.mkdir(parents=True, exist_ok=True)
    target = modules_root / name
    try:
        materialise("module", target, variables={"name": name})
    except FileExistsError:
        sys.exit(
            f"{target} already exists — pick a different module name "
            f"or remove the existing directory."
        )
    echo_next_steps_for_new(name, modules_root)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# db subcommand — schema diff + migration autogen
# ---------------------------------------------------------------------------


def _add_db_subcommand(subs) -> None:
    db = subs.add_parser(
        "db",
        help="Schema utilities (diff, autogen-migration).",
        description=(
            "Inspect or update the DB schema against the loaded module "
            "registry. `diff` prints what's missing; `autogen` writes a "
            "migration file. Both require PYVELM_DSN."
        ),
    )
    db_subs = db.add_subparsers(
        dest="db_command", required=True, metavar="<db-command>"
    )

    diff_p = db_subs.add_parser(
        "diff",
        help="Print the schema delta for a module (no file write).",
    )
    diff_p.add_argument("module", help="Module name (e.g. 'base').")
    diff_p.add_argument(
        "--roots", nargs="*",
        default=_parse_roots(os.environ.get("PYVELM_MODULE_ROOTS", "")),
        help="Module-discovery roots (defaults to PYVELM_MODULE_ROOTS).",
    )
    diff_p.set_defaults(func=_run_db_diff)

    auto_p = db_subs.add_parser(
        "autogen",
        help=(
            "Write a migration file from the schema delta, bumping the "
            "module's minor version."
        ),
    )
    auto_p.add_argument("module", help="Module name.")
    auto_p.add_argument(
        "--roots", nargs="*",
        default=_parse_roots(os.environ.get("PYVELM_MODULE_ROOTS", "")),
        help="Module-discovery roots (defaults to PYVELM_MODULE_ROOTS).",
    )
    auto_p.add_argument(
        "--version", dest="target_version", default=None,
        help=(
            "Explicit target version (e.g. '0.17.0'). Defaults to a "
            "minor bump of the module's current VERSION."
        ),
    )
    auto_p.add_argument(
        "--dry-run", action="store_true",
        help="Print the would-be file contents instead of writing.",
    )
    auto_p.set_defaults(func=_run_db_autogen)


def _build_db_env_and_spec(args):
    """Common bootstrap for db subcommands.

    Returns ``(env, spec, conn)`` — caller is responsible for closing
    the connection. Exits with a clear error if the module isn't
    found or if PYVELM_DSN is missing.
    """
    import psycopg

    from . import BUILTIN_MODULE_ROOTS, Environment, Registry, loader

    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN not set")
    roots = list(BUILTIN_MODULE_ROOTS) + [Path(p) for p in args.roots]
    specs = loader.discover(roots)
    if args.module not in specs:
        sys.exit(
            f"Module {args.module!r} not discovered. "
            f"Known: {sorted(specs)}"
        )
    ordered = loader.resolve_order(specs)
    registry = Registry()
    for spec in ordered:
        loader._load_models(spec, registry)
    conn = psycopg.connect(dsn, autocommit=True)
    env = Environment(conn, registry=registry)
    return env, specs[args.module], conn


def _run_db_diff(args: argparse.Namespace) -> None:
    from . import db_autogen

    env, _spec, conn = _build_db_env_and_spec(args)
    try:
        diff = db_autogen.compute_diff(env, args.module)
    finally:
        conn.close()
    if diff.is_empty:
        print(f"{args.module}: no schema changes.")
        return
    print(f"{args.module}: {db_autogen._summary(diff)}")
    for table, _ddl in diff.new_tables:
        print(f"  + table {table}")
    for table, col, _stmt, was_required in diff.new_columns:
        tag = " (required — needs backfill)" if was_required else ""
        print(f"  + column {table}.{col}{tag}")
    for table, col in diff.orphan_columns:
        print(f"  - orphan {table}.{col}")


def _run_db_autogen(args: argparse.Namespace) -> None:
    from . import db_autogen

    env, spec, conn = _build_db_env_and_spec(args)
    try:
        diff = db_autogen.compute_diff(env, args.module)
    finally:
        conn.close()
    cur_version = tuple(spec.version)
    if args.target_version:
        new_version = db_autogen.parse_version(args.target_version)
    else:
        new_version = db_autogen.next_minor_version(cur_version)
    body = db_autogen.render_migration(diff, cur_version, new_version)
    fname = db_autogen.migration_filename(cur_version, new_version)
    mig_dir = Path(spec.package_path) / "migrations"
    target = mig_dir / fname
    if args.dry_run:
        print(f"# would write {target}\n")
        print(body, end="")
        return
    if target.exists():
        sys.exit(f"Refusing to overwrite existing migration: {target}")
    mig_dir.mkdir(exist_ok=True)
    target.write_text(body)
    # Bump VERSION in __pyvelm__.py.
    manifest = Path(spec.package_path) / "__pyvelm__.py"
    text = manifest.read_text()
    old_v_repr = repr(tuple(cur_version))
    new_v_repr = repr(tuple(new_version))
    if old_v_repr not in text:
        sys.exit(
            f"Could not find VERSION = {old_v_repr} in {manifest}; "
            f"bump it manually."
        )
    manifest.write_text(text.replace(old_v_repr, new_v_repr, 1))
    print(f"Wrote {target}")
    print(f"Bumped VERSION: {cur_version} → {new_version}")
    if diff.is_empty:
        print("(Migration body is a no-op — review whether you really need it.)")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyvelm",
        description=(
            "pyvelm command-line tool. Subcommands: `cron` (background "
            "worker), `init` (scaffold a project), `new` (scaffold a "
            "module), `db` (schema utilities)."
        ),
    )
    subs = parser.add_subparsers(dest="command", required=True, metavar="<command>")
    _add_db_subcommand(subs)

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
