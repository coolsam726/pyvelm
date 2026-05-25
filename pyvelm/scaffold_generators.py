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


def _load_dotenv_for_scaffold() -> None:
    try:
        from dotenv import find_dotenv, load_dotenv

        path = find_dotenv(usecwd=True)
        if path:
            load_dotenv(path)
    except ImportError:
        pass


def modules_root_candidates(explicit: Path | None = None) -> list[Path]:
    """Directories to scan for addons (``pyvelm.toml``, then ``PYVELM_MODULE_ROOTS``)."""
    if explicit is not None:
        return [explicit.resolve()]
    _load_dotenv_for_scaffold()
    from .cli import _default_module_roots

    out: list[Path] = []
    seen: set[str] = set()
    marker_root = find_modules_root()
    if marker_root is not None:
        key = str(marker_root.resolve())
        out.append(marker_root)
        seen.add(key)
    for r in _default_module_roots():
        resolved = r.resolve()
        if not resolved.is_dir():
            continue
        key = str(resolved)
        if key not in seen:
            out.append(resolved)
            seen.add(key)
    return out


def infer_module_for_model(model_name: str, roots: list[Path]) -> str:
    """Resolve owning module from a technical model name (e.g. ``vellum.demo.comment``)."""
    from . import loader
    from .registry import Registry

    specs = loader.discover(roots)
    registry = Registry()
    for spec in loader.resolve_order(specs):
        loader._load_models(spec, registry)
    if model_name in registry._model_module:
        return registry._model_module[model_name]
    if "." not in model_name:
        matches = [
            m for m in registry._model_module if m.endswith("." + model_name)
        ]
        if len(matches) == 1:
            return registry._model_module[matches[0]]
    raise ValueError(
        f"Model {model_name!r} is not registered under {roots!r}. "
        f"Pass --module=<name> or check PYVELM_MODULE_ROOTS."
    )


def resolve_module(
    module: str | None,
    *,
    model_name: str | None = None,
    modules_root: Path | None = None,
) -> tuple[str, Path, Path]:
    """Return ``(module_name, modules_root, module_path)`` or raise ValueError."""
    candidates = modules_root_candidates(modules_root)
    if not candidates:
        raise ValueError(
            "Couldn't find module roots — add pyvelm.toml, set "
            "PYVELM_MODULE_ROOTS in .env, or pass --modules-root=."
        )
    mod_name = module
    if mod_name is None and model_name:
        mod_name = infer_module_for_model(model_name, candidates)
    if mod_name is None:
        for root in candidates:
            cwd = Path.cwd().resolve()
            try:
                rel = cwd.relative_to(root.resolve())
                if rel.parts and valid_name(rel.parts[0]):
                    mod_name = rel.parts[0]
                    break
            except ValueError:
                continue
    if not mod_name or not valid_name(mod_name):
        raise ValueError(
            "Pass --module=<name>, a full model name (e.g. vellum.demo.comment), "
            "or run from inside <modules-root>/<module>/."
        )
    for root in candidates:
        mod_path = root / mod_name
        if (mod_path / "__pyvelm__.py").is_file():
            return mod_name, root, mod_path
    raise ValueError(
        f"Module {mod_name!r} not found under: "
        + ", ".join(str(r) for r in candidates)
    )


def normalize_model_for_views(
    model_name: str,
    module_name: str,
    registry: Registry | None = None,
) -> tuple[str, str, str]:
    """Return ``(view_file_stem, view_name_stem, technical_model_name)``."""
    technical = model_name
    if registry is not None and model_name in registry:
        technical = model_name
    elif "." not in model_name:
        technical = f"{module_name}.{model_name}"
    if registry is not None and technical not in registry:
        raise ValueError(
            f"Model {technical!r} is not loaded — run from the project root or "
            f"set PYVELM_MODULE_ROOTS."
        )
    view_file_stem = technical.split(".")[-1]
    parts = technical.split(".")
    if parts and parts[0] == module_name:
        rest = parts[1:]
    else:
        rest = parts[1:] if len(parts) > 1 else parts
    view_name_stem = "_".join(rest) if rest else view_file_stem
    if not valid_name(view_file_stem.replace(".", "_")):
        raise ValueError(f"Invalid model suffix {view_file_stem!r}.")
    return view_file_stem, view_name_stem, technical


