"""Breadcrumb trail for list and form navigation."""

from pyvelm.render import build_breadcrumbs


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


def test_encode_list_nav_query():
    from pyvelm.render import encode_list_nav_query

    qs = encode_list_nav_query("crm", "lead_list", search="x", order="name ASC")
    assert "list=crm%2Flead_list" in qs or "list=crm/lead_list" in qs
    assert "search=x" in qs
    assert "order=name+ASC" in qs or "order=name%20ASC" in qs


def test_unknown_path_with_leaf_label():
    crumbs = build_breadcrumbs(_menu(), "/web/other", leaf_label="Custom")
    assert crumbs == [
        {"label": "Home", "href": "/web/admin"},
        {"label": "Custom", "href": None},
    ]
