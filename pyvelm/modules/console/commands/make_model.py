"""``pyvelm make:model`` — scaffold a model file."""

from pyvelm.console import Command
from pyvelm.scaffold_generators import generate_model, resolve_module


class MakeModelCommand(Command):
    name = "make:model"
    description = "Create a model class under a module's models/ package"
    signature = (
        "make:model {model : Technical name (e.g. product or inventory.product)} "
        "{--module= : Owning module} "
        "{--vellum : Scaffold with Vellum mixin and _fillable} "
        "{--force : Overwrite an existing file}"
    )

    def handle(
        self,
        model: str,
        module: str | None = None,
        vellum: bool = False,
        force: bool = False,
    ) -> int:
        try:
            mod_name, _root, mod_path = resolve_module(module)
            path = generate_model(
                mod_path, mod_name, model, force=force, vellum=vellum
            )
        except (ValueError, FileExistsError) as exc:
            self.error(str(exc))
            return 1
        self.info(f"Created {path}")
        self.line(f"Next: pyvelm make:view {model} --module={mod_name}")
        self.line(f"       pyvelm db autogen {mod_name} --with-views")
        return 0
