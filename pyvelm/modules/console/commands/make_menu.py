"""``pyvelm make:menu`` — scaffold or extend sidebar menu entries."""

from pyvelm.console import Command
from pyvelm.scaffold_generators import generate_menu, resolve_module


class MakeMenuCommand(Command):
    name = "make:menu"
    description = "Create or extend views/menu.py for a list view"
    signature = (
        "make:menu {--view= : List view name (e.g. product.list)} "
        "{--module= : Owning module} "
        "{--group=main : Sidebar group name} "
        "{--group-label= : Group label (default: module title)} "
        "{--item= : Menu item name (default: <group>.<view-stem>)} "
        "{--item-label= : Menu item label} "
        "{--append : Add item to an existing menu.py} "
        "{--force : Replace menu.py}"
    )

    def handle(
        self,
        view: str | None = None,
        module: str | None = None,
        group: str = "main",
        group_label: str | None = None,
        item: str | None = None,
        item_label: str | None = None,
        append: bool = False,
        force: bool = False,
    ) -> int:
        if not view:
            self.error("--view= is required (e.g. --view=product.list).")
            return 1
        try:
            mod_name, _root, mod_path = resolve_module(module)
            path = generate_menu(
                mod_path,
                mod_name,
                view_name=view,
                group=group,
                group_label=group_label,
                item_name=item,
                item_label=item_label,
                force=force,
                append=append,
            )
        except (ValueError, FileExistsError) as exc:
            self.error(str(exc))
            return 1
        self.info(f"Updated {path}")
        return 0
