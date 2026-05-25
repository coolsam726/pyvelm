"""``pyvelm make:view`` — scaffold list + form views for a model."""

from pathlib import Path

from pyvelm.console import Command
from pyvelm.scaffold_generators import (
    _load_dotenv_for_scaffold,
    generate_views,
    load_registry_for_module,
    resolve_module,
)


class MakeViewCommand(Command):
    name = "make:view"
    description = "Create list + form views for a model"
    signature = (
        "make:view {model : Model technical name (e.g. vellum.demo.comment)} "
        "{--module= : Owning module (inferred from model when omitted)} "
        "{--modules-root= : Addon roots directory (default: pyvelm.toml or .env)} "
        "{--minimal : Stub with name only (default: build from model fields)} "
        "{--force : Overwrite an existing views file}"
    )
    requires_db = False

    def handle(
        self,
        model: str,
        module: str | None = None,
        modules_root: str | None = None,
        minimal: bool = False,
        force: bool = False,
    ) -> int:
        from_model = not minimal
        _load_dotenv_for_scaffold()
        try:
            root_path = Path(modules_root).resolve() if modules_root else None
            mod_name, _root, mod_path = resolve_module(
                module,
                model_name=model,
                modules_root=root_path,
            )
            registry = (
                load_registry_for_module(mod_name) if from_model else None
            )
            path = generate_views(
                mod_path,
                mod_name,
                model,
                registry=registry,
                force=force,
                from_model=from_model,
            )
        except (ValueError, FileExistsError) as exc:
            self.error(str(exc))
            return 1
        mode = "from model fields" if from_model else "minimal stub"
        self.info(f"Created {path} ({mode})")
        from pyvelm.scaffold_generators import normalize_model_for_views

        _f, view_stem, _ = normalize_model_for_views(
            model, mod_name, registry=registry
        )
        self.line(f"Next: pyvelm make:menu --view={view_stem}.list --module={mod_name}")
        return 0