def model_stem(model_name: str, module_name: str) -> str:
    """Legacy helper — view file stem (last segment of the technical name)."""
    return normalize_model_for_views(model_name, module_name)[0]


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
        raise FileExistsError(
            f"{target} already exists — pass --force to overwrite."
        )
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


def load_registry_for_module(
    module_name: str,
    *,
    modules_root: Path | None = None,
) -> Registry | None:
    """Load the module and its dependencies into a registry for introspection."""
    from . import loader
    from .registry import Registry

    # Always discover all addon roots so ``depends`` (e.g. ``base``) resolve.
    roots = modules_root_candidates(None)
    specs = loader.discover(roots)
    if module_name not in specs:
        return None
    registry = Registry()
    for spec in loader.resolve_order(specs):
        loader._load_models(spec, registry)
        if spec.name == module_name:
            return registry
    return None


_SKIP_VIEW_FIELDS = frozenset(
    {
        "id",
        "display_name",
        "create_uid",
        "write_uid",
        "create_date",
        "write_date",
    }
)


def _field_view_ref(fname: str, field: Any) -> str:
    """One list/form field entry as Python source."""
    from .fields import Boolean, Many2many, One2many

    if isinstance(field, Boolean):
        return f'field("{fname}", widget="toggle")'
    if isinstance(field, (One2many, Many2many)):
        return f'field("{fname}", widget="dialog")'
    return f'"{fname}"'


def _ordered_stored_fields(cls) -> list[tuple[str, Any]]:
    """Stored fields in stable order (``name`` first when present)."""
    from .fields import Many2many, One2many

    scalars: list[tuple[str, Any]] = []
    relations: list[tuple[str, Any]] = []
    timestamps: list[tuple[str, Any]] = []
    ts_names = set(_timestamp_field_names(cls))

    for fname, field in cls._fields.items():
        if fname in _SKIP_VIEW_FIELDS:
            continue
        if isinstance(field, (One2many, Many2many)):
            relations.append((fname, field))
            continue
        if not field.is_stored:
            continue
        if fname in ts_names:
            timestamps.append((fname, field))
        else:
            scalars.append((fname, field))

    def _sort_key(item: tuple[str, Any]) -> tuple[int, str]:
        fname = item[0]
        if fname == "name":
            return (0, fname)
        if fname == "active":
            return (1, fname)
        return (2, fname)

    scalars.sort(key=_sort_key)
    relations.sort(key=lambda x: x[0])
    timestamps.sort(key=lambda x: x[0])
    return scalars + relations + timestamps


