"""``pyvelm make:module`` — scaffold a new addon (alias for ``pyvelm new``)."""

import sys
from pathlib import Path

from pyvelm.console import Command
from pyvelm.scaffolder import (
    echo_next_steps_for_new,
    find_modules_root,
    materialise,
    valid_name,
)


class MakeModuleCommand(Command):
    name = "make:module"
    description = "Scaffold a new module in the current project"
    signature = (
        "make:module {name : Module name (directory + NAME in manifest)} "
        "{--modules-root= : Path to modules directory (default: pyvelm.toml)}"
    )

    def handle(self, name: str, modules_root: str | None = None) -> int:
        if not valid_name(name):
            self.error(
                f"Invalid module name {name!r}. Use letters, digits, "
                "underscores; must start with a letter."
            )
            return 1
        if modules_root is not None and modules_root != "":
            root = Path(modules_root).resolve()
        else:
            root = find_modules_root()
            if root is None:
                self.error(
                    "Couldn't find pyvelm.toml in cwd or any parent. "
                    "Run from a project root or pass --modules-root=app/modules."
                )
                return 1
        root.mkdir(parents=True, exist_ok=True)
        target = root / name
        try:
            materialise("module", target, variables={"name": name})
        except FileExistsError:
            self.error(f"{target} already exists.")
            return 1
        echo_next_steps_for_new(name, root)
        return 0
