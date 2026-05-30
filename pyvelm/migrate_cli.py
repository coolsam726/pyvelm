"""Database migrate / reset helpers for console commands and ``pyvelm db …`` shims."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

from . import loader
from .env import Environment
from .registry import Registry


def require_dsn() -> str:
    dsn = os.environ.get("PYVELM_DSN")
    if not dsn:
        sys.exit("PYVELM_DSN not set")
    return dsn


def dsn_display(dsn: str) -> str:
    """Return a DSN safe to print (password redacted)."""
    try:
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(dsn)
        if parsed.scheme and parsed.hostname:
            netloc = parsed.hostname
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            if parsed.username:
                netloc = f"{parsed.username}:***@{netloc}"
            path = parsed.path or ""
            return urlunparse(
                (parsed.scheme, netloc, path, parsed.params, "", "")
            )
    except Exception:
        pass
    return "<dsn>"


def read_installed_versions(conn) -> dict[str, str]:
    installed: dict[str, str] = {}
    try:
        rows = conn.execute(
            'SELECT "name", "version" FROM "ir_module"'
        ).fetchall()
        installed = {str(r[0]): str(r[1]) for r in rows}
    except Exception:
        pass
    return installed


def module_action(installed: dict[str, str], spec: loader.ModuleSpec) -> str:
    db_ver = installed.get(spec.name)
    disk = spec.version_str
    if db_ver is None:
        return "install"
    if db_ver == disk:
        return "sync"
    return f"upgrade ({db_ver} → {disk})"


def ordered_specs_for_install(
    roots: list[Path], only_module: str | None
) -> list[loader.ModuleSpec]:
    specs = loader.discover(roots)
    if only_module is not None:
        if only_module not in specs:
            sys.exit(
                f"Module {only_module!r} not discovered. "
                f"Known: {sorted(specs)}"
            )
        needed: set[str] = set()

        def _add(name: str) -> None:
            if name in needed:
                return
            if name not in specs:
                sys.exit(
                    f"Module {only_module!r} depends on {name!r}, "
                    f"which is not in the discovered set."
                )
            needed.add(name)
            for dep in specs[name].depends:
                _add(dep)

        _add(only_module)
        ordered = loader.resolve_order(specs)
        return [s for s in ordered if s.name in needed]
    return loader.resolve_order(specs)


def resolve_migrate_specs(
    roots: list[Path],
    dsn: str,
    *,
    only_module: str | None = None,
    install_all: bool = False,
    fresh_after_wipe: bool = False,
) -> list[loader.ModuleSpec]:
    """Return the topo-ordered specs to install/upgrade on this migrate pass."""
    ordered = ordered_specs_for_install(roots, only_module)
    if only_module is not None or install_all:
        return ordered
    if fresh_after_wipe:
        return [s for s in ordered if s.name in loader.BOOTSTRAP_MODULES]
    with psycopg.connect(dsn, autocommit=True) as conn:
        env = Environment(conn, registry=Registry(), uid=None)
        return loader.specs_to_install(env, ordered, install_all=False)


def execute_db_install(
    dsn: str, to_install: list[loader.ModuleSpec]
) -> list[dict]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        reg = Registry()
        env = Environment(conn, registry=reg)
        for spec in to_install:
            loader._load_models(spec, reg)
        return loader.install(to_install, env)


def print_install_results(
    ordered: list[loader.ModuleSpec], results: list[dict]
) -> None:
    print(f"Migrated {len(ordered)} module(s):")
    for row in results:
        parts = [row["name"]]
        if row.get("schema"):
            parts.append(row["schema"])
        if row.get("views"):
            parts.append(row["views"])
        if row.get("menus"):
            parts.append(row["menus"])
        print("  " + " — ".join(parts))


def print_migrate_plan(
    *,
    dsn: str,
    ordered: list[loader.ModuleSpec],
    installed: dict[str, str],
    production: bool,
) -> None:
    from .runtime import get_runtime_env

    runtime = get_runtime_env()
    print("Migration plan (migrate-fresh)")
    print(f"  PYVELM_ENV:     {runtime}")
    print(f"  Database:       {dsn_display(dsn)}")
    print(f"  Modules:        {len(ordered)}")
    if production:
        print(
            "  Production:     yes — confirmation required "
            "(use --yes for non-interactive CI)"
        )
    print()
    for spec in ordered:
        action = module_action(installed, spec)
        print(f"  {spec.name:20} {spec.version_str:12}  {action}")
    print()


def confirm_migrate_fresh(*, production: bool, yes: bool) -> None:
    if yes:
        if production:
            print(
                "WARNING: --yes skipped production confirmation. "
                "Only use in trusted CI/deploy pipelines.",
                file=sys.stderr,
            )
        return
    if not production:
        return
    print(
        "This will modify the production database (schema, views, menus, "
        "migration scripts for version gaps)."
    )
    try:
        typed = input("Type migrate-fresh to continue: ").strip()
    except EOFError:
        sys.exit("Aborted (non-interactive terminal). Use --yes in CI.")
    if typed != "migrate-fresh":
        sys.exit("Aborted.")


def drop_schema_contents(conn, schema: str) -> None:
    from psycopg import sql

    qschema = sql.Identifier(schema)
    conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(qschema))
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(qschema))
    conn.execute(sql.SQL("GRANT ALL ON SCHEMA {} TO CURRENT_USER").format(qschema))
    conn.execute(sql.SQL("GRANT ALL ON SCHEMA {} TO PUBLIC").format(qschema))


def guard_destructive_schema_command(*, label: str) -> None:
    from .runtime import is_production

    if is_production() and not os.environ.get("PYVELM_ALLOW_DB_NUKE"):
        sys.exit(
            f"pyvelm {label} is disabled in production "
            "(PYVELM_ENV=production). Set PYVELM_ALLOW_DB_NUKE=1 only for "
            "trusted demo/staging reset pipelines, or use development."
        )


def confirm_destructive_phrase(*, phrase: str, yes: bool, preamble: str) -> None:
    if yes:
        return
    print(preamble)
    try:
        typed = input(f"Type {phrase} to continue: ").strip()
    except EOFError:
        sys.exit("Aborted (non-interactive terminal). Pass --yes in CI.")
    if typed != phrase:
        sys.exit("Aborted.")


def wipe_schema(dsn: str, schema: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        print(f"Dropping schema {schema!r}…")
        drop_schema_contents(conn, schema)
        print("Schema dropped + recreated.\n")


def run_migrate(
    roots: list[Path],
    *,
    install_all: bool = False,
    only_module: str | None = None,
) -> None:
    """Install or upgrade modules — same policy as app boot by default."""
    dsn = require_dsn()
    to_install = resolve_migrate_specs(
        roots,
        dsn,
        only_module=only_module,
        install_all=install_all,
    )
    results = execute_db_install(dsn, to_install)
    print_install_results(to_install, results)


def run_db_migrate_fresh(
    roots: list[Path],
    *,
    install_all: bool = False,
    only_module: str | None = None,
    yes: bool = False,
    dry_run: bool = False,
) -> None:
    """``pyvelm db migrate-fresh`` — plan + optional production confirmation."""
    from .runtime import is_production

    dsn = require_dsn()
    to_install = resolve_migrate_specs(
        roots,
        dsn,
        only_module=only_module,
        install_all=install_all,
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        installed = read_installed_versions(conn)
    production = is_production()
    print_migrate_plan(
        dsn=dsn,
        ordered=to_install,
        installed=installed,
        production=production,
    )
    if dry_run:
        print("Dry run — no changes applied.")
        return
    confirm_migrate_fresh(production=production, yes=yes)
    results = execute_db_install(dsn, to_install)
    print_install_results(to_install, results)


def run_migrate_reset(
    roots: list[Path],
    *,
    schema: str = "public",
    yes: bool = False,
) -> None:
    """Drop the schema and leave an empty database."""
    from .runtime import get_runtime_env

    _ = roots  # reserved for future per-project schema policy
    guard_destructive_schema_command(label="migrate:reset")
    dsn = require_dsn()

    print("migrate:reset")
    print(f"  PYVELM_ENV:     {get_runtime_env()}")
    print(f"  Database:       {dsn_display(dsn)}")
    print(f"  Schema:         {schema}")
    print()

    confirm_destructive_phrase(
        phrase="migrate:reset",
        yes=yes,
        preamble=(
            f"This will DROP every table, view, sequence, and function in "
            f"schema {schema!r} of {dsn_display(dsn)}.\n"
            "All data is lost. There is no undo. No modules will be reinstalled."
        ),
    )
    wipe_schema(dsn, schema)
    print("Schema reset complete.")


def run_migrate_fresh(
    roots: list[Path],
    *,
    schema: str = "public",
    yes: bool = False,
    install_all: bool = False,
    only_module: str | None = None,
) -> None:
    """Drop the schema, then migrate (bootstrap by default after wipe)."""
    from .runtime import get_runtime_env

    guard_destructive_schema_command(label="migrate:fresh")
    dsn = require_dsn()
    use_bootstrap_after_wipe = not install_all and only_module is None
    to_install = resolve_migrate_specs(
        roots,
        dsn,
        only_module=only_module,
        install_all=install_all,
        fresh_after_wipe=use_bootstrap_after_wipe,
    )

    print("migrate:fresh")
    print(f"  PYVELM_ENV:     {get_runtime_env()}")
    print(f"  Database:       {dsn_display(dsn)}")
    print(f"  Schema:         {schema}")
    print(f"  Then migrate:   {len(to_install)} module(s)")
    for spec in to_install:
        print(f"    - {spec.name} {spec.version_str}")
    print()

    confirm_destructive_phrase(
        phrase="migrate:fresh",
        yes=yes,
        preamble=(
            f"This will DROP schema {schema!r} on {dsn_display(dsn)}, "
            "then run pyvelm migrate on an empty database "
            "(all bundled pyvelm modules by default; pass --all or --module "
            "to include external addons or limit scope)."
        ),
    )
    wipe_schema(dsn, schema)
    print("Running migrate…")
    results = execute_db_install(dsn, to_install)
    print_install_results(to_install, results)
