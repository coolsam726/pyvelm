"""pyvelm command-line entry points.

A single ``pyvelm`` command dispatches subcommands:

    pyvelm cron                Background cron + mail-dispatcher worker.
    pyvelm init <name>         Scaffold a new pyvelm project.
    pyvelm new <module>        Drop a runnable module skeleton into a project.
    pyvelm db diff <module>    Print the schema delta for a module.
    pyvelm db autogen <module> Write an additive migration file.
    pyvelm migrate               Upgrade installed modules (deploy hook).
    pyvelm db migrate-fresh    Same as migrate, with plan + prod confirmation.
    pyvelm migrate:fresh       DEV ONLY — drop schema, then ``migrate``.
    pyvelm migrate:reset       DEV ONLY — drop schema (same wipe as ``db nuke``).
    pyvelm db nuke             DEV ONLY — drop schema + reinstall every module.
    pyvelm db status           Installed vs on-disk module versions.
    pyvelm list                List core and module commands.
    pyvelm make:module …       Scaffold a module (see docs/console.md).

The legacy ``pyvelm-cron`` entry point keeps working — it's a thin
alias for ``pyvelm cron`` so existing docker-compose files and
systemd units don't need editing during upgrades.

Configuration is env-driven (CLI flags override). Most apps set
these in their ``.env``:

    PYVELM_DSN              Postgres DSN. Required for ``cron``/``db``.
    PYVELM_MODULE_ROOTS     Extra module dirs (comma or colon separated).
                            ``cron``/``db`` also auto-detect ``modules_root``
                            from ``pyvelm.toml`` in cwd or a parent.
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

from .env import Environment
from . import loader
from .registry import Registry

log = logging.getLogger("pyvelm.cron")


def _parse_roots(value: str) -> list[Path]:
    return loader.parse_module_roots_env(value)


def _default_module_roots() -> list[Path]:
    """Discovery roots for CLI commands — mirrors ``app/serve.py``.

    Order: bundled ``base``/``admin``, then ``pyvelm.toml``'s
    ``modules_root`` (walk up from cwd), then ``PYVELM_MODULE_ROOTS``.
    """
    from . import BUILTIN_MODULE_ROOTS
    from .scaffolder import find_modules_root

    roots: list[Path] = list(BUILTIN_MODULE_ROOTS)
    seen = {str(r.resolve()) for r in roots}
    app_root = find_modules_root()
    if app_root is not None and app_root.is_dir():
        key = str(app_root.resolve())
        if key not in seen:
            roots.append(app_root)
            seen.add(key)
    for part in _parse_roots(os.environ.get("PYVELM_MODULE_ROOTS", "")):
        key = str(part.resolve())
        if part.is_dir() and key not in seen:
            roots.append(part)
            seen.add(key)
    return roots


def _resolve_module_roots(args: argparse.Namespace) -> list[Path]:
    """Merge explicit ``--roots`` with builtins, or use defaults."""
    from . import BUILTIN_MODULE_ROOTS

    if getattr(args, "roots", None):
        return list(BUILTIN_MODULE_ROOTS) + list(args.roots)
    return _default_module_roots()


# ---------------------------------------------------------------------------
# cron subcommand
# ---------------------------------------------------------------------------

def cron_loop(*, dsn: str, roots: list[Path], interval: float) -> None:
    """Boot the registry against `dsn` + `roots`, then loop forever.

    SIGTERM / SIGINT flip a shutdown flag and the loop exits cleanly
    after the current tick — useful for graceful container restarts.
    """
    from .database import create_database_from_dsn, normalize_dsn

    registry = Registry()
    database = create_database_from_dsn(normalize_dsn(dsn), pool_size=2)
    with database.connect() as conn:
        env = Environment(conn, registry=registry)
        loader.load_and_install(roots, env)
        log.info("loaded modules; cron runner ready")

    pool = database.pool

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
        database.dispose()


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
        "--roots", nargs="*", default=None,
        help=(
            "Extra module-discovery roots (in addition to builtins). "
            "When omitted, uses pyvelm.toml modules_root (walk up from "
            "cwd) plus PYVELM_MODULE_ROOTS."
        ),
    )


def _run_cron(args: argparse.Namespace) -> None:
    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN not set")

    # Framework-bundled modules always come first — the loader install
    # order matters (deps before dependants) and built-ins are
    # depended on by app modules. Caller-supplied roots are appended.
    all_roots = _resolve_module_roots(args)

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
        materialise(
            "project",
            target,
            variables={
                "name": name,
                "stub_path": ".pyvelm/typing",
                "include_json": '["app"]',
            },
        )
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
    from .loader import module_display_name

    try:
        materialise(
            "module",
            target,
            variables={
                "name": name,
                "display_name": module_display_name(name),
            },
        )
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
        help="Schema utilities (diff, autogen, migrate, nuke, status).",
        description=(
            "Inspect or update the DB schema against the loaded module "
            "registry. `diff` / `autogen` draft migrations; use "
            "``pyvelm migrate`` to install/upgrade modules; "
            "`migrate-fresh` adds a plan and production confirmation; "
            "`nuke` (dev only) drops the schema and re-runs every "
            "install from scratch; `status` lists versions. Requires "
            "PYVELM_DSN."
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
        "--roots", nargs="*", default=None,
        help="Extra module roots (default: pyvelm.toml + PYVELM_MODULE_ROOTS).",
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
        "--roots", nargs="*", default=None,
        help="Extra module roots (default: pyvelm.toml + PYVELM_MODULE_ROOTS).",
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
    auto_p.add_argument(
        "--with-views", action="store_true",
        help=(
            "For each model changed by the migration, create list+form "
            "views when none exist yet (views/<model>.py + DATA entry)."
        ),
    )
    auto_p.set_defaults(func=_run_db_autogen)

    mig_p = db_subs.add_parser(
        "migrate",
        help="Deprecated alias for ``pyvelm migrate``.",
    )
    mig_p.add_argument(
        "--roots", nargs="*", default=None,
        help="Extra module roots (default: pyvelm.toml + PYVELM_MODULE_ROOTS).",
    )
    mig_p.add_argument(
        "--all", action="store_true",
        help="Install/upgrade every discovered module (legacy full-stack pass).",
    )
    mig_p.add_argument(
        "--module", dest="only_module", default=None,
        help="Limit to one module and its dependencies (e.g. partners).",
    )
    mig_p.add_argument(
        "--database", dest="database_key", default=None,
        help="Target tenant database from PYVELM_DATABASES (v1.1+).",
    )
    mig_p.set_defaults(func=_run_db_migrate_shim)

    fresh_p = db_subs.add_parser(
        "migrate-fresh",
        help=(
            "Install/upgrade with a pre-flight plan; requires confirmation "
            "when PYVELM_ENV=production."
        ),
    )
    fresh_p.add_argument(
        "--roots", nargs="*", default=None,
        help="Extra module roots (default: pyvelm.toml + PYVELM_MODULE_ROOTS).",
    )
    fresh_p.add_argument(
        "--module", dest="only_module", default=None,
        help="Limit to one module and its dependencies (e.g. base).",
    )
    fresh_p.add_argument(
        "--all", action="store_true",
        help="Install/upgrade every discovered module (legacy full-stack pass).",
    )
    fresh_p.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip interactive confirmation (for CI; still prints warnings).",
    )
    fresh_p.add_argument(
        "--dry-run", action="store_true",
        help="Print the migration plan only; do not change the database.",
    )
    fresh_p.set_defaults(func=_run_db_migrate_fresh)

    st_p = db_subs.add_parser(
        "status",
        help="Show installed ir_module versions vs on-disk manifests.",
    )
    st_p.add_argument(
        "--roots", nargs="*", default=None,
        help="Extra module roots (default: pyvelm.toml + PYVELM_MODULE_ROOTS).",
    )
    st_p.set_defaults(func=_run_db_status)

    nuke_p = db_subs.add_parser(
        "nuke",
        help=(
            "DEV ONLY — DROP the schema (same wipe as migrate:reset), then "
            "reinstall every discovered module. Type ``nuke`` to confirm."
        ),
    )
    nuke_p.add_argument(
        "--roots", nargs="*", default=None,
        help="Extra module roots (default: pyvelm.toml + PYVELM_MODULE_ROOTS).",
    )
    nuke_p.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip the interactive confirmation (for CI / scripts).",
    )
    nuke_p.add_argument(
        "--schema", default="public",
        help='Postgres schema to drop and recreate. Default "public".',
    )
    nuke_p.set_defaults(func=_run_db_nuke)


def _build_db_env_and_spec(args):
    """Common bootstrap for db subcommands.

    Returns ``(env, spec, conn)`` — caller is responsible for closing
    the connection. Exits with a clear error if the module isn't
    found or if PYVELM_DSN is missing.
    """
    from . import Environment, Registry, loader
    from .database import create_database_from_dsn, normalize_dsn

    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN not set")
    roots = _resolve_module_roots(args)
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
    db = create_database_from_dsn(normalize_dsn(dsn))
    conn = db.open_connection()
    env = Environment(conn, registry=registry)
    return env, specs[args.module], conn


def _run_db_diff(args: argparse.Namespace) -> None:
    from . import db_autogen

    env, _spec, conn = _build_db_env_and_spec(args)
    try:
        diff = db_autogen.compute_diff(env, args.module)
        if diff.is_empty:
            print(f"{args.module}: no schema changes.")
            return
        print(f"{args.module}: {db_autogen._summary(diff)}")
        for table, _ddl in diff.new_tables:
            print(f"  + table {table}")
        for table, col, _stmt, was_required, _sql_type in diff.new_columns:
            tag = " (required — needs backfill)" if was_required else ""
            print(f"  + column {table}.{col}{tag}")
        for alt in diff.alterations:
            print(alt.cli_line())
            if alt.kind == "set_not_null":
                nulls = db_autogen.count_null_rows(env, alt.table, alt.column)
                if nulls:
                    print(
                        f"      → migrate will NOT apply SET NOT NULL yet: "
                        f"{nulls} row(s) have NULL in {alt.table}.{alt.column}"
                    )
                    print(
                        "      → backfill those rows (migration script or SQL), "
                        "then run pyvelm migrate again"
                    )
                else:
                    print(
                        f"      → no NULL rows; pyvelm migrate should apply "
                        f"SET NOT NULL on {alt.table}.{alt.column}"
                    )
        for table, col in diff.orphan_columns:
            print(f"  - orphan {table}.{col}")
    finally:
        conn.close()


def _run_db_autogen(args: argparse.Namespace) -> None:
    from . import db_autogen
    from . import scaffold_generators

    env, spec, conn = _build_db_env_and_spec(args)
    try:
        diff = db_autogen.compute_diff(env, args.module)
        if getattr(args, "with_views", False) and not diff.is_empty:
            affected = scaffold_generators.models_affected_by_diff(
                env, args.module, diff,
            )
            created = scaffold_generators.ensure_views_for_models(
                spec,
                affected,
                registry=env.registry,
            )
            for path in created:
                print(f"Created view: {path}")
            if not created and affected:
                print("All affected models already have list views.")
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


from .migrate_cli import (
    confirm_destructive_phrase as _confirm_destructive_phrase,
    confirm_migrate_fresh as _confirm_migrate_fresh,
    drop_schema_contents as _drop_schema_contents,
    dsn_display as _dsn_display,
    execute_db_install as _execute_db_install,
    guard_destructive_schema_command as _guard_destructive_schema_command,
    ordered_specs_for_install as _ordered_specs_for_install,
    print_install_results as _print_install_results,
    read_installed_versions as _read_installed_versions,
    require_dsn as _require_dsn,
    resolve_migrate_specs as _resolve_migrate_specs,
    run_db_migrate_fresh,
    run_migrate,
    wipe_schema as _wipe_schema,
)


def _run_db_migrate_shim(args: argparse.Namespace) -> None:
    """Backward-compatible alias for ``pyvelm migrate``."""
    print(
        "note: `pyvelm db migrate` is deprecated — use `pyvelm migrate`",
        file=sys.stderr,
    )
    run_migrate(
        _resolve_module_roots(args),
        install_all=args.all,
        only_module=args.only_module,
        database_key=getattr(args, "database_key", None),
    )


def _run_db_migrate_fresh(args: argparse.Namespace) -> None:
    run_db_migrate_fresh(
        _resolve_module_roots(args),
        install_all=args.all,
        only_module=args.only_module,
        yes=args.yes,
        dry_run=args.dry_run,
    )


def _confirm_nuke(*, dsn: str, schema: str, yes: bool) -> None:
    _confirm_destructive_phrase(
        phrase="nuke",
        yes=yes,
        preamble=(
            f"This will DROP every table, view, sequence, and function in "
            f"schema {schema!r} of {_dsn_display(dsn)}.\n"
            f"All data is lost. There is no undo."
        ),
    )


def _run_db_nuke(args: argparse.Namespace) -> None:
    """DROP the schema and re-run every module install from scratch.

    Same schema wipe as ``migrate:reset``, then reinstalls **every**
    discovered module (``migrate --all``). Refuses production unless
    ``PYVELM_ALLOW_DB_NUKE=1``. Type ``nuke`` to confirm (or ``--yes``).
    """
    from .database import normalize_dsn, nuke_dsn_from_env as _nuke_dsn_from_env
    from .runtime import get_runtime_env

    _guard_destructive_schema_command(label="db nuke")

    dsn = _require_dsn()
    nuke_dsn = _nuke_dsn_from_env()
    roots = _resolve_module_roots(args)
    ordered = _ordered_specs_for_install(roots, None)
    schema = args.schema or "public"

    print("Nuke + reinstall plan")
    print(f"  PYVELM_ENV:     {get_runtime_env()}")
    print(f"  Database:       {_dsn_display(dsn)}")
    if nuke_dsn != normalize_dsn(dsn):
        print(f"  Nuke DSN:       {_dsn_display(nuke_dsn)}")
    print(f"  Schema:         {schema}")
    print(f"  Modules:        {len(ordered)}")
    for spec in ordered:
        print(f"    - {spec.name} {spec.version_str}")
    print()

    _confirm_nuke(dsn=dsn, schema=schema, yes=args.yes)

    _wipe_schema(nuke_dsn, schema)

    print("Reinstalling modules…")
    results = _execute_db_install(dsn, ordered)
    _print_install_results(ordered, results)


def _run_db_status(args: argparse.Namespace) -> None:
    """Compare ``ir_module`` rows to discovered manifests."""
    from .database import create_database_from_dsn, normalize_dsn

    dsn = _require_dsn()
    roots = _resolve_module_roots(args)
    specs = loader.discover(roots)
    ordered = loader.resolve_order(specs)
    with create_database_from_dsn(normalize_dsn(dsn)).connect() as conn:
        installed = _read_installed_versions(conn)
    for spec in ordered:
        db_ver = installed.get(spec.name)
        if db_ver is None:
            state = "not installed"
        elif db_ver == spec.version_str:
            state = "ok"
        else:
            state = f"upgrade ({db_ver} → {spec.version_str})"
        print(f"  {spec.name:20} {spec.version_str:12}  {state}")


# ---------------------------------------------------------------------------
# Artisan-style module commands (pyvelm make:module, etc.)
# ---------------------------------------------------------------------------

_BUILTIN_SUBCOMMANDS = frozenset({
    "cron", "db", "init", "new", "list", "help",
})


def bootstrap_command_env(ctx) -> None:
    """Load registry + DB env for commands with ``requires_db=True``."""
    from .database import create_database_from_dsn, normalize_dsn
    from .env import Environment
    from .registry import Registry

    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN not set (required for this command)")
    specs = loader.discover(ctx.roots)
    ordered = loader.resolve_order(specs)
    registry = Registry()
    for spec in ordered:
        loader._load_models(spec, registry)
    db = create_database_from_dsn(normalize_dsn(dsn))
    conn = db.open_connection()
    ctx.registry = registry
    ctx.env = Environment(conn, registry=registry)


def _command_registry(roots: list[Path] | None = None):
    roots = roots or _default_module_roots()
    return loader.discover_commands(roots)


# Built-in ``pyvelm`` subcommands (argparse). Listed by ``pyvelm list`` alongside
# Artisan-style module commands from :func:`loader.discover_commands`.
_CORE_CLI_COMMANDS: list[tuple[str, str]] = [
    ("cron", "Run the background cron + mail-dispatcher worker."),
    ("init <name>", "Scaffold a new pyvelm project."),
    ("new <module>", "Scaffold a new module inside the current project."),
    ("db diff <module>", "Print schema delta for a module (no writes)."),
    ("db autogen <module>", "Write migration file + bump VERSION."),
    ("db migrate-fresh", "Migrate with pre-flight plan + prod confirmation."),
    ("db status", "Show ir_module versions vs on-disk manifests."),
    ("db nuke", "DEV ONLY — drop schema + reinstall every module."),
    ("list", "List core and module commands."),
    ("help <command>", "Show help for a module command (e.g. make:module)."),
]


def _print_command_section(title: str, commands: list[tuple[str, str]]) -> None:
    """Print a aligned name + description block under *title*."""
    if not commands:
        return
    print(title)
    width = max(len(name) for name, _ in commands)
    for name, desc in commands:
        text = (desc or "").strip()
        pad = " " * (width - len(name) + 2)
        print(f"  {name}{pad}{text}")
    print()


def _run_command_list(_args: argparse.Namespace | None = None) -> None:
    print("Available commands:\n")
    _print_command_section("Core:", list(_CORE_CLI_COMMANDS))
    reg = _command_registry()
    module_cmds = [(cmd.name, cmd.description or "") for cmd in reg.all()]
    if module_cmds:
        _print_command_section("Module:", module_cmds)
    else:
        print("Module: (none registered)\n")


def _run_command_help(args: argparse.Namespace) -> None:
    from .console import parse_signature, _build_argparse

    reg = _command_registry()
    name = args.command_name
    cmd = reg.get(name)
    if cmd is None:
        sys.exit(f"Unknown command {name!r}. Run `pyvelm list` to see commands.")
    _build_argparse(cmd).print_help()


def _try_dispatch_module_command(argv: list[str]) -> bool:
    """Run ``pyvelm make:foo ...`` if registered. Returns True if handled."""
    if not argv:
        return False
    name = argv[0]
    if name in _BUILTIN_SUBCOMMANDS:
        return False
    reg = _command_registry()
    if name not in reg.names():
        return False
    from .console import CommandContext

    ctx = CommandContext(roots=_default_module_roots())
    try:
        code = reg.run(name, argv[1:], ctx=ctx)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        sys.exit(str(exc))
    sys.exit(code)
    return True  # pragma: no cover


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyvelm",
        description=(
            "pyvelm command-line tool. Built-ins: cron, init, new, db, "
            "list, help. Console commands: pyvelm migrate, serve, "
            "make:module, etc. (see `pyvelm list`)."
        ),
    )
    subs = parser.add_subparsers(dest="command", required=False, metavar="<command>")
    _add_db_subcommand(subs)

    lst = subs.add_parser(
        "list",
        help="List core CLI commands and Artisan-style module commands.",
    )
    lst.set_defaults(func=_run_command_list)

    hlp = subs.add_parser(
        "help",
        help="Show help for a module command (e.g. pyvelm help make:module).",
    )
    hlp.add_argument("command_name", help="Command name (e.g. make:module).")
    hlp.set_defaults(func=_run_command_help)

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


def _load_dotenv() -> None:
    """Load ``.env`` from cwd or any parent (same search as ``find_dotenv``)."""
    from dotenv import find_dotenv, load_dotenv

    path = find_dotenv(usecwd=True)
    if path:
        load_dotenv(path)


def main() -> None:
    """``pyvelm`` entry point — subcommand dispatch."""
    _load_dotenv()
    argv = sys.argv[1:]
    if argv and _try_dispatch_module_command(argv):
        return
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        print("\nMore commands (run `pyvelm list` for the full list):")
        reg = _command_registry()
        for cmd in reg.all()[:8]:
            print(f"  {cmd.name:<20} {cmd.description or ''}")
        if len(reg.all()) > 8:
            print(f"  … and {len(reg.all()) - 8} more")
        sys.exit(0)
    args.func(args)


def cron_main() -> None:
    """``pyvelm-cron`` legacy entry point.

    Same shape as the old ``pyvelm-cron`` command (``--interval``,
    ``--roots``), still works without subcommand prefix. Kept so
    existing docker-compose files and systemd units survive a
    pyvelm upgrade without edits.
    """
    _load_dotenv()
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
