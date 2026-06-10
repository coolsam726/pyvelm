"""Tiny pure helpers used by the ``geo_data`` module.

Hoisted out of ``pyvelm.modules.geo_data.hooks`` so unit tests can
import them without going through the poisoned
``pyvelm.modules`` namespace.
"""

from __future__ import annotations

import locale
import os

# Common IANA zones → ISO 3166-1 alpha-2 (install-time hint when
# ``PYVELM_GEO_COUNTRY`` is unset).
_TZ_COUNTRY_HINTS: dict[str, str] = {
    "Africa/Abidjan": "CI",
    "Africa/Accra": "GH",
    "Africa/Addis_Ababa": "ET",
    "Africa/Algiers": "DZ",
    "Africa/Cairo": "EG",
    "Africa/Casablanca": "MA",
    "Africa/Johannesburg": "ZA",
    "Africa/Kampala": "UG",
    "Africa/Lagos": "NG",
    "Africa/Nairobi": "KE",
    "Africa/Tunis": "TN",
    "America/Argentina/Buenos_Aires": "AR",
    "America/Bogota": "CO",
    "America/Chicago": "US",
    "America/Denver": "US",
    "America/Lima": "PE",
    "America/Los_Angeles": "US",
    "America/Mexico_City": "MX",
    "America/New_York": "US",
    "America/Sao_Paulo": "BR",
    "America/Toronto": "CA",
    "Asia/Bangkok": "TH",
    "Asia/Dubai": "AE",
    "Asia/Hong_Kong": "HK",
    "Asia/Jakarta": "ID",
    "Asia/Kolkata": "IN",
    "Asia/Manila": "PH",
    "Asia/Riyadh": "SA",
    "Asia/Seoul": "KR",
    "Asia/Shanghai": "CN",
    "Asia/Singapore": "SG",
    "Asia/Tokyo": "JP",
    "Australia/Sydney": "AU",
    "Europe/Amsterdam": "NL",
    "Europe/Berlin": "DE",
    "Europe/Istanbul": "TR",
    "Europe/London": "GB",
    "Europe/Madrid": "ES",
    "Europe/Paris": "FR",
    "Europe/Rome": "IT",
    "Europe/Stockholm": "SE",
    "Europe/Warsaw": "PL",
    "Europe/Zurich": "CH",
    "Pacific/Auckland": "NZ",
}


def detect_geo_country_code() -> str | None:
    """Best-effort ISO alpha-2 for bootstrap geography seeding.

    Resolution order: ``PYVELM_GEO_COUNTRY`` → ``TZ`` hint table →
    locale territory (``en_US`` → ``US``).
    """
    explicit = (os.environ.get("PYVELM_GEO_COUNTRY") or "").strip().upper()
    if len(explicit) == 2 and explicit.isalpha():
        return explicit
    tz = (os.environ.get("TZ") or "").strip()
    if tz and tz in _TZ_COUNTRY_HINTS:
        return _TZ_COUNTRY_HINTS[tz]
    try:
        loc = locale.getlocale() or locale.getdefaultlocale()
        tag = (loc[0] or "") if loc else ""
        if tag:
            parts = tag.replace("-", "_").split("_")
            if len(parts) >= 2:
                territory = parts[-1].upper()
                if len(territory) == 2 and territory.isalpha():
                    return territory
    except Exception:  # noqa: BLE001
        pass
    return None


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
