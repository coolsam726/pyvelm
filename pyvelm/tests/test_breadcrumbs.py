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


def test_build_form_breadcrumbs_edit_trail(monkeypatch):
    def _fake_view_breadcrumb(env, module, name, menu_tree=None, **kw):
        return {"label": "Partners", "href": f"/web/views/{module}/{name}"}

    monkeypatch.setattr("pyvelm.render._view_breadcrumb", _fake_view_breadcrumb)
    crumbs = build_form_breadcrumbs(
        _menu(),
        env=object(),
        ref_module="partners",
        ref_name="partner.list",
        leaf_label="Acme Corp",
        mode="edit",
        record_href="/web/views/partners/partner.form/record/7",
    )
    assert crumbs[-2] == {
        "label": "Acme Corp",
        "href": "/web/views/partners/partner.form/record/7",
    }
    assert crumbs[-1] == {"label": "Edit", "href": None}


def test_form_page_list_crumb_without_record_title():
    """Record title lives in the page heading; list crumb stays a link."""
    crumbs = build_breadcrumbs(
        _menu(),
        "/web/views/sales/order.form/record/7",
        parent_href="/web/views/sales/order.list",
        parent_label="Orders",
    )
    assert crumbs == [
        {"label": "Home", "href": "/web/admin"},
        {"label": "Orders", "href": "/web/views/sales/order.list"},
    ]


def test_encode_view_nav_query_ref_and_bc():
    qs = encode_view_nav_query(
        "sales",
        "order.kanban",
        search="hello",
        group_by="partner_id",
        bc_stack=[("sales", "order.list")],
    )
    assert "ref=sales%2Forder.kanban" in qs or ("ref=sales/order.kanban" in qs)
    assert "bc=sales%2Forder.list" in qs or ("bc=sales/order.list" in qs)
    assert "search=hello" in qs
    assert "group_by=partner_id" in qs


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
        ref_module="sales",
        ref_name="order.kanban",
        bc_stack=[("sales", "order.list")],
        search="x",
        group_by="partner_id",
    )
    assert crumbs[0] == {"label": "Home", "href": "/web/admin"}
    assert crumbs[1]["label"] == "Comments"
    assert crumbs[1]["href"] == "/web/views/sales/order.list"
    assert crumbs[2]["label"] == "Kanban"
    assert "order.kanban" in crumbs[2]["href"]
    assert "search=x" in crumbs[2]["href"]
    assert "group_by=partner_id" in crumbs[2]["href"]


def test_build_form_breadcrumbs_without_ref():
    crumbs = build_form_breadcrumbs(
        _menu(),
        env=object(),
        ref_module=None,
        ref_name=None,
    )
    assert crumbs == [{"label": "Home", "href": "/web/admin"}]
