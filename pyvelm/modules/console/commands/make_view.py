"""``pyvelm make:view`` — scaffold list + form views for a model."""

from pyvelm.console import Command
from pyvelm.scaffold_generators import generate_views, resolve_module


class MakeViewCommand(Command):
    name = "make:view"
    description = "Create list + form views for a model"
    signature = (
        "make:view {model : Model technical name (e.g. inventory.product)} "
        "{--module= : Owning module} "
        "{--force : Overwrite an existing views file}"
    )
    requires_db = False

    def _load_registry(self, mod_name: str):
        from pyvelm import loader
        from pyvelm.registry import Registry
        from pyvelm.cli import _default_module_roots

        specs = loader.discover(_default_module_roots())
        if mod_name not in specs:
            return None
        registry = Registry()
        for spec in loader.resolve_order(specs):
            if spec.name == mod_name:
                loader._load_models(spec, registry)
                return registry
        return None

    def handle(self, model: str, module: str | None = None, force: bool = False) -> int:
        try:
            mod_name, _root, mod_path = resolve_module(module)
            registry = self._load_registry(mod_name)
            path = generate_views(
                mod_path, mod_name, model, registry=registry, force=force,
            )
        except (ValueError, FileExistsError) as exc:
            self.error(str(exc))
            return 1
        self.info(f"Created {path}")
        self.line(f"Next: pyvelm make:menu --view={path.stem}.list --module={mod_name}")
        return 0
