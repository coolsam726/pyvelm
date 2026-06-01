"""Laravel-style database seeders for pyvelm modules.

Each seeder is a class with a ``run_instance(env, **context)`` method.
Compose seeders with :meth:`Seeder.call` (same idea as
``$this->call(CountrySeeder::class)`` in Laravel).

Register seeders in ``<module>/seeders/__init__.py``::

    from .database import DatabaseSeeder

    SEEDERS = [DatabaseSeeder]

The loader discovers that list automatically (or runs ``DatabaseSeeder``
when ``SEEDERS`` is omitted). Override with an explicit ``SEEDERS`` list
in ``__pyvelm__.py`` when needed.

The loader runs them on **install**, **upgrade**, and **Apps Sync**
(after ``INSTALL_HOOK`` / ``SYNC_HOOK`` and schema apply). Implement
``run_instance`` to be **idempotent** — search by natural keys, insert
only missing rows, patch when upstream data changes.

Re-run manually via :func:`run_seeders` or ``pyvelm db seed``.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, ClassVar

log = logging.getLogger("pyvelm.seeding")

_DEFAULT_ENTRY_SEEDERS = ("DatabaseSeeder",)


class Seeder:
    """Base class for module seed data.

    Subclasses must tolerate repeated runs: the loader invokes manifest
    seeders on every install, upgrade, and Sync pass.
    """

    #: When False, :meth:`run` logs and returns without calling ``run_instance``.
    enabled: ClassVar[bool] = True

    @classmethod
    def run(cls, env, **context: Any) -> Any:
        """Instantiate and run this seeder (entry point for loader / CLI)."""
        if not cls.enabled:
            log.info("%s: skipped (disabled)", cls.__name__)
            return None
        if not cls.should_run(env, **context):
            log.info("%s: skipped (should_run returned False)", cls.__name__)
            return None
        return cls().run_instance(env, **context)

    @classmethod
    def should_run(cls, env, **context: Any) -> bool:  # noqa: ARG003
        """Override to skip when optional deps or data are already present."""
        return True

    def run_instance(self, env, **context: Any) -> Any:
        """Populate the database. Override in subclasses."""
        raise NotImplementedError(f"{type(self).__name__}.run_instance")

    def call(self, env, seeder: type[Seeder] | str, **context: Any) -> Any:
        """Run another seeder class (or ``\"pkg.mod:Class\"`` dotted path)."""
        target = resolve_seeder(seeder) if isinstance(seeder, str) else seeder
        return target.run(env, **context)


def normalize_seeder_ref(
    ref: Any,
    *,
    package: str,
    seeders_module: str | None = None,
) -> str:
    """Turn a manifest/``seeders`` entry into ``package.module:Class``."""
    if isinstance(ref, str):
        text = ref.strip()
        if not text:
            raise ValueError("empty seeder reference")
        if ":" in text:
            return text
        mod = seeders_module or f"{package}.seeders"
        return f"{mod}:{text}"
    if isinstance(ref, type) and issubclass(ref, Seeder):
        return f"{ref.__module__}:{ref.__qualname__}"
    raise TypeError(f"seeder reference must be str or Seeder subclass, not {type(ref)!r}")


def discover_seeders(package: str, package_path: Path | None) -> list[str]:
    """Load ``SEEDERS`` from ``<package>/seeders/__init__.py`` when present."""
    if package_path is None:
        return []
    init_py = package_path / "seeders" / "__init__.py"
    if not init_py.is_file():
        return []
    seeders_module = f"{package}.seeders"
    mod = importlib.import_module(seeders_module)
    explicit = getattr(mod, "SEEDERS", None)
    if explicit is not None:
        return [
            normalize_seeder_ref(item, package=package, seeders_module=seeders_module)
            for item in explicit
        ]
    for name in _DEFAULT_ENTRY_SEEDERS:
        candidate = getattr(mod, name, None)
        if isinstance(candidate, type) and issubclass(candidate, Seeder):
            return [f"{seeders_module}:{name}"]
    return []


def resolve_module_seeders(
    package: str,
    package_path: Path | None,
    manifest_seeders: list[Any],
) -> list[str]:
    """Manifest ``SEEDERS`` wins when set; otherwise discover ``seeders/``."""
    if manifest_seeders:
        return [normalize_seeder_ref(item, package=package) for item in manifest_seeders]
    return discover_seeders(package, package_path)


def resolve_seeder(dotted: str) -> type[Seeder]:
    """Import a seeder class from ``package.module:Class`` or ``package.module.Class``."""
    if ":" in dotted:
        mod_name, attr = dotted.rsplit(":", 1)
    else:
        mod_name, attr = dotted.rsplit(".", 1)
    mod = importlib.import_module(mod_name)
    target = getattr(mod, attr)
    if not isinstance(target, type) or not issubclass(target, Seeder):
        raise TypeError(f"{dotted!r} is not a Seeder subclass")
    return target


def run_seeders(env, seeders: list[str], *, module: str | None = None) -> list[Any]:
    """Run every dotted seeder path; returns each seeder's return value."""
    results: list[Any] = []
    for dotted in seeders:
        log.info("Running seeder %s%s", dotted, f" ({module})" if module else "")
        results.append(resolve_seeder(dotted).run(env))
    return results
