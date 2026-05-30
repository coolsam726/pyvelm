"""``pyvelm migrate``, ``migrate:fresh``, and ``migrate:reset`` console commands."""

from __future__ import annotations

from pyvelm.console import Command
from pyvelm.migrate_cli import run_migrate, run_migrate_fresh, run_migrate_reset


class MigrateCommand(Command):
    name = "migrate"
    description = (
        "Install or upgrade installed modules (bootstrap on a fresh DB)"
    )
    signature = (
        "migrate "
        "{--all : Install/upgrade every discovered module} "
        "{--module= : Limit to one module and its dependencies}"
    )

    def handle(self, all: bool = False, module: str | None = None) -> int:
        only_module = (module or "").strip() or None
        run_migrate(
            self._ctx.roots,
            install_all=all,
            only_module=only_module,
        )
        return 0


class MigrateFreshCommand(Command):
    name = "migrate:fresh"
    description = (
        "DEV ONLY — drop schema, then migrate (bundled modules by default)"
    )
    signature = (
        "migrate:fresh "
        "{--all : After reset, install every discovered module} "
        "{--module= : After reset, limit to one module and dependencies} "
        "{--yes : Skip typed confirmation (CI / scripts)} "
        "{--schema=public : Postgres schema to drop and recreate}"
    )

    def handle(
        self,
        all: bool = False,
        module: str | None = None,
        yes: bool = False,
        schema: str = "public",
    ) -> int:
        only_module = (module or "").strip() or None
        run_migrate_fresh(
            self._ctx.roots,
            schema=(schema or "public").strip() or "public",
            yes=yes,
            install_all=all,
            only_module=only_module,
        )
        return 0


class MigrateResetCommand(Command):
    name = "migrate:reset"
    description = "DEV ONLY — drop schema (empty database, no reinstall)"
    signature = (
        "migrate:reset "
        "{--yes : Skip typed confirmation (CI / scripts)} "
        "{--schema=public : Postgres schema to drop and recreate}"
    )

    def handle(self, yes: bool = False, schema: str = "public") -> int:
        run_migrate_reset(
            self._ctx.roots,
            schema=(schema or "public").strip() or "public",
            yes=yes,
        )
        return 0
