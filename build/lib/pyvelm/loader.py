"""Module discovery, dependency resolution, and install/migrate.

A pyvelm module is a Python package containing a `__pyvelm__.py` manifest
with at least:

    NAME = "partners"
    VERSION = (0, 1, 0)
    DEPENDS = ["base"]

Optionally:

    MODELS_PACKAGE = "myapp.partners.models"   # defaults to <pkg>.models
    INSTALL_HOOK = "myapp.partners.hooks:install"
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


@dataclass
class ModuleSpec:
    name: str
    version: tuple[int, ...]
    depends: list[str]
    package: str                       # import path of the module package
    models_package: str
    migrations_package: str | None
    install_hook: Callable | None = None
    package_path: Path | None = None
    data: list[str] = dc_field(default_factory=list)
    # Optional human-facing manifest fields. Drive the Apps catalog UI;
    # none of them affect install behavior.
    summary: str = ""                  # one-line tagline
    description: str = ""              # longer prose (Markdown-ish)
    category: str = ""                 # grouping label, e.g. "CRM" or "Admin"
    author: str = ""                   # free-form
    icon: str = ""                     # raw inline SVG markup or empty
    # Filled during install from the data files.
    views: list[dict[str, Any]] = dc_field(default_factory=list)
    view_inherits: list[dict[str, Any]] = dc_field(default_factory=list)
    menus: list[dict[str, Any]] = dc_field(default_factory=list)
    # Filled by the loader during the import pass.
    loaded: bool = False

    @property
    def version_str(self) -> str:
        return ".".join(str(p) for p in self.version)


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
    data = list(getattr(mod, "DATA", []))

    return ModuleSpec(
        name=name,
        version=version,
        depends=depends,
        package=package,
        models_package=models_pkg,
        migrations_package=migrations_pkg,
        install_hook=install_hook,
        package_path=pkg_path,
        data=data,
        summary=getattr(mod, "SUMMARY", ""),
        description=getattr(mod, "DESCRIPTION", ""),
        category=getattr(mod, "CATEGORY", ""),
        author=getattr(mod, "AUTHOR", ""),
        icon=getattr(mod, "ICON", ""),
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


def _load_models(spec: ModuleSpec, registry: Registry) -> None:
    """Import a module's models package under the active registry, tagging
    every newly-registered model with the module name.

    New models (not in registry before the import) are tagged with this
    module as their owner.  Existing models whose registry class changed
    (replaced by a `_inherit` extension) are recorded in
    `registry._model_extensions` so `_setup_module_schema` can add their
    new columns.
    """
    with registry.activate():
        before_models: dict[str, type] = dict(registry._models)
        importlib.import_module(spec.models_package)
        for model_name, cls in registry._models.items():
            if model_name not in before_models:
                # Brand-new model defined by this module.
                registry._model_module[model_name] = spec.name
            elif cls is not before_models[model_name]:
                # Existing model extended via _inherit by this module.
                registry._model_extensions.setdefault(spec.name, []).append(
                    model_name
                )
    spec.loaded = True


def _ensure_ir_module(env: Environment) -> None:
    env.conn.execute(
        f'CREATE TABLE IF NOT EXISTS "{IR_MODULE_TABLE}" ('
        f'"name" text PRIMARY KEY, '
        f'"version" text NOT NULL, '
        f'"installed_at" timestamptz NOT NULL DEFAULT now())'
    )


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


def _sync_menus(spec: ModuleSpec, env: Environment) -> None:
    """Upsert this module's MENUS as `ir.ui.menu` records.

    Identity is `(module, name)`. The optional `parent` key references
    another menu by `<module>.<name>` and is resolved to `parent_id`
    here — the parent must already be installed (i.e. live in this
    module or in a dep). Modules are installed in topo order, so the
    only intra-module concern is that a child appears after its parent
    in the MENUS list — sorting by absence-of-parent keeps that
    automatic.
    """
    if not spec.menus:
        return
    if "ir.ui.menu" not in env.registry:
        return
    Menu = env["ir.ui.menu"]
    # Roots first so children in the same module can resolve their parent.
    ordered = sorted(spec.menus, key=lambda m: 0 if not m.get("parent") else 1)
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
        }
        existing = Menu.search([
            ("module", "=", spec.name),
            ("name", "=", m["name"]),
        ])
        if existing:
            existing.write(vals)
        else:
            Menu.create(vals)


def install(specs: list[ModuleSpec], env: Environment) -> None:
    """Install or upgrade each module, in `specs` order, atomically per
    module. Models must already be loaded into `env.registry`."""
    with env.transaction():
        _ensure_ir_module(env)
    for spec in specs:
        with env.transaction():
            current = _installed_version(env, spec.name)
            if current is None:
                _setup_module_schema(spec, env)
                if spec.install_hook is not None:
                    spec.install_hook(env)
                env.conn.execute(
                    f'INSERT INTO "{IR_MODULE_TABLE}" '
                    f'("name", "version") VALUES (%s, %s)',
                    [spec.name, spec.version_str],
                )
            elif current < spec.version:
                _run_migrations(spec, env, current, spec.version)
                env.conn.execute(
                    f'UPDATE "{IR_MODULE_TABLE}" SET "version" = %s, '
                    f'"installed_at" = now() WHERE "name" = %s',
                    [spec.version_str, spec.name],
                )
            # Load data files (views, future seed records) and sync
            # them. Runs every install pass so re-declaring overwrites
            # the previous state. Base views first so extensions in
            # dependent modules can resolve their parents.
            _load_data_files(spec)
            _sync_views(spec, env)
            _sync_view_inherits(spec, env)
            _sync_menus(spec, env)

    # Build the compute graph once everything's loaded — depends paths
    # may cross module boundaries.
    env.registry._build_compute_graph()
    for cls in env.registry._models.values():
        cls._validate_relations(env.registry)


def load_and_install(roots: list[Path | str], env: Environment) -> list[ModuleSpec]:
    """End-to-end: discover, resolve, load models, install. Returns the
    ordered ModuleSpecs that were processed."""
    specs = discover(roots)
    ordered = resolve_order(specs)
    for spec in ordered:
        _load_models(spec, env.registry)
    install(ordered, env)
    return ordered
