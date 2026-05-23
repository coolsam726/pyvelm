"""Tests for Heroicons menu icon resolution."""

from markupsafe import Markup

from pyvelm.icons import resolve_icon


def test_resolve_icon_home_outline():
    svg = resolve_icon("home")
    assert svg is not None
    assert isinstance(svg, Markup)
    assert "svg" in str(svg).lower()
    assert 'class="w-4 h-4"' in str(svg)


def test_resolve_icon_variant_prefix():
    svg = resolve_icon("solid:shield-check")
    assert svg is not None
    assert "svg" in str(svg).lower()


def test_resolve_icon_legacy_svg_passthrough():
    raw = '<svg viewBox="0 0 24 24"><path d="M0 0"/></svg>'
    assert resolve_icon(raw) == Markup(raw)


def test_resolve_icon_underscore_alias():
    assert resolve_icon("chart_bar") is not None


def test_resolve_icon_unknown_falls_back():
    svg = resolve_icon("not-a-real-icon-xyz")
    assert svg is not None
    assert "svg" in str(svg).lower()
