"""Module discovery, dependency resolution, and install/migrate.

A pyvelm module is a Python package containing a `__pyvelm__.py` manifest
with at least:

    NAME = "partners"
    VERSION = (0, 1, 0)
    DEPENDS = ["base"]

Optionally:

    MODELS_PACKAGE = "myapp.partners.models"   # defaults to <pkg>.models
    INSTALL_HOOK = "myapp.partners.hooks:install"
    SYNC_HOOK = "myapp.partners.hooks:sync"   # runs on Apps Sync (re-install path)
    WEB_ROUTES = "myapp.partners.web:register_routes"  # optional FastAPI routes
    MIGRATIONS_PACKAGE = "myapp.partners.migrations"  # defaults to <pkg>.migrations

The loader:
  1. discovers manifests under given roots,
  2. resolves dependency order (topo sort, cycle detection),
  3. imports each module's models under an active registry,
  4. runs install/migrate per module inside one transaction,
  5. records installed versions in `ir_module`.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Callable

from .env import Environment
from .registry import Registry


# Reserved name for the bookkeeping table the loader maintains.
IR_MODULE_TABLE = "ir_module"

_BUILTIN_MODULES_ROOT = Path(__file__).resolve().parent / "modules"


def discover_bootstrap_module_names() -> frozenset[str]:
    """Technical names of every bundled module under ``pyvelm/modules/``."""
    if not _BUILTIN_MODULES_ROOT.is_dir():
        return frozenset({"base", "admin"})
    return frozenset(
        p.name
        for p in _BUILTIN_MODULES_ROOT.iterdir()
        if p.is_dir() and (p / "__pyvelm__.py").is_file()
    )


# Auto-installed on a fresh database (empty ``ir_module``). Every other
# discovered module (e.g. app addons outside ``pyvelm/modules/``) is opt-in
# via **Apps** or ``pyvelm migrate --all``.
BOOTSTRAP_MODULES: frozenset[str] = discover_bootstrap_module_names()


def parse_module_roots_env(value: str) -> list[Path]:
    """Parse ``PYVELM_MODULE_ROOTS`` — comma- or colon-separated paths."""
    import re

    parts = re.split(r"[:,]", value or "")
    return [Path(p.strip()) for p in parts if p.strip()]


@dataclass
class ModuleSpec:
    name: str
    version: tuple[int, ...]
    depends: list[str]
    package: str                       # import path of the module package
    models_package: str
    migrations_package: str | None
    install_hook: Callable | None = None
    sync_hook: Callable | None = None
    web_routes: str | None = None
    package_path: Path | None = None
    data: list[str] = dc_field(default_factory=list)
    # Optional human-facing manifest fields. Drive the Apps catalog UI;
    # none of them affect install behavior.
    display_name: str = ""             # human label for Apps UI (defaults from name)
    summary: str = ""                  # one-line tagline
    description: str = ""              # longer prose (Markdown-ish)
    category: str = ""                 # grouping label, e.g. "CRM" or "Admin"
    author: str = ""                   # free-form
    icon: str = ""                     # raw inline SVG markup or empty
    # Optional Apps-catalog visibility gate. When set, `/web/apps` hides this
    # module unless the user passes the ACL + (optional) policy check.
    catalog_access_model: str = ""
    catalog_access_perm: str = ""
    catalog_access_policy: str = ""
    # Filled during install from the data files.
    views: list[dict[str, Any]] = dc_field(default_factory=list)
    view_inherits: list[dict[str, Any]] = dc_field(default_factory=list)
    menus: list[dict[str, Any]] = dc_field(default_factory=list)
    command_refs: list[str] = dc_field(default_factory=list)
    # Filled by the loader during the import pass.
    loaded: bool = False

    @property
    def version_str(self) -> str:
        return ".".join(str(p) for p in self.version)


def module_display_name(name: str, explicit: str | None = None) -> str:
    """Readable Apps label. ``NAME`` stays the technical id (``vellum_demo``)."""
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    return " ".join(part.capitalize() for part in name.split("_") if part)


def _import_attr(dotted: str):
    """Resolve `pkg.mod:attr` (or `pkg.mod.attr`) into the attribute."""
    if ":" in dotted:
        mod_name, attr = dotted.rsplit(":", 1)
    else:
        mod_name, attr = dotted.rsplit(".", 1)
    mod = importlib.import_module(mod_name)
    return getattr(mod, attr)


def _read_manifest(pkg_path: Path) -> ModuleSpec | None:
    manifest = pkg_path / "__pyvelm__.py"
    if not manifest.is_file():
        return None
    spec_obj = importlib.util.spec_from_file_location(
        f"_pyvelm_manifest_{pkg_path.name}", manifest
    )
    if spec_obj is None or spec_obj.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec_obj)
    spec_obj.loader.exec_module(mod)

    if not hasattr(mod, "NAME"):
        raise ValueError(f"Manifest at {manifest} is missing NAME")
    if not hasattr(mod, "VERSION"):
        raise ValueError(f"Manifest at {manifest} is missing VERSION")

    name = mod.NAME
    version = tuple(mod.VERSION)
    depends = list(getattr(mod, "DEPENDS", []))
    package = getattr(mod, "PACKAGE", pkg_path.name)
    models_pkg = getattr(mod, "MODELS_PACKAGE", f"{package}.models")
    migrations_pkg = getattr(mod, "MIGRATIONS_PACKAGE", f"{package}.migrations")
    install_dotted = getattr(mod, "INSTALL_HOOK", None)
    install_hook = _import_attr(install_dotted) if install_dotted else None
    sync_dotted = getattr(mod, "SYNC_HOOK", None)
    sync_hook = _import_attr(sync_dotted) if sync_dotted else None
    web_routes = getattr(mod, "WEB_ROUTES", None)
    if web_routes is not None:
        web_routes = str(web_routes).strip() or None
    data = list(getattr(mod, "DATA", []))
    command_refs = list(getattr(mod, "COMMANDS", []))

    return ModuleSpec(
        name=name,
        version=version,
        depends=depends,
        package=package,
        models_package=models_pkg,
        migrations_package=migrations_pkg,
        install_hook=install_hook,
        sync_hook=sync_hook,
        web_routes=web_routes,
        package_path=pkg_path,
        data=data,
        display_name=module_display_name(
            name, getattr(mod, "DISPLAY_NAME", None)
        ),
        summary=getattr(mod, "SUMMARY", ""),
        description=getattr(mod, "DESCRIPTION", ""),
        category=getattr(mod, "CATEGORY", ""),
        author=getattr(mod, "AUTHOR", ""),
        icon=getattr(mod, "ICON", ""),
        catalog_access_model=getattr(mod, "CATALOG_ACCESS_MODEL", ""),
        catalog_access_perm=getattr(mod, "CATALOG_ACCESS_PERM", ""),
        catalog_access_policy=getattr(mod, "CATALOG_ACCESS_POLICY", ""),
        command_refs=command_refs,
    )


def discover(roots: list[Path | str]) -> dict[str, ModuleSpec]:
    """Walk `roots` for directories containing a `__pyvelm__.py` manifest."""
    specs: dict[str, ModuleSpec] = {}
    for root in roots:
        rootp = Path(root)
        if not rootp.is_dir():
            continue
        # Make the root importable so `partners.models.partner` etc. resolves.
        rootp_str = str(rootp.resolve())
        if rootp_str not in sys.path:
            sys.path.insert(0, rootp_str)
        for sub in sorted(rootp.iterdir()):
            if not sub.is_dir():
                continue
            spec = _read_manifest(sub)
            if spec is None:
                continue
            if spec.name in specs:
                raise ValueError(
                    f"Duplicate module name {spec.name!r} "
                    f"({specs[spec.name].package_path} and {sub})"
                )
            specs[spec.name] = spec
    return specs


def resolve_order(specs: dict[str, ModuleSpec]) -> list[ModuleSpec]:
    """Topological sort by DEPENDS; raises on missing deps or cycles."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in specs}
    order: list[ModuleSpec] = []

    def visit(n: str, stack: list[str]):
        if color[n] == BLACK:
            return
        if color[n] == GRAY:
            cycle = stack[stack.index(n):] + [n]
            raise ValueError(f"Module dependency cycle: {' -> '.join(cycle)}")
        color[n] = GRAY
        for dep in specs[n].depends:
            if dep not in specs:
                raise ValueError(
                    f"Module {n!r} depends on {dep!r} which was not discovered"
                )
            visit(dep, stack + [n])
        color[n] = BLACK
        order.append(specs[n])

    for n in specs:
        visit(n, [])
    return order


