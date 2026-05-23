"""Per-company theme — map ``res.company.primary_color`` to CSS variables."""
from __future__ import annotations

import colorsys
import re

# Lightness / saturation multipliers per Tailwind-style shade (anchor at 600).
_SHADE_STOPS: dict[int, tuple[float, float]] = {
    50: (0.97, 0.20),
    100: (0.93, 0.30),
    200: (0.86, 0.45),
    300: (0.77, 0.60),
    400: (0.67, 0.78),
    500: (0.57, 0.92),
    600: (0.0, 1.0),  # anchor — uses the exact company hex
    700: (0.42, 0.95),
    800: (0.34, 0.90),
    900: (0.27, 0.85),
    950: (0.19, 0.80),
}

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize_hex(color: str | None) -> str | None:
    """Return a lower-case ``#rrggbb`` string, or ``None`` if invalid/empty."""
    if color is None:
        return None
    text = str(color).strip()
    if not text:
        return None
    if not text.startswith("#"):
        text = f"#{text}"
    if not _HEX_RE.match(text):
        return None
    if len(text) == 4:
        text = "#" + "".join(ch * 2 for ch in text[1:])
    return text.lower()


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color[1:]
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
    )


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(round(r * 255)))),
        max(0, min(255, int(round(g * 255)))),
        max(0, min(255, int(round(b * 255)))),
    )


def primary_palette(hex_color: str) -> dict[int, str]:
    """Build a primary colour scale from one accent hex (nuru ``primary_color``)."""
    base = normalize_hex(hex_color)
    if not base:
        return {}
    r, g, b = _hex_to_rgb(base)
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    out: dict[int, str] = {}
    for shade, (target_l, sat_mult) in _SHADE_STOPS.items():
        if shade == 600:
            out[shade] = base
            continue
        l = target_l if target_l > 0 else lightness
        s = min(1.0, max(0.0, saturation * sat_mult))
        nr, ng, nb = colorsys.hls_to_rgb(hue, l, s)
        out[shade] = _rgb_to_hex(nr, ng, nb)
    return out


def company_theme_css(hex_color: str | None) -> str:
    """CSS overrides for the active company's accent colour."""
    palette = primary_palette(hex_color or "")
    if not palette:
        return ""
    lines = [
        "/* pyvelm company theme — generated from res.company.primary_color */",
        ":root {",
    ]
    for shade, value in sorted(palette.items()):
        lines.append(f"  --color-primary-{shade}: {value};")
    lines.extend(
        [
            "  --color-fg-brand-subtle: var(--color-primary-100);",
            "  --color-fg-brand: var(--color-primary-600);",
            "  --color-fg-brand-strong: var(--color-primary-900);",
            "  --color-brand-softer: var(--color-primary-50);",
            "  --color-brand-soft: var(--color-primary-100);",
            "  --color-brand: var(--color-primary-500);",
            "  --color-brand-medium: var(--color-primary-300);",
            "  --color-brand-strong: var(--color-primary-700);",
            "  --color-brand-subtle: var(--color-primary-200);",
            "  --color-brand-light: var(--color-primary-600);",
            "  --color-shiki-fg-brand: var(--color-primary-500);",
            "  --color-shiki-fg-brand-subtle: var(--color-primary-200);",
            "}",
            ".dark {",
            "  --color-fg-brand-subtle: var(--color-primary-200);",
            "  --color-fg-brand: var(--color-primary-500);",
            "  --color-fg-brand-strong: var(--color-primary-400);",
            "  --color-brand-softer: var(--color-primary-950);",
            "  --color-brand-soft: var(--color-primary-900);",
            "  --color-brand: var(--color-primary-600);",
            "  --color-brand-medium: var(--color-primary-800);",
            "  --color-brand-strong: var(--color-primary-700);",
            "  --color-brand-subtle: var(--color-primary-900);",
            "  --color-brand-light: var(--color-primary-600);",
            "}",
        ]
    )
    return "\n".join(lines)


def company_theme_context(env, *, company_id: int | None = None) -> dict[str, str]:
    """Template variables for company accent CSS (all layouts / standalone pages)."""
    empty = {"company_primary_color": "", "company_theme_style": ""}
    if env is None:
        return empty
    cid = env.company_id if company_id is None else company_id
    if cid is None or "res.company" not in env.registry:
        return empty
    bypass_env = env.with_company(None)
    bypass_env._acl_bypass = True
    try:
        if not bypass_env["res.company"].search([("id", "=", cid)]):
            return empty
        co = bypass_env["res.company"].browse(cid)
        primary = normalize_hex(co.primary_color) or ""
        return {
            "company_primary_color": primary,
            "company_theme_style": company_theme_css(primary),
        }
    finally:
        bypass_env._acl_bypass = False
