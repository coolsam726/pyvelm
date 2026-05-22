"""``pyvelm make:command`` — scaffold a new Command class in a module."""

import re
from pathlib import Path

from pyvelm.console import Command
from pyvelm.scaffolder import find_modules_root, valid_name


def _class_name(command_name: str) -> str:
    """``reports:sync`` → ``ReportsSyncCommand``."""
    parts = re.split(r"[:._-]+", command_name)
    return "".join(p.capitalize() for p in parts if p) + "Command"


class MakeCommandCommand(Command):
    name = "make:command"
    description = "Create a new Artisan-style command class in a module"
    signature = (
        "make:command {name : Command name (e.g. reports:sync)} "
        "{--module= : Owning module (default: infer from cwd)} "
        "{--force : Overwrite an existing file}"
    )

    def handle(
        self,
        name: str,
        module: str | None = None,
        force: bool = False,
    ) -> int:
        if ":" not in name:
            self.error(
                "Command name should use a namespace, e.g. reports:sync "
                "or inventory:import"
            )
            return 1
        mod_name = module
        modules_root = find_modules_root()
        if modules_root is None:
            self.error("Couldn't find pyvelm.toml — run from a project root.")
            return 1
        if mod_name is None:
            cwd = Path.cwd().resolve()
            try:
                rel = cwd.relative_to(modules_root.resolve())
                if rel.parts:
                    mod_name = rel.parts[0]
            except ValueError:
                pass
        if not mod_name or not valid_name(mod_name):
            self.error(
                "Pass --module=<name> (e.g. inventory) or run from "
                "inside app/modules/<module>/."
            )
            return 1
        mod_path = modules_root / mod_name
        if not (mod_path / "__pyvelm__.py").is_file():
            self.error(f"Module not found: {mod_path}")
            return 1
        cmd_dir = mod_path / "commands"
        cmd_dir.mkdir(exist_ok=True)
        stem = name.replace(":", "_").replace("-", "_")
        target = cmd_dir / f"{stem}.py"
        if target.exists() and not force:
            self.error(f"{target} already exists (use --force to overwrite).")
            return 1
        cls = _class_name(name)
        body = _COMMAND_TEMPLATE.format(
            class_name=cls,
            command_name=name,
            description=f"TODO: describe {name}",
        )
        target.write_text(body, encoding="utf-8")
        self.info(f"Created {target}")
        self.line(f"Run: pyvelm {name}")
        return 0


_COMMAND_TEMPLATE = '''\
"""``pyvelm {command_name}``."""

from pyvelm.console import Command


class {class_name}(Command):
    name = "{command_name}"
    description = "{description}"
    signature = "{command_name}"
    # requires_db = True  # uncomment if the command needs PYVELM_DSN

    def handle(self) -> int:
        self.info("Not implemented yet.")
        return 0
'''