def _has_models_package(spec: ModuleSpec) -> bool:
    """True when the module ships a ``models/`` package to import."""
    if spec.package_path is not None:
        return (spec.package_path / "models").is_dir()
    try:
        return importlib.util.find_spec(spec.models_package) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _sync_models_from_package(
    spec: ModuleSpec,
    registry: Registry,
    before_models: dict[str, type],
) -> None:
    """Register model classes from an imported models package.

    On a fresh import, metaclass hooks usually register classes already.
    When Python has cached the package (uvicorn ``--reload``, tests, or a
    second ``Registry`` in-process), class bodies do not re-run and we must
    scan ``sys.modules`` and attach classes to this registry explicitly.
    """
    from .model import BaseModel

    prefix = spec.models_package + "."
    mod_names = [spec.models_package] + [
        k for k in sys.modules if k.startswith(prefix)
    ]
    seen: set[type] = set()
    for mod_name in mod_names:
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        for attr in vars(mod).values():
            if not isinstance(attr, type) or attr in seen:
                continue
            if not issubclass(attr, BaseModel):
                continue
            name = getattr(attr, "_name", None)
            if not name:
                continue
            seen.add(attr)
            registry._models[name] = attr

    for model_name, cls in registry._models.items():
        if model_name not in before_models:
            registry._model_module[model_name] = spec.name
        elif cls is not before_models[model_name]:
            registry._model_extensions.setdefault(spec.name, []).append(
                model_name
            )


