"""Per-company typography — Google Fonts with safe CSS generation."""
from __future__ import annotations

import os
import re

DEFAULT_FONT_FAMILY = "Inter"
_FONT_FAMILY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 \-&]{0,78}[A-Za-z0-9]?$")
_DEFAULT_WEIGHTS = (300, 400, 500, 600, 700)

# Curated Google Fonts for the admin UI (loaded globally via ``_head_fonts.html``).
UI_FONT_FAMILIES: tuple[str, ...] = (
    "Roboto",
    "Open Sans",
    "Lato",
    "Montserrat",
    "Source Sans 3",
    "Nunito",
    "Poppins",
    "Raleway",
    "Merriweather",
    "Playfair Display",
    "Oswald",
    "Work Sans",
    "DM Sans",
    "IBM Plex Sans",
)

UI_FONT_FAMILY_CHOICES: list[tuple[str, str]] = [
    ("", "Default (Inter)"),
    *((f, f) for f in UI_FONT_FAMILIES),
]


def normalize_font_family(name: str | None) -> str:
    """Return a sanitized Google Font family name, or ``""`` if invalid."""
    if name is None:
        return ""
    text = str(name).strip()
    if not text:
        return ""
    if text.lower() in ("default", "inter"):
        return ""
    if not _FONT_FAMILY_RE.match(text):
        return ""
    return text


def google_fonts_stylesheet_url(
    family: str,
    *,
    weights: tuple[int, ...] = _DEFAULT_WEIGHTS,
) -> str:
    """Build a Google Fonts CSS2 URL for *family* (defaults to Inter)."""
    name = normalize_font_family(family)
    if not name:
        raw = (family or "").strip()
        if not raw or raw.lower() in ("inter", "default"):
            name = DEFAULT_FONT_FAMILY
        else:
            return ""
    family_param = name.replace(" ", "+")
    w = ";".join(str(weight) for weight in weights)
    return (
        f"https://fonts.googleapis.com/css2?family={family_param}:wght@{w}&display=swap"
    )


def company_font_css(family: str | None) -> str:
    """CSS overrides for Tailwind v4 theme font tokens + html/body."""
    name = normalize_font_family(family)
    if not name:
        return ""
    stack = f"'{name}', ui-sans-serif, system-ui, sans-serif"
    return (
        "/* pyvelm company font — generated from res.company.font_family */\n"
        "@layer theme {\n"
        "  :root, :host {\n"
        f"    --font-sans: {stack};\n"
        f"    --font-body: {stack};\n"
        f"    --default-font-family: {stack};\n"
        "  }\n"
        "}\n"
        "html, body {\n"
        f"  font-family: {stack};\n"
        "}"
    )


def _env_font_family() -> str:
    return normalize_font_family(os.environ.get("PYVELM_FONT_FAMILY", ""))


def resolve_branding_company_id(
    env,
    *,
    company_id: int | None = None,
) -> int | None:
    """Active company for branding: explicit id → cookie scope → user's home company."""
    if company_id is not None:
        return company_id
    if env is None:
        return None
    cid = env.company_id
    if cid is not None:
        return cid
    uid = getattr(env, "uid", None)
    if uid and "res.users" in env.registry and "res.company" in env.registry:
        try:
            env.prime_current_user_cache()
            user = env["res.users"].browse(uid)
            home = user.company_id
            if home:
                return home.id
        except Exception:
            pass
    return None


def resolve_font_family(*, company_value: str | None = None) -> str:
    """Resolved UI font: company row → ``PYVELM_FONT_FAMILY`` → Inter."""
    from_co = normalize_font_family(company_value)
    if from_co:
        return from_co
    from_env = _env_font_family()
    if from_env:
        return from_env
    return DEFAULT_FONT_FAMILY


def company_font_context(env, *, company_id: int | None = None) -> dict[str, str]:
    """Template variables for font link + CSS overrides."""
    empty = {
        "company_font_family": DEFAULT_FONT_FAMILY,
        "company_font_stylesheet_url": google_fonts_stylesheet_url(DEFAULT_FONT_FAMILY),
        "company_font_style": "",
    }
    if env is None:
        env_family = _env_font_family()
        if env_family:
            return {
                "company_font_family": env_family,
                "company_font_stylesheet_url": google_fonts_stylesheet_url(env_family),
                "company_font_style": company_font_css(env_family),
            }
        return empty

    cid = resolve_branding_company_id(env, company_id=company_id)
    if cid is None or "res.company" not in env.registry:
        env_family = _env_font_family()
        if env_family:
            return {
                "company_font_family": env_family,
                "company_font_stylesheet_url": google_fonts_stylesheet_url(env_family),
                "company_font_style": company_font_css(env_family),
            }
        return empty

    Company = env.with_company(None).sudo()["res.company"]
    if not Company.search([("id", "=", cid)]):
        return empty

    co = Company.browse(cid)
    font_val = getattr(co, "font_family", None)
    family = resolve_font_family(company_value=font_val)
    custom = normalize_font_family(font_val) or _env_font_family()
    return {
        "company_font_family": family,
        "company_font_stylesheet_url": google_fonts_stylesheet_url(family),
        "company_font_style": company_font_css(custom),
    }
