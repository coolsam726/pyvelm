"""Heroicons integration — resolve menu ``icon='home'`` names to SVG markup."""
from __future__ import annotations

from markupsafe import Markup

try:
    from heroicons import IconDoesNotExist
    from heroicons.jinja import (
        heroicon_micro,
        heroicon_mini,
        heroicon_outline,
        heroicon_solid,
    )
except ImportError:  # pragma: no cover - optional until package install
    IconDoesNotExist = Exception  # type: ignore[misc, assignment]
    heroicon_outline = heroicon_solid = heroicon_mini = heroicon_micro = None  # type: ignore

_VARIANT_RENDERERS = {
    "outline": heroicon_outline,
    "solid": heroicon_solid,
    "mini": heroicon_mini,
    "micro": heroicon_micro,
}

_FALLBACK_ICON = "question-mark-circle"


def _normalize_icon_name(name: str) -> str:
    return name.strip().replace("_", "-").lower()


def _parse_icon_spec(spec: str) -> tuple[str, str]:
    """Return ``(variant, name)`` from ``home``, ``solid:home``, etc."""
    text = spec.strip()
    if ":" in text:
        variant, _, name = text.partition(":")
        variant = variant.strip().lower()
        name = name.strip()
        if variant in _VARIANT_RENDERERS and name:
            return variant, _normalize_icon_name(name)
    return "outline", _normalize_icon_name(text)


def resolve_icon(
    spec: str | None,
    *,
    css_class: str = "w-4 h-4",
    fallback: bool = True,
) -> Markup | None:
    """Render a menu/template icon from a Heroicons name or legacy SVG string.

    * ``"home"`` → outline ``home`` (default style for sidebar menus)
    * ``"solid:shield-check"`` → solid variant
    * ``"mini:bell"`` / ``"micro:bell"`` → smaller variants
    * Strings starting with ``<svg`` are returned unchanged (backward compatible)
    """
    if spec is None:
        return None
    text = str(spec).strip()
    if not text:
        return None
    if text.lstrip().startswith("<"):
        return Markup(text)

    if heroicon_outline is None:
        return None

    variant, name = _parse_icon_spec(text)
    renderer = _VARIANT_RENDERERS.get(variant) or heroicon_outline
    attrs = {"class": css_class}
    try:
        return Markup(renderer(name, **attrs))  # type: ignore[misc]
    except IconDoesNotExist:
        if not fallback or name == _FALLBACK_ICON:
            return None
        try:
            return Markup(heroicon_outline(_FALLBACK_ICON, **attrs))  # type: ignore[misc]
        except IconDoesNotExist:
            return None


def register_jinja_globals(env) -> None:
    """Expose ``heroicon`` and ``resolve_icon`` on a Jinja environment."""
    if heroicon_outline is None:
        return
    env.globals["heroicon"] = resolve_icon
    env.globals.update(
        {
            "heroicon_outline": heroicon_outline,
            "heroicon_solid": heroicon_solid,
            "heroicon_mini": heroicon_mini,
            "heroicon_micro": heroicon_micro,
        }
    )