def _load_models(spec: ModuleSpec, registry: Registry) -> None:
    """Import a module's models package under the active registry, tagging
    every newly-registered model with the module name.

    Modules without a ``models/`` directory (e.g. the bundled ``console``
    CLI-only addon) are skipped.

    New models (not in registry before the import) are tagged with this
    module as their owner.  Existing models whose registry class changed
    (replaced by a `_inherit` extension) are recorded in
    `registry._model_extensions` so `_setup_module_schema` can add their
    new columns.

    When the models package is already in :data:`sys.modules` (uvicorn
    reload, tests, or a prior ``install_all`` in-process), class bodies
    do not re-run and ``_inherit`` merges would stay bound to an old
    registry — reload the package so extensions merge against *registry*.
    """
    if not _has_models_package(spec):
        spec.loaded = True
        return
    with registry.activate():
        before_models: dict[str, type] = dict(registry._models)
        if spec.models_package in sys.modules:
            reload_models(spec, registry)
        else:
            importlib.import_module(spec.models_package)
            _sync_models_from_package(spec, registry, before_models)
    spec.loaded = True


def reload_models(spec: ModuleSpec, registry: Registry) -> None:
    """Re-import a module's models package (upgrade / dev reload).

    Refreshes Python class definitions on the live registry without
    requiring a full process restart.
    """
    if not _has_models_package(spec):
        return
    with registry.activate():
        before_models: dict[str, type] = dict(registry._models)
        pkg = importlib.import_module(spec.models_package)
        importlib.reload(pkg)
        prefix = spec.models_package + "."
        for mod_name in sorted(
            k for k in sys.modules if k.startswith(prefix)
        ):
            importlib.reload(sys.modules[mod_name])
        _sync_models_from_package(spec, registry, before_models)


def reload_installed_models(env: Environment, specs: dict[str, ModuleSpec]) -> None:
    """Re-import models for every installed module in dependency order.

    Reloading a single module overwrites ``_inherit`` merges on shared
    models (e.g. upgrading ``base`` alone drops ``geo_data`` fields on
    ``res.country`` while ``res.continent`` still references them).
    """
    _ensure_ir_module(env)
    rows = env.conn.execute(
        f'SELECT name FROM "{IR_MODULE_TABLE}"',
    ).fetchall()
    installed = {r[0] for r in rows}
    subset = {k: v for k, v in specs.items() if k in installed}
    if not subset:
        return
    for spec in resolve_order(subset):
        reload_models(spec, env.registry)


