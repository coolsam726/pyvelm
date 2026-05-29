"""Document registry + branded HTML assembly.

Business modules register a printable document with ``register_document`` and a
``render_body(env, record) -> html`` callable. ``render_html`` wraps that body in
the company's external layout (logo, address, accent, variant); ``render_pdf``
pipes it through wkhtmltopdf.
"""
from __future__ import annotations

import base64
import re
from functools import lru_cache
from pathlib import Path
from typing import Callable

from markupsafe import Markup

from . import pdf as _pdf

_ATTACHMENT_URL = re.compile(r"/api/attachment/(\d+)/download")


@lru_cache(maxsize=32)
def _google_font_embed(font_name: str) -> str:
    """Return a ``<style>`` block embedding *font_name* (regular + bold) as TTF
    ``@font-face`` data URIs, so wkhtmltopdf AND the browser render it identically
    (no per-render network, no woff2/UA pitfalls). Empty string on any failure."""
    if not font_name:
        return ""
    try:
        import httpx

        fam = font_name.replace(" ", "+")
        url = f"https://fonts.googleapis.com/css2?family={fam}:wght@400;700&display=swap"
        # An old UA makes Google Fonts serve TTF (truetype) rather than woff2.
        css = httpx.get(url, headers={"User-Agent": "Mozilla/4.0"}, timeout=8.0).text
        faces = []
        for block in re.findall(r"@font-face\s*\{[^}]*\}", css):
            wm = re.search(r"font-weight:\s*(\d+)", block)
            um = re.search(r"url\((https://[^)]+?\.ttf)\)", block)
            if not um:
                continue
            data = httpx.get(um.group(1), timeout=8.0).content
            b64 = base64.b64encode(data).decode("ascii")
            weight = wm.group(1) if wm else "400"
            faces.append(
                f"@font-face{{font-family:'{font_name}';font-style:normal;"
                f"font-weight:{weight};src:url(data:font/ttf;base64,{b64}) "
                f"format('truetype');}}"
            )
        return f"<style>{''.join(faces)}</style>" if faces else ""
    except Exception:
        return ""


def _logo_data_uri(env, url: str) -> str:
    """Resolve a logo URL to an embeddable ``data:`` URI.

    wkhtmltopdf is a separate process with no session/base URL, so it can't fetch
    the relative, auth-protected `/api/attachment/{id}/download` link the file
    picker stores (the logo would be missing in the PDF). Read the bytes
    server-side and inline them — works in both the PDF and the HTML preview.
    """
    if not url or url.startswith("data:"):
        return url or ""
    m = _ATTACHMENT_URL.search(url)
    if m and "ir.attachment" in env.registry:
        att = env.sudo()["ir.attachment"].search([("id", "=", int(m.group(1)))], limit=1)
        if att:
            if att.type == "url" and att.url:
                return att.url
            try:
                content = att.fetch_content()
                mime = att.mimetype or "image/png"
                return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"
            except Exception:
                return url
    if url.startswith(("http://", "https://")):
        try:
            import httpx

            r = httpx.get(url, timeout=5.0)
            if r.status_code == 200:
                mime = (r.headers.get("content-type") or "image/png").split(";")[0]
                return f"data:{mime};base64,{base64.b64encode(r.content).decode('ascii')}"
        except Exception:
            pass
    return url

# key -> {"model": str, "render_body": callable, "title": str}
_REGISTRY: dict[str, dict] = {}

_jinja = None


def _resolve_template_dir() -> Path:
    """Locate bundled Jinja templates (dev tree or installed wheel).

    ``layout.py`` lives under ``pyvelm/modules/document_layout/``; setuptools
    ships ``modules/**/templates/**`` beside it. Fall back to the ``pyvelm``
    package root when ``__file__`` resolves elsewhere (editable installs,
    importlib loaders).
    """
    marker = "external_layout.html"
    here = Path(__file__).resolve().parent
    candidates = [here / "templates"]
    try:
        import pyvelm

        candidates.append(
            Path(pyvelm.__file__).resolve().parent
            / "modules"
            / "document_layout"
            / "templates"
        )
    except ImportError:
        pass
    seen: set[Path] = set()
    for d in candidates:
        d = d.resolve()
        if d in seen:
            continue
        seen.add(d)
        if (d / marker).is_file():
            return d
    raise FileNotFoundError(
        "document_layout templates not found (missing external_layout.html); "
        "reinstall pyvelm with module template assets"
    )


def _jinja_env():
    global _jinja
    if _jinja is None:
        from jinja2 import ChoiceLoader, FileSystemLoader
        from pyvelm.render import _env as _pv_env

        template_dir = _resolve_template_dir()
        # Overlay pyvelm's environment so module templates can extend the
        # framework shell (`layouts/main.html`) while keeping pyvelm filters.
        _jinja = _pv_env.overlay(
            loader=ChoiceLoader([
                FileSystemLoader(str(template_dir)),
                _pv_env.loader,
            ])
        )
    return _jinja


def register_document(key: str, *, model: str, render_body: Callable, title: str = "") -> None:
    """Register a printable document. `render_body(env, record) -> html str`."""
    _REGISTRY[key] = {"model": model, "render_body": render_body, "title": title}


