"""Tests for declarative dashboard views and widget builders."""

import pytest

from pyvelm.builders import (
    chart_widget,
    dashboard_view,
    link_widget,
    stat_widget,
    table_widget,
)
from pyvelm.render import (
    _filter_fields_spec,
    _field_headers,
    _parse_view_ref,
    _resolve_dashboard_colspan,
)
from pyvelm.views import normalize_arch


def test_parse_view_ref():
    assert _parse_view_ref("user.list", "admin") == ("admin", "user.list")
    assert _parse_view_ref(("crm", "lead.graph"), "admin") == ("crm", "lead.graph")
    assert _parse_view_ref("crm/lead.graph", "admin") == ("crm", "lead.graph")


def test_resolve_dashboard_colspan_full():
    assert _resolve_dashboard_colspan("full", 3) == 3
    assert _resolve_dashboard_colspan("FULL", 4) == 4
    assert _resolve_dashboard_colspan(2, 3) == 2
    assert _resolve_dashboard_colspan(9, 3) == 3


def test_dashboard_view_columns():
    dv = dashboard_view("home", columns=3, widgets=[])
    assert dv["arch"]["columns"] == 3
    with pytest.raises(ValueError):
        dashboard_view("bad", columns=0, widgets=[])


def test_dashboard_view_shape():
    dv = dashboard_view(
        "home",
        title="Home",
        widgets=[
            stat_widget("s1", title="Users", model="res.users"),
            chart_widget(
                "c1",
                title="By active",
                model="res.users",
                groupby="active",
            ),
            table_widget("t1", title="Recent", view="user.list", limit=5),
            link_widget(
                "l1",
                title="Groups",
                subtitle="res.groups",
                description="Manage groups",
                url="/web/views/admin/group.list",
            ),
        ],
    )
    assert dv["view_type"] == "dashboard"
    assert dv["model"] == "dashboard"
    assert len(dv["arch"]["widgets"]) == 4


def test_chart_widget_requires_config():
    with pytest.raises(ValueError):
        chart_widget("bad", title="Missing config")
    w = chart_widget("ok", view="lead.graph")
    assert w["view"] == "lead.graph"


def test_table_widget_requires_config():
    with pytest.raises(ValueError):
        table_widget("bad", title="Missing config")
    w = table_widget("ok", model="res.users", fields=["name"])
    assert w["fields"] == ["name"]


def test_table_widget_columns():
    w = table_widget(
        "t1",
        view="user.list",
        columns=["name", "login"],
    )
    assert w["columns"] == ["name", "login"]


def test_filter_fields_spec():
    specs = ["name", "login", "active"]
    assert [s if isinstance(s, str) else s["name"] for s in _filter_fields_spec(specs, ["login", "name"])] == [
        "login",
        "name",
    ]


def test_field_headers_visible_default():
    class _F:
        string = "Label"

    class _M:
        _fields = {"hidden": _F(), "shown": _F()}

    headers = _field_headers(
        _M,
        [{"name": "hidden", "visible": False}, {"name": "shown"}],
    )
    by_name = {h["name"]: h for h in headers}
    assert by_name["hidden"]["visible_default"] is False
    assert by_name["shown"]["visible_default"] is True


def test_normalize_dashboard_table_fields():
    arch = normalize_arch(
        {
            "widgets": [
                {
                    "type": "table",
                    "id": "t1",
                    "model": "res.users",
                    "fields": ["name", "login"],
                }
            ]
        },
        "dashboard",
    )
    fields = arch["widgets"][0]["fields"]
    assert fields[0] == {"name": "name"}
    assert fields[1] == {"name": "login"}