def _ensure_ir_module(env: Environment) -> None:
    env.conn.execute(
        f'CREATE TABLE IF NOT EXISTS "{IR_MODULE_TABLE}" ('
        f'"name" text PRIMARY KEY, '
        f'"version" text NOT NULL, '
        f'"installed_at" timestamptz NOT NULL DEFAULT now())'
    )


def _installed_module_names(env: Environment) -> set[str]:
    _ensure_ir_module(env)
    rows = env.conn.execute(
        f'SELECT "name" FROM "{IR_MODULE_TABLE}"',
    ).fetchall()
    return {r[0] for r in rows}


def specs_to_install(
    env: Environment,
    ordered: list[ModuleSpec],
    *,
    install_all: bool = False,
) -> list[ModuleSpec]:
    """Return the subset of *ordered* specs to load and install on this pass.

    By default (app/cron boot): on a fresh database every bundled module in
    ``pyvelm/modules/`` (``BOOTSTRAP_MODULES``) is installed; otherwise only
    rows already present in ``ir_module``. Pass ``install_all=True`` to also
    install discovered addons outside the bundled tree (``migrate --all``,
    demo scripts, integration tests).
    """
    if install_all:
        return ordered
    installed = _installed_module_names(env)
    if not installed:
        return [s for s in ordered if s.name in BOOTSTRAP_MODULES]
    return [s for s in ordered if s.name in installed]


def _installed_version(env: Environment, name: str) -> tuple[int, ...] | None:
    row = env.conn.execute(
        f'SELECT "version" FROM "{IR_MODULE_TABLE}" WHERE "name" = %s',
        [name],
    ).fetchone()
    if row is None:
        return None
    return tuple(int(p) for p in row[0].split("."))


def _setup_module_schema(spec: ModuleSpec, env: Environment) -> None:
    """Create just this module's tables, FKs, and junction tables.

    For brand-new models this is a full CREATE TABLE.  For models extended
    via `_inherit` the table already exists; `_setup_table` idempotently
    adds any new columns with ALTER TABLE ADD COLUMN IF NOT EXISTS.
    """
    registry = env.registry
    models = registry.models_of(spec.name)
    # Models extended (not owned) by this module — need column additions.
    extended = [
        registry[n]
        for n in registry._model_extensions.get(spec.name, [])
        if n in registry
    ]
    all_cls = models + extended
    for cls in all_cls:
        cls._setup_table(env.conn)
    for cls in all_cls:
        cls._setup_foreign_keys(env.conn, registry)
    created: set[str] = set()
    for cls in all_cls:
        cls._setup_relation_tables(env.conn, registry, created)


def _pad(v: tuple[int, ...], width: int = 3) -> tuple[int, ...]:
    """Right-pad a version tuple with zeros so (0, 1) compares equal to
    (0, 1, 0). Comparison-order matters because filenames may use either
    form."""
    return v + (0,) * max(0, width - len(v))


def _parse_migration_filename(stem: str) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    """`0_1_to_0_2` -> ((0, 1), (0, 2)). Returns None if it doesn't match."""
    if "_to_" not in stem:
        return None
    from_part, to_part = stem.split("_to_", 1)
    try:
        from_v = tuple(int(p) for p in from_part.split("_") if p)
        to_v = tuple(int(p) for p in to_part.split("_") if p)
    except ValueError:
        return None
    if not from_v or not to_v:
        return None
    return from_v, to_v