def document_spec(key: str) -> dict | None:
    return _REGISTRY.get(key)


# ISO / US paper sizes for HTML preview (matches wkhtmltopdf --page-size).
_PAPER_CSS: dict[str, tuple[str, str]] = {
    "A4": ("210mm", "297mm"),
    "Letter": ("215.9mm", "279.4mm"),
}
# Printable height inside wkhtmltopdf margins (16 mm top + 16 mm bottom).
_PAPER_CONTENT_MIN: dict[str, str] = {
    "A4": "265mm",
    "Letter": "247.4mm",
}


def paper_css_size(paper: str) -> tuple[str, str]:
    """Return ``(width, height)`` CSS lengths for *paper*."""
    return _PAPER_CSS.get(paper, _PAPER_CSS["A4"])


def paper_content_min_height(paper: str) -> str:
    """Minimum content height matching wkhtmltopdf's top/bottom margins."""
    return _PAPER_CONTENT_MIN.get(paper, _PAPER_CONTENT_MIN["A4"])


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def tint_color(hex_color: str, *, white_weight: float = 0.92) -> str:
    """Bootstrap-style tint — ``mix(white, color, 92%)`` for Odoo folder/wave shapes."""
    r, g, b = _hex_to_rgb(hex_color)
    t = white_weight
    u = 1.0 - t
    return "#{:02x}{:02x}{:02x}".format(
        round(255 * t + r * u),
        round(255 * t + g * u),
        round(255 * t + b * u),
    )


def _company_context(env, company=None) -> dict:
    Company = env["res.company"]
    if company is None:
        if env.company_id:
            company = Company.search([("id", "=", env.company_id)], limit=1)
        if not company:
            company = Company.search([], limit=1)
    if not company:
        pw, ph = paper_css_size("A4")
        accent = "#1f2937"
        return {"name": "", "address_lines": [], "logo_url": "", "accent": accent,
                "secondary": accent, "font": "", "font_face_css": Markup(""),
                "copyright": "", "layout": "light", "paper": "A4",
                "paper_width": pw, "paper_height": ph,
                "paper_content_min": paper_content_min_height("A4"),
                "folder_tint": tint_color(accent), "vat": ""}
    accent = company.primary_color or "#1f2937"
    font = company.google_font or ""
    paper = company.paper_format or "A4"
    pw, ph = paper_css_size(paper)
    return {
        "name": company.name or "",
        "address_lines": company._address_lines(),
        "logo_url": _logo_data_uri(env, company.logo_url or ""),
        "accent": accent,
        "secondary": company.secondary_color or accent,
        "font": font,
        "font_face_css": Markup(_google_font_embed(font)),
        "copyright": company.copyright_text or "",
        "layout": company.document_layout or "light",
        "paper": paper,
        "paper_width": pw,
        "paper_height": ph,
        "paper_content_min": paper_content_min_height(paper),
        "folder_tint": tint_color(accent),
        "vat": company.vat or "",
    }


def render_html(env, key: str, record_id: int, *, preview: bool = False) -> str:
    """Render the full branded HTML document for a record.

    ``preview=True`` wraps the document in a paper-sized sheet on a grey backdrop
    (for in-browser preview); the PDF path uses ``preview=False`` (full-bleed —
    wkhtmltopdf sets the physical page + margins).
    """
    spec = _REGISTRY.get(key)
    if not spec:
        raise KeyError(f"Unknown report document {key!r}")
    Model = env[spec["model"]]
    if not Model.search([("id", "=", record_id)], limit=1):
        raise ValueError(f"{spec['model']} {record_id} not found")
    record = Model.browse(record_id)
    body = spec["render_body"](env, record)
    company = _company_context(env)
    template = _jinja_env().get_template("external_layout.html")
    return template.render(
        body=Markup(body),
        company=company,
        title=spec.get("title") or key,
        preview=preview,
    )


def _sample_body(ctx: dict) -> Markup:
    return Markup(_jinja_env().get_template("layout_sample.html").render(accent=ctx["accent"]))


def _render_sample(ctx: dict) -> str:
    """Full standalone HTML document (used for the PDF + full-page preview)."""
    return _jinja_env().get_template("external_layout.html").render(
        body=_sample_body(ctx), company=ctx, title="Layout Preview", preview=True,
    )


def _render_inline(ctx: dict) -> str:
    """Scoped HTML *fragment* (no <html>/<body>) for inline injection into the
    designer dialog — styles namespaced under `.pvdoc` so they don't leak."""
    return _jinja_env().get_template("preview_inline.html").render(
        body=_sample_body(ctx), company=ctx,
        title="Sample Invoice",
        accent=ctx["accent"], secondary=ctx["secondary"],
    )


