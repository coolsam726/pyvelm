"""Tiny pure helpers used by the ``geo_data`` module.

Hoisted out of ``pyvelm.modules.geo_data.hooks`` so unit tests can
import them without going through the poisoned
``pyvelm.modules`` namespace.
"""

from __future__ import annotations


def flag_emoji(iso_alpha2: str | None) -> str:
    """Return the regional-indicator emoji for an ISO 3166-1 alpha-2 code.

    Returns an empty string for None / wrong length / non-alpha inputs
    so callers can pass it through to template rendering without
    extra guard clauses.
    """
    if not iso_alpha2 or len(iso_alpha2) != 2 or not iso_alpha2.isalpha():
        return ""
    return "".join(
        chr(0x1F1E6 + (ord(c) - ord("A"))) for c in iso_alpha2.upper()
    )


def geo_packages_available() -> bool:
    """True when the optional ``[geo]`` deps are importable."""
    try:
        import geonamescache  # noqa: F401
        import pycountry  # noqa: F401
        return True
    except ImportError:
        return False


def require_geo_packages() -> None:
    """Raise a friendly error when the geo extras aren't installed."""
    if not geo_packages_available():
        raise RuntimeError(
            "geo_data needs the geo extras: pip install pyvelm[geo]"
        )