def _run_migrations(spec: ModuleSpec, env: Environment,
                    from_version: tuple[int, ...],
                    to_version: tuple[int, ...]) -> None:
    """Run migration scripts whose filename indicates a transition that
    falls strictly between `from_version` (exclusive) and `to_version`
    (inclusive). Convention: `<from>_to_<to>.py` with `_`-separated
    version parts (e.g. `0_1_to_0_2.py`). Each module must export
    `migrate(env)`. Files that don't match the convention raise."""
    if spec.migrations_package is None:
        return
    try:
        pkg = importlib.import_module(spec.migrations_package)
    except ImportError:
        return
    pkg_file = getattr(pkg, "__file__", None)
    if not pkg_file:
        return
    pkg_dir = Path(pkg_file).parent

    width = max(len(from_version), len(to_version), 3)
    fv = _pad(from_version, width)
    tv = _pad(to_version, width)

    applicable: list[tuple[tuple[int, ...], tuple[int, ...], Path]] = []
    for p in pkg_dir.glob("*.py"):
        if p.name == "__init__.py":
            continue
        parsed = _parse_migration_filename(p.stem)
        if parsed is None:
            raise ValueError(
                f"Migration {p} doesn't match the <from>_to_<to>.py "
                f"convention; rename it or move it elsewhere."
            )
        from_v, to_v = parsed
        from_v_p = _pad(from_v, width)
        to_v_p = _pad(to_v, width)
        # A migration is applicable if its transition fits inside the
        # version gap we're bridging. Equivalently: don't re-run anything
        # that ends at or before the recorded version, and don't run
        # anything whose target exceeds where we're heading.
        if to_v_p > fv and to_v_p <= tv:
            applicable.append((from_v_p, to_v_p, p))

    applicable.sort()
    for _, _, p in applicable:
        mod_name = f"{spec.migrations_package}.{p.stem}"
        m = importlib.import_module(mod_name)
        if hasattr(m, "migrate"):
            m.migrate(env)


def _load_data_files(spec: ModuleSpec) -> None:
    """Execute each path in `spec.data` and accumulate any VIEWS /
    VIEW_INHERITS lists they expose. Today only `.py` files are
    supported; future extensions (`.json`, `.yaml`) can dispatch on
    suffix.

    Populates `spec.views` and `spec.view_inherits` so the subsequent
    `_sync_*` calls have a single source of truth regardless of where
    the declarations live on disk.
    """
    if not spec.data or spec.package_path is None:
        return
    views: list[dict[str, Any]] = []
    inherits: list[dict[str, Any]] = []
    menus: list[dict[str, Any]] = []
    for rel_path in spec.data:
        path = spec.package_path / rel_path
        if not path.is_file():
            raise FileNotFoundError(
                f"Module {spec.name!r}: data file {rel_path!r} not found "
                f"under {spec.package_path}"
            )
        suffix = path.suffix.lower()
        if suffix == ".py":
            mod_name = (
                f"_pyvelm_data_{spec.name}_"
                + rel_path.replace("/", "_").replace(".py", "")
            )
            if mod_name in sys.modules:
                mod = importlib.reload(sys.modules[mod_name])
            else:
                spec_obj = importlib.util.spec_from_file_location(mod_name, path)
                if spec_obj is None or spec_obj.loader is None:
                    raise ImportError(f"Could not import data file {path}")
                mod = importlib.util.module_from_spec(spec_obj)
                spec_obj.loader.exec_module(mod)
            views.extend(getattr(mod, "VIEWS", []))
            inherits.extend(getattr(mod, "VIEW_INHERITS", []))
            menus.extend(getattr(mod, "MENUS", []))
        else:
            raise ValueError(
                f"Module {spec.name!r}: data file {rel_path!r} has unsupported "
                f"extension {suffix!r}. Only .py is supported today."
            )
    spec.views = views
    spec.view_inherits = inherits
    spec.menus = menus


def _sync_views(spec: ModuleSpec, env: Environment) -> None:
    """Upsert this module's declared base views as `ir.ui.view` records.

    View identity is `(module, name)`. Arch goes through `normalize_arch`
    so the stored form has dict-shaped list entries — the addressing
    convention for inheritance operations.
    """
    if not spec.views:
        return
    if "ir.ui.view" not in env.registry:
        return
    from .views import normalize_arch

    View = env["ir.ui.view"]
    for v in spec.views:
        required = {"name", "model", "view_type", "arch"}
        missing = required - v.keys()
        if missing:
            raise ValueError(
                f"Module {spec.name!r}: view {v.get('name')!r} missing "
                f"keys {sorted(missing)}"
            )
        arch = v["arch"]
        if isinstance(arch, str):
            arch_obj = json.loads(arch)
        else:
            arch_obj = arch
        arch_normalized = normalize_arch(arch_obj, v["view_type"])
        existing = View.search([
            ("module", "=", spec.name),
            ("name", "=", v["name"]),
        ])
        vals = {
            "module": spec.name,
            "name": v["name"],
            "model": v["model"],
            "view_type": v["view_type"],
            "arch": json.dumps(arch_normalized),
            "priority": v.get("priority", 16),
        }
        if existing:
            existing.write(vals)
        else:
            View.create(vals)


