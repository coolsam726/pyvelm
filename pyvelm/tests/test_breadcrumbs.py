"""Breadcrumb trail for list, kanban, and form navigation."""

from pyvelm.render import (
    build_breadcrumbs,
    build_form_breadcrumbs,
    encode_view_nav_query,
    format_bc_param,
    parse_bc_param,
)


def _menu():
    return [
        {
            "label": "CRM",
            "href": None,
            "children": [
                {"label": "Leads", "href": "/web/views/crm/lead_list"},
            ],
        },
    ]


def test_list_page_home_and_view_label():
    crumbs = build_breadcrumbs(_menu(), "/web/views/crm/lead_list")
    assert crumbs == [
        {"label": "Home", "href": "/web/admin"},
        {"label": "Leads", "href": None},
    ]


def test_form_page_links_back_to_list():
    crumbs = build_breadcrumbs(
        _menu(),
        "/web/views/crm/lead_form/record/7/edit",
        leaf_label="Acme Corp",
        parent_href="/web/views/crm/lead_list",
        parent_label="Leads",
    )
    assert crumbs == [
        {"label": "Home", "href": "/web/admin"},
        {"label": "Leads", "href": "/web/views/crm/lead_list"},
        {"label": "Acme Corp", "href": None},
    ]


def test_form_page_list_crumb_without_record_title():
    """Record title lives in the page heading; list crumb stays a link."""
    crumbs = build_breadcrumbs(
        _menu(),
        "/web/views/vellum_demo/demo_note.form/record/7",
        parent_href="/web/views/vellum_demo/demo_note.list",
        parent_label="Demo notes",
    )
    assert crumbs == [
        {"label": "Home", "href": "/web/admin"},
        {"label": "Demo notes", "href": "/web/views/vellum_demo/demo_note.list"},
    ]


def test_encode_view_nav_query_ref_and_bc():
    qs = encode_view_nav_query(
        "vellum_demo",
        "demo_comment.kanban",
        search="hello",
        group_by="note_id",
        bc_stack=[("vellum_demo", "demo_comment.list")],
    )
    assert "ref=vellum_demo%2Fdemo_comment.kanban" in qs or (
        "ref=vellum_demo/demo_comment.kanban" in qs
    )
    assert "bc=vellum_demo%2Fdemo_comment.list" in qs or (
        "bc=vellum_demo/demo_comment.list" in qs
    )
    assert "search=hello" in qs
    assert "group_by=note_id" in qs


def test_parse_bc_param_roundtrip():
    stack = [("a", "b.list"), ("c", "d.kanban")]
    assert parse_bc_param(format_bc_param(stack)) == stack


def test_build_form_breadcrumbs_from_kanban_with_history(monkeypatch):
    """Kanban parent + list ancestor — Odoo-style stack."""

    def _fake_view_breadcrumb(env, module, name, menu_tree=None, **kw):
        link_query = kw.get("link_query", True)
        href = f"/web/views/{module}/{name}"
        if link_query and kw.get("search"):
            href += f"?search={kw['search']}"
        if link_query and kw.get("group_by"):
            href += f"&group_by={kw['group_by']}" if "?" in href else f"?group_by={kw['group_by']}"
        label = "Comments" if "list" in name else "Kanban"
        return {"label": label, "href": href}

    monkeypatch.setattr("pyvelm.render._view_breadcrumb", _fake_view_breadcrumb)
    crumbs = build_form_breadcrumbs(
        _menu(),
        env=object(),
        ref_module="vellum_demo",
        ref_name="demo_comment.kanban",
        bc_stack=[("vellum_demo", "demo_comment.list")],
        search="x",
        group_by="note_id",
    )
    assert crumbs[0] == {"label": "Home", "href": "/web/admin"}
    assert crumbs[1]["label"] == "Comments"
    assert crumbs[1]["href"] == "/web/views/vellum_demo/demo_comment.list"
    assert crumbs[2]["label"] == "Kanban"
    assert "demo_comment.kanban" in crumbs[2]["href"]
    assert "search=x" in crumbs[2]["href"]
    assert "group_by=note_id" in crumbs[2]["href"]


def test_build_form_breadcrumbs_without_ref():
    crumbs = build_form_breadcrumbs(
        _menu(),
        env=object(),
        ref_module=None,
        ref_name=None,
    )
    assert crumbs == [{"label": "Home", "href": "/web/admin"}]
