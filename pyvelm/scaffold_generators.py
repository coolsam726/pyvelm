"""Code generators for ``pyvelm make:model``, ``make:view``, ``make:menu``.

Shared by console commands and ``pyvelm db autogen --with-views``.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .scaffolder import _substitute, find_modules_root, valid_name

if TYPE_CHECKING:
    from .env import Environment
    from .loader import ModuleSpec
    from .registry import Registry

_SCaffold_ROOT = Path(__file__).parent / "scaffolds"


def resolve_module(
    module: str | None,
    *,
    modules_root: Path | None = None,
) -> tuple[str, Path, Path]:
    """Return ``(module_name, modules_root, module_path)`` or raise ValueError."""
    root = modules_root or find_modules_root()
    if root is None:
        raise ValueError(
            "Couldn't find pyvelm.toml — run from a project root or "
            "pass --modules-root=."
        )
    mod_name = module
    if mod_name is None:
        cwd = Path.cwd().resolve()
        try:
            rel = cwd.relative_to(root.resolve())
            if rel.parts:
                mod_name = rel.parts[0]
        except ValueError:
            pass
    if not mod_name or not valid_name(mod_name):
        raise ValueError(
            "Pass --module=<name> or run from inside app/modules/<module>/."
        )
    mod_path = root / mod_name
    if not (mod_path / "__pyvelm__.py").is_file():
        raise ValueError(f"Module not found: {mod_path}")
    return mod_name, root, mod_path


def model_stem(model_name: str, module_name: str) -> str:
    """``inventory.product`` → ``product``; validates module prefix."""
    if "." not in model_name:
        model_name = f"{module_name}.{model_name}"
    prefix, stem = model_name.split(".", 1)
    if prefix != module_name:
        raise ValueError(
            f"Model {model_name!r} must start with module name {module_name!r} "
            f"(e.g. {module_name}.product)."
        )
    if not valid_name(stem.replace(".", "_")):
        raise ValueError(f"Invalid model suffix {stem!r}.")
    return stem


def class_name_from_stem(stem: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[._]", stem) if part)


def _read_template(rel_path: str, variables: dict[str, str]) -> str:
    path = _SCaffold_ROOT / rel_path
    if not path.is_file():
        raise FileNotFoundError(f"Missing scaffold template: {path}")
    return _substitute(path.read_text(encoding="utf-8"), variables)


def append_manifest_data(manifest_path: Path, entry: str) -> bool:
    """Append a path to ``DATA`` if missing. Returns True when changed."""
    text = manifest_path.read_text(encoding="utf-8")
    quoted = f'"{entry}"'
    if quoted in text:
        return False
    match = re.search(
        r"DATA:\s*list\[str\]\s*=\s*\[(.*?)\]",
        text,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError(f"Could not find DATA list in {manifest_path}")
    inner = match.group(1).strip()
    if inner:
        insertion = f"{match.group(1).rstrip()}\n    {quoted},\n"
    else:
        insertion = f"\n    {quoted},\n"
    new_text = text[: match.start(1)] + insertion + text[match.end(1) :]
    manifest_path.write_text(new_text, encoding="utf-8")
    return True


def append_models_init(init_path: Path, stem: str) -> bool:
    """Add ``from . import <stem>`` if missing."""
    line = f"from . import {stem}  # noqa: F401"
    text = init_path.read_text(encoding="utf-8")
    if stem in text:
        return False
    if not text.strip():
        init_path.write_text(f'"""Models package."""\n\n{line}\n', encoding="utf-8")
        return True
    if not text.endswith("\n"):
        text += "\n"
    init_path.write_text(text + f"{line}\n", encoding="utf-8")
    return True


def _views_for_model(spec: ModuleSpec) -> set[str]:
    """Models that already have a list view in this module's data files."""
    from . import loader

    loader._load_data_files(spec)
    return {
        v["model"]
        for v in spec.views
        if v.get("view_type") == "list" and v.get("model")
    }


def model_has_list_view(spec: ModuleSpec, model_name: str) -> bool:
    return model_name in _views_for_model(spec)


def list_view_files(module_path: Path) -> list[Path]:
    views_dir = module_path / "views"
    if not views_dir.is_dir():
        return []
    return sorted(views_dir.glob("*.py"))


def generate_model(
    module_path: Path,
    module_name: str,
    model_name: str,
    *,
    force: bool = False,
    vellum: bool = False,
) -> Path:
    """Write ``models/<stem>.py`` and update ``models/__init__.py``."""
    stem = model_stem(model_name, module_name)
    model_name = f"{module_name}.{stem}"
    target = module_path / "models" / f"{stem}.py"
    if target.exists() and not force:
        raise FileExistsError(str(target))
    (module_path / "models").mkdir(exist_ok=True)
    template = (
        "snippets/model_vellum.py.template" if vellum else "snippets/model.py.template"
    )
    body = _read_template(
        template,
        {
            "module": module_name,
            "model": model_name,
            "class_name": class_name_from_stem(stem),
        },
    )
    target.write_text(body, encoding="utf-8")
    append_models_init(module_path / "models" / "__init__.py", stem)
    return target


def _timestamp_field_names(cls) -> list[str]:
    """Timestamp columns to show on list/form views when enabled."""
    try:
        from pyvelm.vellum.timestamps import (
            created_at_column,
            updated_at_column,
            uses_timestamps,
        )
    except ImportError:
        return []
    if not uses_timestamps(cls):
        return []
    names: list[str] = []
    for col in (created_at_column(cls), updated_at_column(cls)):
        if col and col in cls._fields:
            names.append(col)
    return names