def _sync_view_inherits(spec: ModuleSpec, env: Environment) -> None:
    """Upsert this module's view extension records.

    A VIEW_INHERITS entry references its parent by `<module>.<name>`;
    we look up the parent and persist a new ir.ui.view with `inherit_id`
    set. model/view_type are auto-filled from the parent so authoring
    extensions stays terse.
    """
    if not spec.view_inherits:
        return
    if "ir.ui.view" not in env.registry:
        return
    View = env["ir.ui.view"]
    for v in spec.view_inherits:
        required = {"name", "inherit", "operations"}
        missing = required - v.keys()
        if missing:
            raise ValueError(
                f"Module {spec.name!r}: view inherit {v.get('name')!r} "
                f"missing keys {sorted(missing)}"
            )
        parent_ref = v["inherit"]
        if "." not in parent_ref:
            raise ValueError(
                f"Inherit reference {parent_ref!r} must be 'module.name'"
            )
        parent_module, parent_name = parent_ref.split(".", 1)
        parent = View.search([
            ("module", "=", parent_module),
            ("name", "=", parent_name),
        ])
        if not parent:
            raise ValueError(
                f"Module {spec.name!r}: view inherit references "
                f"{parent_ref!r} which is not (yet) installed."
            )
        parent.ensure_one()
        existing = View.search([
            ("module", "=", spec.name),
            ("name", "=", v["name"]),
        ])
        vals = {
            "module": spec.name,
            "name": v["name"],
            "model": parent.model,           # auto-fill from parent
            "view_type": parent.view_type,
            "arch": None,
            "priority": v.get("priority", 16),
            "inherit_id": parent.id,
            "operations": json.dumps(v["operations"]),
        }
        if existing:
            existing.write(vals)
        else:
            View.create(vals)


def _menu_sync_order(menus: list, module: str) -> list:
    """Sort menus so every parent in *module* is upserted before its children."""
    by_name = {m["name"]: m for m in menus}
    depth_cache: dict[str, int] = {}

    def depth(entry: dict) -> int:
        name = entry["name"]
        if name in depth_cache:
            return depth_cache[name]
        parent_ref = entry.get("parent")
        if not parent_ref:
            depth_cache[name] = 0
            return 0
        if "." not in parent_ref:
            parent_name = parent_ref
            external = True
        else:
            pmod, parent_name = parent_ref.split(".", 1)
            external = pmod != module
        if external:
            depth_cache[name] = 1
            return 1
        parent_entry = by_name.get(parent_name)
        if parent_entry is None:
            depth_cache[name] = 1
            return 1
        d = depth(parent_entry) + 1
        depth_cache[name] = d
        return d

    return sorted(
        menus,
        key=lambda m: (depth(m), m.get("sequence", 10), m.get("label", "")),
    )


