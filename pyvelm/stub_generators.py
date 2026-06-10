"""Generate static typing stubs for app authors (``pyvelm make:stubs``).

Walks the same module discovery + model loading path as the loader, then
emits ``.pyvelm/typing/`` beside ``pyvelm.toml`` so Pylance/Pyright can
validate model and view string literals.
"""
from __future__ import annotations

import json
import re
import shutil
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
    # ``(module_name, package_path_relative_to_project)`` for Pyright scopes.
    module_roots: list[tuple[str, str]] = field(default_factory=list)


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
    module_roots: list[tuple[str, str]] | None = None,
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
    if module_roots is not None:
        desired["executionEnvironments"] = (
            _execution_environments(stub_path, module_roots)
            if module_roots
            else []
        )
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


def dependency_closure(
    module_name: str,
    specs: dict[str, ModuleSpec],
) -> frozenset[str]:
    """Return *module_name* plus every direct and indirect ``DEPENDS`` module."""
    visited: set[str] = set()
    stack = [module_name]
    while stack:
        current = stack.pop()
        if current in visited or current not in specs:
            continue
        visited.add(current)
        stack.extend(specs[current].depends)
    return frozenset(visited)


def index_for_modules(
    modules: frozenset[str],
    index: StubIndex,
) -> StubIndex:
    """Filter *index* to models and views declared in *modules*."""
    models = sorted(
        name
        for name, owner in index.model_modules.items()
        if owner in modules
    )
    qualified_views = [
        view
        for view in index.qualified_views
        if view.split(".", 1)[0] in modules
    ]
    view_slugs = sorted(
        {
            view.split(".", 1)[1]
            for view in qualified_views
            if "." in view
        }
    )
    return StubIndex(
        models=models,
        model_modules={
            name: owner
            for name, owner in index.model_modules.items()
            if owner in modules
        },
        qualified_views=qualified_views,
        view_slugs=view_slugs,
        view_models={
            view: model
            for view, model in index.view_models.items()
            if view in qualified_views
        },
    )