def _apply_overrides(env, ctx: dict, overrides: dict | None) -> dict:
    if overrides:
        if overrides.get("layout"):
            ctx["layout"] = overrides["layout"]
        if overrides.get("paper"):
            ctx["paper"] = overrides["paper"]
            pw, ph = paper_css_size(overrides["paper"])
            ctx["paper_width"] = pw
            ctx["paper_height"] = ph
            ctx["paper_content_min"] = paper_content_min_height(overrides["paper"])
        if overrides.get("color"):
            ctx["accent"] = overrides["color"]
            ctx["folder_tint"] = tint_color(overrides["color"])
        if overrides.get("secondary"):
            ctx["secondary"] = overrides["secondary"]
        if "font" in overrides:
            ctx["font"] = overrides["font"]
            ctx["font_face_css"] = Markup(_google_font_embed(overrides["font"]))
        if "logo" in overrides:
            ctx["logo_url"] = _logo_data_uri(env, overrides["logo"] or "")
    return ctx


def render_layout_preview(env, company_id: int | None = None, overrides: dict | None = None,
                          *, inline: bool = False) -> str:
    """Render a sample document in a company's layout. ``overrides`` show unsaved
    edits live; ``inline=True`` returns the scoped fragment for the dialog."""
    Company = env["res.company"]
    company = None
    if company_id and Company.search([("id", "=", company_id)], limit=1):
        company = Company.browse(company_id)
    ctx = _apply_overrides(env, _company_context(env, company), overrides)
    return _render_inline(ctx) if inline else _render_sample(ctx)


def _designer_context(env, company_id: int | None):
    """Shared company values + framework widgets for dialog and full-page designer."""
    from pyvelm.render import _render_color_widget, _render_file_url_widget

    from .constants import DOCUMENT_LAYOUT_CHOICES

    Company = env["res.company"]
    company = None
    if company_id and Company.search([("id", "=", company_id)], limit=1):
        company = Company.browse(company_id)
    if not company:
        company = Company.search([], limit=1)
    cid = company.id if company else 0
    primary = (company.primary_color if company else "") or "#1f2937"
    values = {
        "document_layout": (company.document_layout if company else "") or "light",
        "paper_format": (company.paper_format if company else "") or "A4",
        "primary_color": primary,
        "secondary_color": (company.secondary_color if company else "") or primary,
        "google_font": (company.google_font if company else "") or "",
        "logo_url": (company.logo_url if company else "") or "",
    }
    layout_choices = [
        (v, lbl.split(" — ", 1)[0] if " — " in lbl else lbl)
        for v, lbl in DOCUMENT_LAYOUT_CHOICES
    ]
    widgets = {
        "logo": _render_file_url_widget(
            values["logo_url"], {"name": "logo_url", "accept": "image/*"}, readonly=False,
        ),
        "primary": _render_color_widget(
            values["primary_color"], {"name": "primary_color"}, readonly=False,
        ),
        "secondary": _render_color_widget(
            values["secondary_color"], {"name": "secondary_color"}, readonly=False,
        ),
    }
    return cid, company, values, widgets, layout_choices


def render_designer(env, company_id: int | None, csrf_token: str) -> str:
    """Render the designer FRAGMENT (controls + inline live preview) for PvDialog."""
    cid, _company, values, widgets, layout_choices = _designer_context(env, company_id)
    from .constants import GOOGLE_FONT_CHOICES

    return _jinja_env().get_template("designer.html").render(
        company_id=cid, csrf_token=csrf_token, values=values,
        google_fonts=GOOGLE_FONT_CHOICES, logo_widget=widgets["logo"],
        layout_choices=layout_choices,
        initial_preview=render_layout_preview(env, cid, inline=True),
    )


def render_designer_page(
    env,
    company_id: int | None,
    csrf_token: str,
) -> str:
    """Render the designer as a normal page inside the app shell (sidebar layout)."""
    from pyvelm.render import _home_breadcrumb, layout_context

    cid, company, values, widgets, layout_choices = _designer_context(env, company_id)
    from .constants import GOOGLE_FONT_CHOICES

    list_href = "/web/views/document_layout/res_company_layout.list"
    company_label = company.name if company else "Company"
    ctx = layout_context(
        env,
        list_href,
        leaf_label="Layout designer",
    )
    ctx["breadcrumbs"] = [
        _home_breadcrumb(),
        {"label": "Document Layout", "href": list_href},
        {"label": company_label, "href": None},
    ]
    ctx["subtitle"] = (
        f"{company_label} — tune the PDF header, colours, and paper format"
        if company else ""
    )
    return _jinja_env().get_template("designer_page.html").render(
        page_title="Document Layout Designer",
        company_id=cid,
        company_name=company_label,
        csrf_token=csrf_token,
        values=values,
        layout_choices=layout_choices,
        google_fonts=GOOGLE_FONT_CHOICES,
        logo_widget=widgets["logo"],
        primary_color_widget=widgets["primary"],
        secondary_color_widget=widgets["secondary"],
        initial_preview=Markup(render_layout_preview(env, cid, inline=True)),
        list_href=list_href,
        **ctx,
    )


def render_pdf(env, key: str, record_id: int) -> tuple[bytes, str]:
    """Return (pdf_bytes, paper_format) for a record."""
    html = render_html(env, key, record_id)
    paper = _company_context(env).get("paper", "A4")
    return _pdf.html_to_pdf(html, paper=paper), paper