def _sync_menus(spec: ModuleSpec, env: Environment) -> None:
    """Upsert this module's MENUS as `ir.ui.menu` records.

    Identity is `(module, name)`. The optional `parent` key references
    another menu by `<module>.<name>` and is resolved to `parent_id`
    here — the parent must already be installed (i.e. live in this
    module or in a dep). Modules are installed in topo order, so the
    only intra-module concern is ordering: parents must be upserted
    before children (including level 3 under a nested group).
    """
    if not spec.menus:
        return
    if "ir.ui.menu" not in env.registry:
        return
    Menu = env["ir.ui.menu"]
    ordered = _menu_sync_order(spec.menus, spec.name)
    for m in ordered:
        required = {"name", "label"}
        missing = required - m.keys()
        if missing:
            raise ValueError(
                f"Module {spec.name!r}: menu {m.get('name')!r} missing "
                f"keys {sorted(missing)}"
            )
        parent_ref = m.get("parent")
        parent_id = None
        if parent_ref:
            if "." not in parent_ref:
                raise ValueError(
                    f"Menu parent {parent_ref!r} must be '<module>.<name>'"
                )
            p_mod, p_name = parent_ref.split(".", 1)
            parent = Menu.search([("module", "=", p_mod), ("name", "=", p_name)])
            if not parent:
                raise ValueError(
                    f"Module {spec.name!r}: menu {m['name']!r} references "
                    f"parent {parent_ref!r} which is not (yet) installed."
                )
            parent.ensure_one()
            parent_id = parent.id
        vals = {
            "module": spec.name,
            "name": m["name"],
            "label": m["label"],
            "parent_id": parent_id,
            "sequence": m.get("sequence", 10),
            "href": m.get("href"),
            "icon": m.get("icon"),
            "active": m.get("active", True),
            "access_model": m.get("access_model"),
            "access_perm": m.get("access_perm"),
            "access_policy": m.get("access_policy"),
            "dev_only": bool(m.get("dev_only", False)),
        }
        existing = Menu.search([
            ("module", "=", spec.name),
            ("name", "=", m["name"]),
        ])
        if existing:
            existing.write(vals)
        else:
            Menu.create(vals)


def install(specs: list[ModuleSpec], env: Environment) -> list[dict]:
    """Install or upgrade each module, in `specs` order, atomically per
    module. Models must already be loaded into `env.registry`.

    Returns one result dict per spec with keys ``name``, ``schema``,
    ``views``, ``menus`` (human-readable summaries for the Apps UI).
    """
    from . import db_autogen

    with env.transaction():
        _ensure_ir_module(env)
    results: list[dict] = []
    for spec in specs:
        with env.transaction():
            current = _installed_version(env, spec.name)
            schema_note = ""
            if current is None:
                _setup_module_schema(spec, env)
                applied = db_autogen.apply_schema_diff(env, spec.name)
                schema_note = applied.summary()
                if spec.install_hook is not None:
                    spec.install_hook(env)
                env.conn.execute(
                    f'INSERT INTO "{IR_MODULE_TABLE}" '
                    f'("name", "version") VALUES (%s, %s)',
                    [spec.name, spec.version_str],
                )
            else:
                _setup_module_schema(spec, env)
                if current < spec.version:
                    _run_migrations(spec, env, current, spec.version)
                # Sync hook before schema apply: idempotent backfills and
                # orphan cleanup (runs every upgrade/Sync, not only on bump).
                if spec.sync_hook is not None:
                    spec.sync_hook(env)
                applied = db_autogen.apply_schema_diff(env, spec.name)
                schema_note = applied.summary()
                env.conn.execute(
                    f'UPDATE "{IR_MODULE_TABLE}" SET "version" = %s, '
                    f'"installed_at" = now() WHERE "name" = %s',
                    [spec.version_str, spec.name],
                )
            # Load data files (views, menus) from disk — always reload
            # so Upgrade/Sync picks up new DATA without reinstall.
            _load_data_files(spec)
            view_count = len(spec.views)
            inherit_count = len(spec.view_inherits)
            menu_count = len(spec.menus)
            _sync_views(spec, env)
            _sync_view_inherits(spec, env)
            _sync_menus(spec, env)
            results.append(
                {
                    "name": spec.name,
                    "schema": schema_note,
                    "views": (
                        f"{view_count} view(s)"
                        + (
                            f", {inherit_count} inherit(s)"
                            if inherit_count
                            else ""
                        )
                    ),
                    "menus": f"{menu_count} menu(s)",
                }
            )

    # Build cross-model indexes once everything's loaded.
    env.registry._build_o2m_inverse_index()
    env.registry._build_m2o_referrers_index()
    env.registry._build_m2m_relation_index()
    env.registry._build_compute_graph()
    for cls in env.registry._models.values():
        cls._validate_relations(env.registry)
    return results