def _execution_environments(
    stub_path: str,
    module_roots: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Pyright execution environments — longest module roots win first."""
    envs: list[dict[str, Any]] = []
    for module_name, rel_root in sorted(
        module_roots,
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        scope_stub = f"{stub_path}/scopes/{module_name}"
        envs.append(
            {
                "root": rel_root,
                "stubPath": scope_stub,
                "extraPaths": [scope_stub, stub_path],
                "pythonVersion": "3.10",
            }
        )
    return envs


def _infer_project_root(
    modules_root: Path | None,
    output_dir: Path,
) -> Path | None:
    """Best-effort project root for relative module paths in pyrightconfig."""
    parent = output_dir.parent
    if parent.name == ".pyvelm" and (parent.parent / "pyvelm.toml").is_file():
        return parent.parent.resolve()
    if modules_root is not None:
        for ancestor in (modules_root.resolve(), *modules_root.resolve().parents):
            if (ancestor / "pyvelm.toml").is_file():
                return ancestor
    return None


def _module_roots_for_pyright(
    specs: dict[str, ModuleSpec],
    project_root: Path | None,
) -> list[tuple[str, str]]:
    if project_root is None:
        return []
    roots: list[tuple[str, str]] = []
    project = project_root.resolve()
    for spec in specs.values():
        if spec.package_path is None:
            continue
        try:
            rel = spec.package_path.resolve().relative_to(project).as_posix()
        except ValueError:
            continue
        roots.append((spec.name, rel))
    return sorted(roots, key=lambda item: item[1])


def generate_stubs(
    output_dir: Path,
    *,
    modules_root: Path | None = None,
    include_bundled: bool = True,
) -> tuple[Path, StubIndex]:
    """Write stub files under ``output_dir``; return path and the symbol index."""
    _registry, specs, index = load_stub_index(modules_root=modules_root)
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
    _write_stub_tree(out, index, include_readme=True)

    project_root = _infer_project_root(modules_root, out)
    index.module_roots = _module_roots_for_pyright(specs, project_root)

    scopes_dir = out / "scopes"
    if scopes_dir.is_dir():
        shutil.rmtree(scopes_dir)
    for module_name in sorted(specs):
        closure = dependency_closure(module_name, specs)
        scoped = index_for_modules(closure, index)
        _write_stub_tree(scopes_dir / module_name, scoped)

    return out, index


def _write_stub_tree(
    target: Path,
    index: StubIndex,
    *,
    include_readme: bool = False,
) -> None:
    """Write the standard ``.pyvelm/typing`` layout under *target*."""
    target.mkdir(parents=True, exist_ok=True)
    pyvelm_pkg = target / "pyvelm"
    pyvelm_pkg.mkdir(parents=True, exist_ok=True)

    (target / "py.typed").write_text("", encoding="utf-8")
    if include_readme:
        (target / "__init__.pyi").write_text(_render_package_init(), encoding="utf-8")
    (target / "names.pyi").write_text(_render_names(index), encoding="utf-8")
    (target / "models_stubs.pyi").write_text(
        _render_model_record_stubs(index), encoding="utf-8"
    )
    (pyvelm_pkg / "model.pyi").write_text(_render_model_stubs(), encoding="utf-8")
    (pyvelm_pkg / "models.pyi").write_text(
        _render_models_module_stubs(), encoding="utf-8"
    )
    (pyvelm_pkg / "registry.pyi").write_text(
        _render_registry_stubs(index), encoding="utf-8"
    )
    (pyvelm_pkg / "env.pyi").write_text(_render_env_stubs(index), encoding="utf-8")
    (pyvelm_pkg / "fields.pyi").write_text(_render_fields_stubs(), encoding="utf-8")
    (pyvelm_pkg / "field_builders.pyi").write_text(
        _render_field_builders_stubs(), encoding="utf-8"
    )
    legacy_builders_stub = pyvelm_pkg / "builders.pyi"
    if legacy_builders_stub.is_file():
        legacy_builders_stub.unlink()
    builders_pkg = pyvelm_pkg / "builders"
    builders_pkg.mkdir(parents=True, exist_ok=True)
    legacy_init_stub = builders_pkg / "__init__.pyi"
    if legacy_init_stub.is_file():
        legacy_init_stub.unlink()
    (builders_pkg / "menus.pyi").write_text(_render_menus_stubs(), encoding="utf-8")
    (builders_pkg / "views.pyi").write_text(_render_views_stubs(), encoding="utf-8")
    (builders_pkg / "legacy.pyi").write_text(_render_legacy_stubs(), encoding="utf-8")
    (pyvelm_pkg / "security.pyi").write_text(_render_security_stubs(), encoding="utf-8")
    if include_readme:
        (target / "README.md").write_text(_render_readme(), encoding="utf-8")


def _bundled_model_prefixes() -> frozenset[str]:
    """Module names shipped inside the pyvelm wheel (for --app-only filtering)."""
    return frozenset(
        {
            "base",
            "admin",
            "console",
            "geo_data",
            "file_manager",
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
        "from pyvelm.query import Query",
        "",
    ]
    for technical in index.models:
        cls = _class_name_from_model(technical)
        mod = index.model_modules.get(technical, "")
        hint = f"Module: ``{mod}``." if mod else ""
        lines.append(f"class {cls}(BaseModel):")
        lines.append(f'    """Recordset stub for ``{technical}``.{hint}"""')
        lines.append("    def query(self) -> Query: ...")
        lines.append("")
    return "\n".join(lines)


def _render_model_stubs() -> str:
    """Augment ``pyvelm.model.BaseModel`` — ``_name`` / ``_inherit`` literals."""
    return '''\
# AUTO-GENERATED by pyvelm make:stubs — do not edit.
from typing import ClassVar

from pyvelm.model import BaseModel as _BaseModel

from ..names import ModelName


class BaseModel(_BaseModel):
    _name: ClassVar[ModelName | str]
    _inherit: ClassVar[ModelName | str]
'''


def _render_models_module_stubs() -> str:
    """Augment ``pyvelm.models.Model`` (inherits typed ``BaseModel`` stub)."""
    return '''\
# AUTO-GENERATED by pyvelm make:stubs — do not edit.
from pyvelm.model import BaseModel as _BaseModel


class Model(_BaseModel):
    """Base class for model definitions and ``_inherit`` extensions."""
'''


def _render_field_builders_stubs() -> str:
    """Augment fluent ORM field builders — ``.comodel("…")`` suggests ``ModelName``."""
    return '''\
# AUTO-GENERATED by pyvelm make:stubs — do not edit.
from typing import overload

from pyvelm.field_builders import OrmFieldBuilder as _OrmFieldBuilder

from ..names import ModelName


class OrmFieldBuilder(_OrmFieldBuilder):
    @overload
    def comodel(self, name: ModelName) -> OrmFieldBuilder: ...
    @overload
    def comodel(self, name: str) -> OrmFieldBuilder: ...
'''


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
from pyvelm.query import Query

from ..names import ModelName


class Environment(_Environment):
    @overload
    def __getitem__(self, model_name: ModelName) -> BaseModel: ...
    @overload
    def __getitem__(self, model_name: str) -> BaseModel: ...
    @overload
    def query(self, model_name: ModelName) -> Query: ...
    @overload
    def query(self, model_name: str) -> Query: ...
'''


def _render_fields_stubs() -> str:
    return '''\
# AUTO-GENERATED by pyvelm make:stubs — do not edit.
from typing import Any, overload

from pyvelm.field_builders import OrmFieldBuilder
from pyvelm.fields import (
    Char as _Char,
    Code as _Code,
    Date as _Date,
    Datetime as _Datetime,
    Float as _Float,
    Html as _Html,
    Integer as _Integer,
    Many2many as _Many2many,
    Many2one as _Many2one,
    Monetary as _Monetary,
    One2many as _One2many,
    Text as _Text,
    Time as _Time,
)

from ..names import ModelName


class Many2one(_Many2one):
    @overload
    def __new__(cls) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, comodel_name: ModelName) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, comodel_name: str) -> OrmFieldBuilder: ...
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
    def __new__(cls) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, comodel_name: ModelName, inverse_name: str) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, comodel_name: str, inverse_name: str) -> OrmFieldBuilder: ...
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
    def __new__(cls) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, comodel_name: ModelName) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, comodel_name: str) -> OrmFieldBuilder: ...
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


class Char(_Char):
    @overload
    def __new__(cls) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, **kwargs: Any) -> _Char: ...


class Text(_Text):
    @overload
    def __new__(cls) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, **kwargs: Any) -> _Text: ...


class Integer(_Integer):
    @overload
    def __new__(cls) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, **kwargs: Any) -> _Integer: ...


class Float(_Float):
    @overload
    def __new__(cls) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, **kwargs: Any) -> _Float: ...


class Monetary(_Monetary):
    @overload
    def __new__(cls) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, **kwargs: Any) -> _Monetary: ...


class Date(_Date):
    @overload
    def __new__(cls) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, **kwargs: Any) -> _Date: ...


class Datetime(_Datetime):
    @overload
    def __new__(cls) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, **kwargs: Any) -> _Datetime: ...


class Time(_Time):
    @overload
    def __new__(cls) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, **kwargs: Any) -> _Time: ...


class Html(_Html):
    @overload
    def __new__(cls) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, **kwargs: Any) -> _Html: ...


class Code(_Code):
    @overload
    def __new__(cls) -> OrmFieldBuilder: ...
    @overload
    def __new__(cls, **kwargs: Any) -> _Code: ...
'''


def _render_menus_stubs() -> str:
    """Augment ``pyvelm.builders.menus`` with ``ViewSlug`` / ``ModelName`` types.

    Do **not** stub ``builders/__init__.py`` — a partial package stub would
    replace the whole ``pyvelm.builders`` namespace and hide ``Field``,
    ``ListView``, ``ViewsData``, etc.
    """
    return '''\
# AUTO-GENERATED by pyvelm make:stubs — do not edit.
from collections.abc import Sequence

from pyvelm.types import Menu

from ...names import ModelName, ViewSlug


class MenuItem:
    def view(self, view: ViewSlug | str, *, module: str | None = None) -> MenuItem: ...


class MenuBranch:
    def children(self, entries: Sequence[Menu | MenuBranch | MenuItem]) -> MenuBranch: ...


class Menus:
    def __init__(self, module: str) -> None: ...
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
    ) -> MenuItem: ...


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


_BUILDER_MODEL_CLASSES: tuple[str, ...] = (
    "ListViewBuilder",
    "FormViewBuilder",
    "DetailViewBuilder",
    "KanbanViewBuilder",
    "GraphViewBuilder",
    "PivotViewBuilder",
    "ChartWidgetBuilder",
    "TableWidgetBuilder",
    "StatWidgetBuilder",
)


def _stub_builder_model_method(class_name: str) -> list[str]:
    """Overload ``model()`` on a fluent view/widget builder class."""
    return [
        f"class {class_name}:",
        "    @overload",
        f"    def model(self, model: ModelName) -> {class_name}: ...",
        "    @overload",
        f"    def model(self, model: str) -> {class_name}: ...",
        "",
    ]


def _render_views_stubs() -> str:
    """Augment ``pyvelm.builders.views`` — ``.model("…")`` suggests ``ModelName``."""
    lines = [
        "# AUTO-GENERATED by pyvelm make:stubs — do not edit.",
        "from typing import overload",
        "",
        "from ...names import ModelName",
        "",
    ]
    for class_name in _BUILDER_MODEL_CLASSES:
        lines.extend(_stub_builder_model_method(class_name))
    return "\n".join(lines)


def _render_legacy_stubs() -> str:
    """Augment ``pyvelm.builders.legacy`` view factories — ``model=`` suggests ``ModelName``."""
    return '''\
# AUTO-GENERATED by pyvelm make:stubs — do not edit.
from typing import Any, overload

from pyvelm.types import (
    ArchKanbanCard,
    DashboardColspan,
    DashboardWidget,
    FieldRefLike,
    FormLayoutItem,
    FormView,
    GraphView,
    KanbanView,
    ListView,
    PivotView,
    ViewRef,
)

from ...names import ModelName


@overload
def list_view(
    name: str,
    model: ModelName,
    fields: list[FieldRefLike],
    *,
    title: str | None = None,
    form_view: str | None = None,
    record_href: str | None = None,
    create_href: str | None = None,
    page_actions: list[dict] | None = None,
    sequence: str | None = None,
    domain: list | None = None,
    priority: int = 16,
) -> ListView: ...
@overload
def list_view(
    name: str,
    model: str,
    fields: list[FieldRefLike],
    *,
    title: str | None = None,
    form_view: str | None = None,
    record_href: str | None = None,
    create_href: str | None = None,
    page_actions: list[dict] | None = None,
    sequence: str | None = None,
    domain: list | None = None,
    priority: int = 16,
) -> ListView: ...


@overload
def form_view(
    name: str,
    model: ModelName,
    sections: list[FormLayoutItem],
    *,
    title: str | None = None,
    header_actions: list[dict] | None = None,
    cols: int | None = None,
    priority: int = 16,
) -> FormView: ...
@overload
def form_view(
    name: str,
    model: str,
    sections: list[FormLayoutItem],
    *,
    title: str | None = None,
    header_actions: list[dict] | None = None,
    cols: int | None = None,
    priority: int = 16,
) -> FormView: ...


@overload
def kanban_view(
    name: str,
    model: ModelName,
    *,
    card: ArchKanbanCard | None = None,
    group_by: str | None = None,
    sequence: str | None = None,
    form_view: str | None = None,
    title: str | None = None,
    priority: int = 16,
) -> KanbanView: ...
@overload
def kanban_view(
    name: str,
    model: str,
    *,
    card: ArchKanbanCard | None = None,
    group_by: str | None = None,
    sequence: str | None = None,
    form_view: str | None = None,
    title: str | None = None,
    priority: int = 16,
) -> KanbanView: ...


@overload
def graph_view(
    name: str,
    model: ModelName,
    *,
    groupby: str,
    measure: str,
    chart: str = "bar",
    title: str | None = None,
    stacked: bool | None = None,
    horizontal: bool | None = None,
    domain: list | None = None,
    priority: int = 16,
) -> GraphView: ...
@overload
def graph_view(
    name: str,
    model: str,
    *,
    groupby: str,
    measure: str,
    chart: str = "bar",
    title: str | None = None,
    stacked: bool | None = None,
    horizontal: bool | None = None,
    domain: list | None = None,
    priority: int = 16,
) -> GraphView: ...


@overload
def pivot_view(
    name: str,
    model: ModelName,
    *,
    row_groupby: list[str],
    col_groupby: list[str] | None = None,
    measures: list[str],
    title: str | None = None,
    domain: list | None = None,
    priority: int = 16,
) -> PivotView: ...
@overload
def pivot_view(
    name: str,
    model: str,
    *,
    row_groupby: list[str],
    col_groupby: list[str] | None = None,
    measures: list[str],
    title: str | None = None,
    domain: list | None = None,
    priority: int = 16,
) -> PivotView: ...


@overload
def chart_widget(
    widget_id: str,
    *,
    title: str | None = None,
    model: ModelName | None = None,
    groupby: str | None = None,
    measure: str = "__count",
    chart: str = "bar",
    domain: list | None = None,
    view: ViewRef | None = None,
    colspan: DashboardColspan = 2,
    perm: str = "read",
) -> DashboardWidget: ...
@overload
def chart_widget(
    widget_id: str,
    *,
    title: str | None = None,
    model: str | None = None,
    groupby: str | None = None,
    measure: str = "__count",
    chart: str = "bar",
    domain: list | None = None,
    view: ViewRef | None = None,
    colspan: DashboardColspan = 2,
    perm: str = "read",
) -> DashboardWidget: ...


@overload
def table_widget(
    widget_id: str,
    *,
    title: str | None = None,
    model: ModelName | None = None,
    fields: list[FieldRefLike] | None = None,
    view: ViewRef | None = None,
    columns: list[str] | None = None,
    domain: list | None = None,
    limit: int = 10,
    order: str | None = None,
    more_href: str | None = None,
    colspan: DashboardColspan = 1,
    perm: str = "read",
) -> DashboardWidget: ...
@overload
def table_widget(
    widget_id: str,
    *,
    title: str | None = None,
    model: str | None = None,
    fields: list[FieldRefLike] | None = None,
    view: ViewRef | None = None,
    columns: list[str] | None = None,
    domain: list | None = None,
    limit: int = 10,
    order: str | None = None,
    more_href: str | None = None,
    colspan: DashboardColspan = 1,
    perm: str = "read",
) -> DashboardWidget: ...


@overload
def stat_widget(
    widget_id: str,
    *,
    title: str,
    model: ModelName,
    measure: str = "__count",
    domain: list | None = None,
    href: str | None = None,
    colspan: DashboardColspan = 1,
    perm: str = "read",
) -> DashboardWidget: ...
@overload
def stat_widget(
    widget_id: str,
    *,
    title: str,
    model: str,
    measure: str = "__count",
    domain: list | None = None,
    href: str | None = None,
    colspan: DashboardColspan = 1,
    perm: str = "read",
) -> DashboardWidget: ...
'''


def _render_security_stubs() -> str:
    """Augment ``pyvelm.security`` — ``grant_model_access`` model arg."""
    return '''\
# AUTO-GENERATED by pyvelm make:stubs — do not edit.
from typing import overload

from pyvelm.env import Environment

from ..names import ModelName


@overload
def grant_model_access(
    env: Environment,
    model: ModelName,
    *,
    admin: str | None = "crud",
    user: str | None = "read",
    public: str | None = None,
) -> None: ...
@overload
def grant_model_access(
    env: Environment,
    model: str,
    *,
    admin: str | None = "crud",
    user: str | None = "read",
    public: str | None = None,
) -> None: ...
'''


def _render_readme() -> str:
    return """\
# Pyvelm typing stubs (generated)

Regenerate after changing models or views:

```bash
pyvelm make:stubs
```

Point Pyright/Pylance at this directory from your project root
(``pyvelm.toml`` parent). ``pyvelm make:stubs`` creates or merges
``pyrightconfig.json`` there (same defaults as ``pyvelm init``). It
configures:

- ``stubPath``: ``.pyvelm/typing`` (augments ``pyvelm.model`` / ``env`` / ``fields`` /
  ``field_builders`` / ``Registry`` / ``builders`` / ``security``)
- ``extraPaths``: ``.pyvelm/typing`` (import ``ModelName``, ``QualifiedViewName``)
- ``executionEnvironments``: per-addon roots under ``scopes/<module>/`` so
  ``ModelName`` only lists models from that module and its ``DEPENDS`` chain

Commit these files or gitignore ``.pyvelm/`` and regenerate locally.
"""