def build_view_scaffold_from_model(
    registry: Registry,
    model_name: str,
    *,
    max_list_fields: int = 12,
) -> tuple[list[str], list[tuple[str, str, list[str]]]]:
    """Build list field lines and form sections from a registered model.

    Returns ``(list_lines, [(section_id, title, field_lines), ...])``.
    """
    if model_name not in registry:
        raise ValueError(
            f"Model {model_name!r} is not loaded — check the module name and "
            f"that models are importable."
        )
    from .fields import Many2many, One2many

    cls = registry[model_name]
    ordered = _ordered_stored_fields(cls)
    ts_set = set(_timestamp_field_names(cls))
    scalars = [
        (f, fld)
        for f, fld in ordered
        if f not in ts_set and not isinstance(fld, (One2many, Many2many))
    ]
    relations = [(f, fld) for f, fld in ordered if isinstance(fld, (One2many, Many2many))]
    timestamps = [(f, fld) for f, fld in ordered if f in ts_set]

    list_names: list[str] = []
    for fname, field in scalars:
        if len(list_names) >= max_list_fields:
            break
        list_names.append(_field_view_ref(fname, field))
    for fname, field in relations:
        if len(list_names) >= max_list_fields:
            break
        list_names.append(_field_view_ref(fname, field))
    for fname, field in timestamps:
        if len(list_names) >= max_list_fields:
            break
        if _field_view_ref(fname, field) not in list_names:
            list_names.append(_field_view_ref(fname, field))

    if not list_names:
        if "name" in cls._fields:
            list_names = ['"name"']
        else:
            list_names = ['"id"']

    sections: list[tuple[str, str, list[str]]] = []
    if scalars:
        title = _title_from_model(model_name)
        sections.append(
            (
                "main",
                title,
                [_field_view_ref(f, fld) for f, fld in scalars],
            )
        )
    if relations:
        sections.append(
            (
                "relations",
                "Relations",
                [_field_view_ref(f, fld) for f, fld in relations],
            )
        )
    if timestamps:
        sections.append(
            (
                "metadata",
                "Record info",
                [_field_view_ref(f, fld) for f, fld in timestamps],
            )
        )
    if not sections:
        sections.append(("main", _title_from_model(model_name), list_names))

    return list_names, sections


def _title_from_model(model_name: str) -> str:
    """``inventory.product`` → ``Product``."""
    stem = model_name.split(".")[-1]
    return " ".join(part.capitalize() for part in stem.split("_") if part)


def _timestamp_field_names(cls) -> list[str]:
    """Timestamp columns to show on list/form views when enabled."""
    try:
        from pyvelm.timestamps import (
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


def _minimal_view_fields(model_name: str) -> tuple[list[str], list[tuple[str, str, list[str]]]]:
    """Fallback when ``--from-model`` is off or the model is not loaded."""
    title = _title_from_model(model_name)
    return ['"name"'], [("main", title, ['"name"'])]


def _format_field_list(lines: list[str]) -> str:
    return "\n".join(f"            {line}," for line in lines)


def _format_form_sections(sections: list[tuple[str, str, list[str]]]) -> str:
    blocks: list[str] = []
    for sid, title, field_lines in sections:
        inner = _format_field_list(field_lines)
        blocks.append(
            f'            section("{sid}", "{title}", [\n{inner}\n            ]),'
        )
    return "\n".join(blocks)


def generate_views(
    module_path: Path,
    module_name: str,
    model_name: str,
    *,
    registry: Registry | None = None,
    force: bool = False,
    from_model: bool = True,
) -> Path:
    """Write ``views/<stem>.py`` and add to manifest ``DATA``."""
    file_stem, view_stem, technical = normalize_model_for_views(
        model_name, module_name, registry
    )
    target = module_path / "views" / f"{file_stem}.py"
    if target.exists() and not force:
        raise FileExistsError(
            f"{target} already exists — pass --force to overwrite."
        )
    (module_path / "views").mkdir(exist_ok=True)
    if from_model:
        if registry is None:
            registry = load_registry_for_module(module_name)
        if registry is None:
            raise ValueError(
                f"Cannot introspect {model_name!r}: module {module_name!r} was not "
                f"found under PYVELM_MODULE_ROOTS. Pass --minimal for a stub view, "
                f"or fix module roots."
            )
        list_fields, form_sections = build_view_scaffold_from_model(
            registry, technical
        )
    else:
        list_fields, form_sections = _minimal_view_fields(technical)
    body = _read_template(
        "snippets/view.py.template",
        {
            "module": module_name,
            "model": technical,
            "stem": view_stem,
            "list_fields": _format_field_list(list_fields),
            "form_sections": _format_form_sections(form_sections),
            "title": _title_from_model(technical),
        },
    )
    target.write_text(body, encoding="utf-8")
    append_manifest_data(
        module_path / "__pyvelm__.py",
        f"views/{file_stem}.py",
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