def load_and_install(
    roots: list[Path | str],
    env: Environment,
    *,
    install_all: bool = False,
) -> list[ModuleSpec]:
    """End-to-end: discover, resolve, load models, install/sync.

    By default every bundled module under ``pyvelm/modules/`` is installed on
    a fresh database; other discovered addons stay available in **Apps** until
    installed. Pass ``install_all=True`` to install every discovered module
    (used by ``pyvelm migrate --all`` and demo scripts). Returns the specs
    that were loaded and installed/synced.
    """
    from pyvelm.policies import register_builtin_policies

    register_builtin_policies()
    specs = discover(roots)
    ordered = resolve_order(specs)
    to_install = specs_to_install(env, ordered, install_all=install_all)
    for spec in to_install:
        _load_models(spec, env.registry)
    install(to_install, env)
    return to_install


def register_web_routes(app, roots: list[Path | str]) -> None:
    """Mount each discovered module's ``WEB_ROUTES`` registrar on *app*.

    Modules declare ``WEB_ROUTES = "pkg.web:register_routes"`` in
    ``__pyvelm__.py``. The callable receives the FastAPI app (with
    ``app.state.registry`` and ``app.state.pool`` already set) and should
    attach routes, static mounts, or routers. Registrars run in dependency
    order after core ``create_app`` routes are registered.

    Only **installed** modules register routes — uninstalled addons stay
    visible in **Apps** but do not mount HTTP handlers until installed.
    """
    from pyvelm import Environment

    specs = discover(roots)
    ordered = resolve_order(specs)
    installed: set[str] | None = None
    if getattr(app.state, "pool", None) is not None:
        with app.state.pool.connection() as conn:
            env = Environment(conn, registry=app.state.registry, uid=None)
            installed = _installed_module_names(env)
    for spec in ordered:
        if installed is not None and spec.name not in installed:
            continue
        if not spec.web_routes:
            continue
        registrar = _import_attr(spec.web_routes)
        registrar(app)


# ---------------------------------------------------------------------------
# Console command discovery (Artisan-style)
# ---------------------------------------------------------------------------


def _iter_command_classes(mod: Any) -> list[type]:
    """Yield Command subclasses declared in an imported module."""
    from .console import Command

    found: list[type] = []
    for attr in vars(mod).values():
        if (
            isinstance(attr, type)
            and issubclass(attr, Command)
            and attr is not Command
            and not getattr(attr, "__abstractmethods__", None)
        ):
            found.append(attr)
    return found


def _load_commands_from_package(spec: ModuleSpec) -> list[type]:
    """Import ``<package>.commands`` or scan ``commands/*.py`` on disk."""
    classes: list[type] = []
    pkg_name = f"{spec.package}.commands"
    try:
        mod = importlib.import_module(pkg_name)
        classes.extend(_iter_command_classes(mod))
    except ModuleNotFoundError:
        pass
    if spec.package_path is None:
        return classes
    cmd_dir = spec.package_path / "commands"
    if not cmd_dir.is_dir():
        return classes
    seen = {c.__module__ + "." + c.__name__ for c in classes}
    for path in sorted(cmd_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = f"_pyvelm_cmd_{spec.name}_{path.stem}"
        spec_obj = importlib.util.spec_from_file_location(mod_name, path)
        if spec_obj is None or spec_obj.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec_obj)
        spec_obj.loader.exec_module(mod)
        for cls in _iter_command_classes(mod):
            key = cls.__module__ + "." + cls.__name__
            if key not in seen:
                seen.add(key)
                classes.append(cls)
    return classes


def discover_commands(
    roots: list[Path | str],
    registry: Any | None = None,
) -> Any:
    """Discover and register console commands from all modules under ``roots``.

    Returns a :class:`~pyvelm.console.CommandRegistry`. Does not require a
    database connection unless a command sets ``requires_db=True``.
    """
    from .console import CommandRegistry

    if registry is None:
        registry = CommandRegistry()
    specs = discover(roots)
    ordered = resolve_order(specs)
    for spec in ordered:
        for ref in spec.command_refs:
            cls = _import_attr(ref)
            if not isinstance(cls, type):
                raise TypeError(f"COMMANDS entry {ref!r} must be a Command class")
            registry.register(cls())
        for cls in _load_commands_from_package(spec):
            registry.register(cls())
    return registry
