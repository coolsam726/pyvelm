"""``pyvelm make:stubs`` — generate IDE typing stubs for models and views."""

from pathlib import Path

from pyvelm.console import Command
from pyvelm.scaffold_generators import _load_dotenv_for_scaffold
from pyvelm.scaffolder import find_project_root
from pyvelm.stub_generators import (
    default_stubs_dir,
    generate_stubs,
    write_pyrightconfig,
)


class MakeStubsCommand(Command):
    name = "make:stubs"
    description = "Generate Pyright/Pylance stubs for model and view names"
    signature = (
        "make:stubs "
        "{--output= : Output directory (default: <project>/.pyvelm/typing)} "
        "{--modules-root= : Addon roots (default: pyvelm.toml + PYVELM_MODULE_ROOTS)} "
        "{--app-only : Omit bundled framework models and views}"
    )
    requires_db = False

    def handle(
        self,
        output: str | None = None,
        modules_root: str | None = None,
        app_only: bool = False,
    ) -> int:
        _load_dotenv_for_scaffold()
        project = find_project_root()
        if output:
            out_dir = Path(output).resolve()
        elif project is not None:
            out_dir = default_stubs_dir(project)
        else:
            out_dir = default_stubs_dir(Path.cwd())
            self.warn(
                "No pyvelm.toml found — writing stubs to ./.pyvelm/typing "
                "(pass --output= to override)."
            )

        root_path = Path(modules_root).resolve() if modules_root else None
        try:
            written, index = generate_stubs(
                out_dir,
                modules_root=root_path,
                include_bundled=not app_only,
            )
        except Exception as exc:  # noqa: BLE001
            self.error(str(exc))
            return 1

        self.info(f"Wrote typing stubs to {written}")
        self.line(
            f"  {len(index.models)} models, "
            f"{len(index.qualified_views)} qualified views"
        )
        config_root = project or Path.cwd()
        if write_pyrightconfig(config_root, stubs_dir=written):
            self.info(f"Updated {config_root / 'pyrightconfig.json'}")
        return 0
