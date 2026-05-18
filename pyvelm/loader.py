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
import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Callable

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

    return ModuleSpec(
        name=name,
        version=version,
        depends=depends,
        package=package,
        models_package=models_pkg,
        migrations_package=migrations_pkg,
        install_hook=install_hook,
        package_path=pkg_path,
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
    every newly-registered model with the module name."""
    with registry.activate():
        before = set(registry._models)
        importlib.import_module(spec.models_package)
        for new_name in set(registry._models) - before:
            registry._model_module[new_name] = spec.name
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
    """Create just this module's tables, FKs, and junction tables."""
    from .fields import Many2many

    registry = env.registry
    models = registry.models_of(spec.name)
    for cls in models:
        cls._setup_table(env.conn)
    for cls in models:
        cls._setup_foreign_keys(env.conn, registry)
    created: set[str] = set()
    for cls in models:
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
            # else: same version, no-op.

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