def _field_refs_for_model(registry: Registry | None, model_name: str) -> tuple[list[str], list[str], list[str]]:
    """Pick stored fields for starter list/form views.

    Returns ``(list_fields, form_fields, form_timestamp_fields)``.
    """
    if registry is None or model_name not in registry:
        return ["name"], ["name"], []
    from .fields import Many2many, One2many

    cls = registry[model_name]
    skip = {
        "id",
        "create_uid",
        "write_uid",
        "create_date",
        "write_date",
        "created_at",
        "updated_at",
    }
    list_names: list[str] = []
    form_names: list[str] = []
    for fname, field in cls._fields.items():
        if fname in skip or not field.is_stored:
            continue
        if isinstance(field, (One2many, Many2many)):
            continue
        list_names.append(fname)
        form_names.append(fname)
        if len(list_names) >= 8:
            break
    if "name" in cls._fields and "name" not in list_names:
        list_names.insert(0, "name")
        form_names.insert(0, "name")
    if not list_names:
        list_names = form_names = ["name"] if "name" in cls._fields else ["id"]
    timestamp_names = _timestamp_field_names(cls)
    for ts in timestamp_names:
        if ts not in list_names:
            list_names.append(ts)
    return list_names, form_names, timestamp_names


def _format_field_list(names: list[str]) -> str:
    lines = [f'            "{n}",' for n in names]
    return "\n".join(lines)


def _format_timestamp_section(timestamp_fields: list[str]) -> str:
    if not timestamp_fields:
        return ""
    body = _format_field_list(timestamp_fields)
    return (
        "            section(\"metadata\", \"Record info\", [\n"
        f"{body}\n"
        "            ]),\n"
    )


def generate_views(
    module_path: Path,
    module_name: str,
    model_name: str,
    *,
    registry: Registry | None = None,
    force: bool = False,
) -> Path:
    """Write ``views/<stem>.py`` and add to manifest ``DATA``."""
    stem = model_stem(model_name, module_name)
    model_name = f"{module_name}.{stem}"
    target = module_path / "views" / f"{stem}.py"
    if target.exists() and not force:
        raise FileExistsError(str(target))
    (module_path / "views").mkdir(exist_ok=True)
    list_fields, form_fields, timestamp_fields = _field_refs_for_model(registry, model_name)
    body = _read_template(
        "snippets/view.py.template",
        {
            "module": module_name,
            "model": model_name,
            "stem": stem,
            "list_fields": _format_field_list(list_fields),
            "form_fields": _format_field_list(form_fields),
            "timestamp_section": _format_timestamp_section(timestamp_fields),
            "title": stem.replace("_", " ").title(),
        },
    )
    target.write_text(body, encoding="utf-8")
    append_manifest_data(
        module_path / "__pyvelm__.py",
        f"views/{stem}.py",
    )
    return target


def generate_menu(
    module_path: Path,
    module_name: str,
    *,
    view_name: str,
    group: str = "main",
    group_label: str | None = None,
    item_name: str | None = None,
    item_label: str | None = None,
    sequence: int = 60,
    force: bool = False,
    append: bool = False,
) -> Path:
    """Create or extend ``views/menu.py``."""
    menu_path = module_path / "views" / "menu.py"
    group_label = group_label or module_name.replace("_", " ").title()
    item_name = item_name or f"{group}.{view_name.split('.')[-1]}"
    item_label = item_label or view_name.split(".")[-1].replace("_", " ").title()
    item_block = (
        f'    m.item("{item_name}", "{item_label}", '
        f'parent="{group}", view="{view_name}", sequence=10),\n'
    )
    if menu_path.exists():
        if not append and not force:
            raise FileExistsError(
                f"{menu_path} already exists — pass --append or --force."
            )
        text = menu_path.read_text(encoding="utf-8")
        if item_block.strip() in text:
            return menu_path
        idx = text.rfind("]")
        if idx == -1:
            raise ValueError(f"No MENUS list in {menu_path}")
        text = text[:idx] + item_block + text[idx:]
        menu_path.write_text(text, encoding="utf-8")
        return menu_path
    (module_path / "views").mkdir(exist_ok=True)
    body = _read_template(
        "snippets/menu.py.template",
        {
            "module": module_name,
            "group": group,
            "group_label": group_label,
            "item_name": item_name,
            "item_label": item_label,
            "view_name": view_name,
            "sequence": str(sequence),
        },
    )
    menu_path.write_text(body, encoding="utf-8")
    append_manifest_data(module_path / "__pyvelm__.py", "views/menu.py")
    return menu_path


def models_affected_by_diff(
    env: Environment,
    module: str,
    diff: Any,
) -> list[str]:
    """Model names touched by a schema diff for this module."""
    reg = env.registry
    tables: set[str] = set()
    for table, _ddl in diff.new_tables:
        tables.add(table)
    for table, _col, _stmt, _req in diff.new_columns:
        tables.add(table)
    models: set[str] = set()
    for model_name, cls in reg._models.items():
        if reg._model_module.get(model_name) != module:
            continue
        if cls._table in tables:
            models.add(model_name)
    return sorted(models)


def ensure_views_for_models(
    spec: ModuleSpec,
    model_names: list[str],
    *,
    registry: Registry | None = None,
    force: bool = False,
) -> list[Path]:
    """Create list+form views for models that do not have one yet."""
    if spec.package_path is None:
        return []
    created: list[Path] = []
    for model_name in model_names:
        if model_has_list_view(spec, model_name):
            continue
        path = generate_views(
            spec.package_path,
            spec.name,
            model_name,
            registry=registry,
            force=force,
        )
        created.append(path)
    return created
