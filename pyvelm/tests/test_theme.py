"""Tests for per-company theme CSS generation."""

from pyvelm.theme import company_theme_css, normalize_hex, primary_palette


def test_normalize_hex():
    assert normalize_hex("#6366f1") == "#6366f1"
    assert normalize_hex("6366f1") == "#6366f1"
    assert normalize_hex("#f00") == "#ff0000"
    assert normalize_hex("") is None
    assert normalize_hex("not-a-color") is None


def test_primary_palette_anchor():
    palette = primary_palette("#6366f1")
    assert palette[600] == "#6366f1"
    assert 50 in palette and 950 in palette


def test_company_theme_css_emits_variables():
    css = company_theme_css("#10b981")
    assert "--color-primary-600: #10b981" in css
    assert "--color-fg-brand: var(--color-primary-600)" in css
    assert ".dark {" in css


def test_company_theme_css_empty_when_invalid():
    assert company_theme_css("") == ""
    assert company_theme_css("not-a-color") == ""


def test_apply_request_scope_reads_company_cookie():
    from types import SimpleNamespace

    from pyvelm.env import Environment
    from pyvelm.request_env import COMPANY_COOKIE, apply_request_scope

    class _Conn:
        def cursor(self):
            raise RuntimeError("not used")

    env = Environment(_Conn(), registry=SimpleNamespace(), uid=None)
    request = SimpleNamespace(
        cookies={COMPANY_COOKIE: "42"},
        headers={},
    )
    scoped = apply_request_scope(
        env,
        request,
        resolve_session=lambda _e, _t: None,
        resolve_basic=lambda _e, _h: None,
    )
    assert scoped.company_id == 42


def test_color_widget_initializes_from_stored_hex():
    from pyvelm.render import _render_color_widget

    html = str(_render_color_widget("#10b981", {"name": "primary_color"}, False))
    assert "pvColorPicker" in html
    assert 'pvColorPicker("#10b981")' in html
    assert 'name="primary_color"' in html
    assert 'x-data="{ hex:' not in html


def test_color_widget_empty_does_not_force_default_in_form_field():
    from pyvelm.render import _render_color_widget

    html = str(_render_color_widget("", {"name": "primary_color"}, False))
    assert 'pvColorPicker("")' in html


def test_main_layout_loads_company_theme_after_stylesheet():
    """Company overrides must follow pyvelm.css or default indigo wins."""
    from pathlib import Path

    html = Path(__file__).resolve().parents[1] / "templates/layouts/main.html"
    text = html.read_text(encoding="utf-8")
    css_pos = text.index("/web/static/dist/pyvelm.css")
    theme_pos = text.index("layouts/_head_theme.html")
    assert css_pos < theme_pos
