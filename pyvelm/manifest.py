"""Fluent builder for ``__pyvelm__.py`` module manifests (velmphp-style).

Assign the builder to a module-level ``manifest`` name::

    from pyvelm.manifest import Manifest

    manifest = (
        Manifest.make("partners")
        .version(0, 4, 0)
        .depends("base")
        .data("views/partner.py", "views/menu.py")
        .install_hook("partners.hooks:install")
        .summary("Companies, contacts, and the partner directory.")
        .category("Business")
    )

Legacy module-level constants (``NAME``, ``VERSION``, ``DEPENDS``, …) remain
supported for older manifests.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any


def _hook_reference(target: str | type | Callable[..., Any], method: str) -> str:
    if isinstance(target, str):
        return target.strip()
    if isinstance(target, type):
        return f"{target.__module__}:{method}"
    mod = getattr(target, "__module__", "") or ""
    qual = getattr(target, "__qualname__", getattr(target, "__name__", ""))
    return f"{mod}:{qual}"


def _model_reference(model: str | type) -> str:
    if isinstance(model, str):
        return model.strip()
    return f"{model.__module__}.{model.__qualname__}"


class Manifest:
    """Fluent builder returned from ``Manifest.make(name)``."""

    def __init__(self, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Module name must not be empty.")
        self._name = name
        self._version: tuple[int, ...] = ()
        self._depends: list[str] = []
        self._data: list[str] = []
        self._models: list[str] = []
        self._seeders: list[str] = []
        self._commands: list[str] = []
        self._summary = ""
        self._description = ""
        self._display_name = ""
        self._category = ""
        self._author = ""
        self._icon = ""
        self._package = ""
        self._models_package = ""
        self._migrations_package = ""
        self._install_hook: str | None = None
        self._sync_hook: str | None = None
        self._web_routes: str | None = None
        self._catalog_access_model = ""
        self._catalog_access_perm = ""
        self._catalog_access_policy = ""
        self._bootstrap = True

    @classmethod
    def make(cls, name: str) -> Manifest:
        return cls(name)

    def version(
        self,
        first: int | Sequence[int],
        *rest: int,
    ) -> Manifest:
        if isinstance(first, Sequence) and not isinstance(first, (str, bytes)):
            if rest:
                raise ValueError(
                    "Pass either version(0, 1, 0) or version((0, 1, 0)), not both."
                )
            parts = tuple(int(p) for p in first)
        else:
            parts = (int(first), *rest)
        if not parts:
            raise ValueError("version() requires at least one segment.")
        self._version = parts
        return self

    def depends(self, *modules: str) -> Manifest:
        self._depends = list(modules)
        return self

    def data(self, *paths: str) -> Manifest:
        self._data = list(paths)
        return self

    def models(self, *model_classes: str | type) -> Manifest:
        self._models = [_model_reference(m) for m in model_classes]
        return self

    def seeders(self, *seeder_classes: str | type) -> Manifest:
        self._seeders = [_model_reference(s) for s in seeder_classes]
        return self

    def commands(self, *command_refs: str) -> Manifest:
        self._commands = list(command_refs)
        return self

    def summary(self, summary: str) -> Manifest:
        self._summary = summary
        return self

    def description(self, description: str) -> Manifest:
        self._description = description
        return self

    def display_name(self, display_name: str) -> Manifest:
        self._display_name = display_name
        return self

    def category(self, category: str) -> Manifest:
        self._category = category
        return self

    def author(self, author: str) -> Manifest:
        self._author = author
        return self

    def icon(self, icon: str) -> Manifest:
        self._icon = icon
        return self

    def package(self, package: str) -> Manifest:
        self._package = package.strip()
        return self

    def models_package(self, models_package: str) -> Manifest:
        self._models_package = models_package.strip()
        return self

    def migrations_package(self, migrations_package: str) -> Manifest:
        self._migrations_package = migrations_package.strip()
        return self

    def install_hook(
        self,
        target: str | type | Callable[..., Any],
        method: str = "install",
    ) -> Manifest:
        self._install_hook = _hook_reference(target, method)
        return self

    def sync_hook(
        self,
        target: str | type | Callable[..., Any],
        method: str = "sync",
    ) -> Manifest:
        self._sync_hook = _hook_reference(target, method)
        return self

    def web_routes(self, target: str | Callable[..., Any]) -> Manifest:
        if isinstance(target, str):
            self._web_routes = target.strip() or None
        else:
            mod = getattr(target, "__module__", "") or ""
            qual = getattr(target, "__qualname__", getattr(target, "__name__", ""))
            self._web_routes = f"{mod}:{qual}"
        return self

    def catalog_access(
        self,
        model: str,
        perm: str = "read",
        *,
        policy: str = "",
    ) -> Manifest:
        self._catalog_access_model = model
        self._catalog_access_perm = perm
        self._catalog_access_policy = policy
        return self

    def bootstrap(self, value: bool = True) -> Manifest:
        """When ``False``, the module is opt-in via Apps (not fresh-DB bootstrap)."""
        self._bootstrap = value
        return self

    def to_dict(self) -> dict[str, Any]:
        if not self._version:
            raise ValueError(f"Manifest for {self._name!r} is missing version().")
        out: dict[str, Any] = {
            "NAME": self._name,
            "VERSION": self._version,
            "DEPENDS": list(self._depends),
            "DATA": list(self._data),
        }
        if self._models:
            out["MODELS"] = list(self._models)
        if self._seeders:
            out["SEEDERS"] = list(self._seeders)
        if self._commands:
            out["COMMANDS"] = list(self._commands)
        if self._summary:
            out["SUMMARY"] = self._summary
        if self._description:
            out["DESCRIPTION"] = self._description
        if self._display_name:
            out["DISPLAY_NAME"] = self._display_name
        if self._category:
            out["CATEGORY"] = self._category
        if self._author:
            out["AUTHOR"] = self._author
        if self._icon:
            out["ICON"] = self._icon
        if self._package:
            out["PACKAGE"] = self._package
        if self._models_package:
            out["MODELS_PACKAGE"] = self._models_package
        if self._migrations_package:
            out["MIGRATIONS_PACKAGE"] = self._migrations_package
        if self._install_hook:
            out["INSTALL_HOOK"] = self._install_hook
        if self._sync_hook:
            out["SYNC_HOOK"] = self._sync_hook
        if self._web_routes:
            out["WEB_ROUTES"] = self._web_routes
        if self._catalog_access_model:
            out["CATALOG_ACCESS_MODEL"] = self._catalog_access_model
        if self._catalog_access_perm:
            out["CATALOG_ACCESS_PERM"] = self._catalog_access_perm
        if self._catalog_access_policy:
            out["CATALOG_ACCESS_POLICY"] = self._catalog_access_policy
        if not self._bootstrap:
            out["BOOTSTRAP"] = False
        return out


def bump_version_in_manifest_text(
    text: str,
    old_version: tuple[int, ...],
    new_version: tuple[int, ...],
) -> str | None:
    """Replace *old_version* with *new_version* in manifest source text.

    Supports legacy ``VERSION = (0, 1, 0)`` and fluent ``.version(0, 1, 0)``.
    Returns the updated text, or ``None`` when no match is found.
    """
    import re

    old_repr = repr(old_version)
    if old_repr in text:
        return text.replace(old_repr, repr(new_version), 1)

    inner = r"\s*,\s*".join(str(p) for p in old_version)
    pattern = rf"\.version\s*\(\s*{inner}\s*\)"
    match = re.search(pattern, text)
    if not match:
        return None
    new_inner = ", ".join(str(p) for p in new_version)
    return text[: match.start()] + f".version({new_inner})" + text[match.end() :]


__all__ = ["Manifest", "bump_version_in_manifest_text"]
