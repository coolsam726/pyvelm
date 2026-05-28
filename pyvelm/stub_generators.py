"""Generate static typing stubs for app authors (``pyvelm make:stubs``).

Walks the same module discovery + model loading path as the loader, then
emits ``.pyvelm/typing/`` beside ``pyvelm.toml`` so Pylance/Pyright can
validate model and view string literals.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .scaffold_generators import modules_root_candidates
from .scaffolder import _read_modules_root, _substitute

if TYPE_CHECKING:
    from .loader import ModuleSpec
    from .registry import Registry

_DEFAULT_STUBS_SUBDIR = Path(".pyvelm") / "typing"
_MAX_LITERAL_MEMBERS = 400


@dataclass
class StubIndex:
    """Collected symbols for one stub generation run."""

    models: list[str] = field(default_factory=list)
    model_modules: dict[str, str] = field(default_factory=dict)
    qualified_views: list[str] = field(default_factory=list)
    view_slugs: list[str] = field(default_factory=list)
    view_models: dict[str, str] = field(default_factory=dict)


def default_stubs_dir(project_root: Path | None = None) -> Path:
    """Return the default output directory for typing stubs."""
    root = project_root or Path.cwd()
    return (root / _DEFAULT_STUBS_SUBDIR).resolve()


def discover_include_paths(project_root: Path) -> list[str]:
    """Directories Pylance should analyze (addon roots, ``app/``, ``examples/``, …)."""
    includes: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        if path in ("", ".") or path in seen:
            return
        seen.add(path)
        includes.append(path)

    marker = project_root / "pyvelm.toml"
    if marker.is_file():
        try:
            add(_read_modules_root(marker).relative_to(project_root.resolve()).as_posix())
        except ValueError:
            pass

    for name in ("app", "examples", "examples/modules", "examples/modules_demo"):
        if (project_root / name).is_dir():
            add(name)

    if not includes:
        add(".")
    return includes


def write_pyrightconfig(
    project_root: Path,
    *,
    stubs_dir: Path,
    create_only: bool = False,
) -> bool:
    """Write or refresh ``pyrightconfig.json`` (include paths + stub dirs).

    When *create_only* is True, an existing file is left unchanged.
    Returns True when the file was created or updated.
    """
    target = project_root / "pyrightconfig.json"
    if create_only and target.is_file():
        return False
    try:
        stub_path = stubs_dir.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        stub_path = stubs_dir.resolve().as_posix()

    desired: dict[str, Any] = {
        "include": discover_include_paths(project_root),
        "stubPath": stub_path,
        "extraPaths": [stub_path],
        "pythonVersion": "3.10",
        "typeCheckingMode": "basic",
    }
    if target.is_file():
        try:
            current = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
        merged = {**current, **desired}
        if merged == current:
            return False
        body = merged
    else:
        body = desired
    target.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return True


def ensure_pyrightconfig(project_root: Path, *, stubs_dir: Path) -> bool:
    """Create ``pyrightconfig.json`` when missing (see :func:`write_pyrightconfig`)."""
    return write_pyrightconfig(project_root, stubs_dir=stubs_dir, create_only=True)


def default_pyrightconfig_variables(project_root: Path) -> dict[str, str]:
    """Template variables for ``pyvelm init`` ``pyrightconfig.json.template``."""
    includes = discover_include_paths(project_root)
    return {
        "stub_path": ".pyvelm/typing",
        "include_json": json.dumps(includes),
    }


def load_stub_index(
    *,
    modules_root: Path | None = None,
) -> tuple[Registry, dict[str, ModuleSpec], StubIndex]:
    """Discover modules, load models + declarative data, return registry + index."""
    from . import loader
    from .registry import Registry

    roots = modules_root_candidates(modules_root)
    specs = loader.discover(roots)
    ordered = loader.resolve_order(specs)
    registry = Registry()
    for spec in ordered:
        loader._load_models(spec, registry)
    for spec in ordered:
        loader._load_data_files(spec)

    index = StubIndex()
    index.models = sorted(registry._models.keys())
    index.model_modules = dict(registry._model_module)

    qualified: set[str] = set()
    slugs: set[str] = set()
    for spec in ordered:
        for view in spec.views:
            name = view.get("name")
            if not name:
                continue
            q = f"{spec.name}.{name}"
            qualified.add(q)
            slugs.add(str(name))
            if view.get("model"):
                index.view_models[q] = str(view["model"])
        for inherit in spec.view_inherits:
            iname = inherit.get("name")
            if iname:
                qualified.add(f"{spec.name}.{iname}")
                slugs.add(str(iname))

    index.qualified_views = sorted(qualified)
    index.view_slugs = sorted(slugs)
    return registry, specs, index


def generate_stubs(
    output_dir: Path,
    *,
    modules_root: Path | None = None,
    include_bundled: bool = True,
) -> tuple[Path, StubIndex]:
    """Write stub files under ``output_dir``; return path and the symbol index."""
    _registry, _specs, index = load_stub_index(modules_root=modules_root)
    if not include_bundled:
        bundled = _bundled_model_prefixes()
        index.models = [m for m in index.models if not _is_bundled(m, bundled)]
        index.model_modules = {
            k: v
            for k, v in index.model_modules.items()
            if k in index.models
        }
        index.qualified_views = [
            v
            for v in index.qualified_views
            if not any(v.startswith(p + ".") for p in bundled)
        ]
        index.view_slugs = [
            v
            for v in index.view_slugs
            if "." not in v or not any(v.startswith(p) for p in bundled)
        ]
        index.view_models = {
            k: v for k, v in index.view_models.items() if k in index.qualified_views
        }

    out = output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    pyvelm_pkg = out / "pyvelm"
    pyvelm_pkg.mkdir(parents=True, exist_ok=True)

    (out / "py.typed").write_text("", encoding="utf-8")
    (out / "__init__.pyi").write_text(_render_package_init(), encoding="utf-8")
    (out / "names.pyi").write_text(_render_names(index), encoding="utf-8")
    (out / "models_stubs.pyi").write_text(
        _render_model_record_stubs(index), encoding="utf-8"
    )
    (pyvelm_pkg / "registry.pyi").write_text(
        _render_registry_stubs(index), encoding="utf-8"
    )
    (pyvelm_pkg / "env.pyi").write_text(_render_env_stubs(index), encoding="utf-8")
    (pyvelm_pkg / "fields.pyi").write_text(_render_fields_stubs(), encoding="utf-8")
    (pyvelm_pkg / "builders.pyi").write_text(_render_builders_stubs(), encoding="utf-8")
    (out / "README.md").write_text(_render_readme(), encoding="utf-8")
    return out, index


def _bundled_model_prefixes() -> frozenset[str]:
    """Module names shipped inside the pyvelm wheel (for --app-only filtering)."""
    return frozenset(
        {
            "base",
            "admin",
            "console",
            "geo_data",
            "file_manager",
            "vellum",
        }
    )


def _is_bundled(model_name: str, module_names: frozenset[str]) -> bool:
    mod = model_name.split(".", 1)[0] if "." in model_name else ""
    return mod in module_names or model_name.startswith("ir.")


def _class_name_from_model(technical: str) -> str:
    parts = [p for p in re.split(r"[._]", technical) if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) + "Record"


def _literal_union(name: str, values: list[str], *, fallback: str = "str") -> str:
    if not values:
        return f"{name} = {fallback}  # nothing discovered — run from project root"
    if len(values) > _MAX_LITERAL_MEMBERS:
        head = values[:_MAX_LITERAL_MEMBERS]
        body = _literal_members(head)
        return (
            f"{name} = Literal[\n{body}\n]  # truncated; "
            f"{len(values)} total — narrow with --modules-root"
        )
    body = _literal_members(values)
    return f"{name} = Literal[\n{body}\n]"


def _literal_members(values: list[str]) -> str:
    return ",\n".join(f'    "{_escape_literal(v)}"' for v in values)


def _escape_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _render_package_init() -> str:
    return '''\
"""Generated pyvelm typing stubs — import literals from here in app code."""

from .names import (
    ModelName,
    QualifiedViewName,
    ViewName,
    ViewSlug,
)

__all__ = [
    "ModelName",
    "QualifiedViewName",
    "ViewName",
    "ViewSlug",
]
'''


def _render_names(index: StubIndex) -> str:
    lines = [
        "# AUTO-GENERATED by pyvelm make:stubs — do not edit.",
        "from typing import Literal",
        "",
        _literal_union("ModelName", index.models),
        "",
        _literal_union("QualifiedViewName", index.qualified_views),
        "",
        _literal_union("ViewSlug", index.view_slugs),
        "",
        "# Short view name within the declaring module (e.g. menu view=).",
        "ViewName = ViewSlug",
        "",
    ]
    return "\n".join(lines)


def _render_model_record_stubs(index: StubIndex) -> str:
    lines = [
        "# AUTO-GENERATED by pyvelm make:stubs — do not edit.",
        "from pyvelm.model import BaseModel",
        "",
    ]
    for technical in index.models:
        cls = _class_name_from_model(technical)
        mod = index.model_modules.get(technical, "")
        hint = f"Module: ``{mod}``." if mod else ""
        lines.append(f"class {cls}(BaseModel):")
        lines.append(f'    """Recordset stub for ``{technical}``.{hint}"""')
        lines.append("")
    return "\n".join(lines)


def _render_registry_stubs(_index: StubIndex) -> str:
    return '''\
# AUTO-GENERATED by pyvelm make:stubs — do not edit.
from typing import overload

from pyvelm.model import BaseModel
from pyvelm.registry import Registry as _Registry

from ..names import ModelName


class Registry(_Registry):
    @overload
    def __getitem__(self, name: ModelName) -> type[BaseModel]: ...
    @overload
    def __getitem__(self, name: str) -> type[BaseModel]: ...
'''


def _render_env_stubs(_index: StubIndex) -> str:
    return '''\
# AUTO-GENERATED by pyvelm make:stubs — do not edit.
from typing import overload

from pyvelm.env import Environment as _Environment
from pyvelm.model import BaseModel

from ..names import ModelName


class Environment(_Environment):
    @overload
    def __getitem__(self, model_name: ModelName) -> BaseModel: ...
    @overload
    def __getitem__(self, model_name: str) -> BaseModel: ...
'''


def _render_fields_stubs() -> str:
    return '''\
# AUTO-GENERATED by pyvelm make:stubs — do not edit.
from typing import overload

from pyvelm.fields import Field, Many2many as _Many2many, Many2one as _Many2one
from pyvelm.fields import One2many as _One2many

from ..names import ModelName


class Many2one(_Many2one):
    @overload
    def __init__(
        self,
        comodel_name: ModelName,
        string: str | None = None,
        required: bool = False,
        ondelete: str = "SET NULL",
        column: str | None = None,
        related: str | None = None,
        readonly: bool = False,
        tracking: bool = False,
    ) -> None: ...
    @overload
    def __init__(
        self,
        comodel_name: str,
        string: str | None = None,
        required: bool = False,
        ondelete: str = "SET NULL",
        column: str | None = None,
        related: str | None = None,
        readonly: bool = False,
        tracking: bool = False,
    ) -> None: ...


class One2many(_One2many):
    @overload
    def __init__(
        self,
        comodel_name: ModelName,
        inverse_name: str,
        string: str | None = None,
        related: str | None = None,
        readonly: bool = False,
        tracking: bool = False,
    ) -> None: ...
    @overload
    def __init__(
        self,
        comodel_name: str,
        inverse_name: str,
        string: str | None = None,
        related: str | None = None,
        readonly: bool = False,
        tracking: bool = False,
    ) -> None: ...


class Many2many(_Many2many):
    @overload
    def __init__(
        self,
        comodel_name: ModelName,
        string: str | None = None,
        relation: str | None = None,
        column1: str | None = None,
        column2: str | None = None,
        related: str | None = None,
        readonly: bool = False,
        tracking: bool = False,
    ) -> None: ...
    @overload
    def __init__(
        self,
        comodel_name: str,
        string: str | None = None,
        relation: str | None = None,
        column1: str | None = None,
        column2: str | None = None,
        related: str | None = None,
        readonly: bool = False,
        tracking: bool = False,
    ) -> None: ...
'''


def _render_builders_stubs() -> str:
    return '''\
# AUTO-GENERATED by pyvelm make:stubs — do not edit.
from pyvelm.builders import Menus as _Menus
from pyvelm.builders import menu_item as _menu_item
from pyvelm.types import Menu

from ..names import ModelName, ViewSlug


class Menus(_Menus):
    def item(
        self,
        name: str,
        label: str,
        *,
        href: str | None = None,
        view: ViewSlug | str | None = None,
        view_module: str | None = None,
        parent: str | tuple[str, str] | None = None,
        icon: str | None = None,
        sequence: int = 10,
        perm: str | None = None,
        model: ModelName | str | None = None,
        policy: str | None = None,
        dev_only: bool = False,
    ) -> Menu: ...


def menu_item(
    name: str,
    label: str,
    *,
    href: str | None = None,
    view: ViewSlug | str | None = None,
    menu_module: str | None = None,
    view_module: str | None = None,
    parent: str | tuple[str, str] | None = None,
    icon: str | None = None,
    sequence: int = 10,
    perm: str | None = None,
    model: ModelName | str | None = None,
    policy: str | None = None,
    dev_only: bool = False,
) -> Menu: ...
'''


def _render_readme() -> str:
    return """\
# Pyvelm typing stubs (generated)

Regenerate after changing models or views:

```bash
pyvelm make:stubs
```

Point Pyright/Pylance at this directory from your project root
(``pyvelm.toml`` parent). ``pyvelm make:stubs`` creates
``pyrightconfig.json`` there when missing (same template as
``pyvelm init``). It configures:

- ``stubPath``: ``.pyvelm/typing`` (augments ``pyvelm.env`` / ``Registry``)
- ``extraPaths``: ``.pyvelm/typing`` (import ``ModelName``, ``QualifiedViewName``)

Commit these files or gitignore ``.pyvelm/`` and regenerate locally.
"""
