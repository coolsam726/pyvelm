"""Menu tree building and layout helpers."""

import os
import unittest
from unittest.mock import patch

from pyvelm.menu import (
    MENU_LAYOUT_APPS,
    MENU_LAYOUT_SIDEBAR,
    _attach_children,
    _mark_active,
    active_menu_root,
    build_menu_tree,
    find_menu_entry,
    menu_active_path_from_breadcrumbs,
    menu_entry_href,
    menu_layout,
    menu_layout_context,
    menu_node_visible,
)


class AttachChildrenTests(unittest.TestCase):
    def test_builds_arbitrary_depth(self):
        nodes = {
            1: {
                "label": "Root",
                "href": None,
                "children": [],
                "_parent_id": None,
            },
            2: {
                "label": "Mid",
                "href": None,
                "children": [],
                "_parent_id": 1,
            },
            3: {
                "label": "Leaf",
                "href": "/web/views/a/x",
                "children": [],
                "_parent_id": 2,
            },
        }
        roots = _attach_children(nodes, [1, 2, 3])
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["label"], "Root")
        self.assertEqual(roots[0]["children"][0]["label"], "Mid")
        self.assertEqual(
            roots[0]["children"][0]["children"][0]["href"],
            "/web/views/a/x",
        )
        self.assertNotIn("_parent_id", roots[0])


class FindMenuEntryTests(unittest.TestCase):
    def _tree(self):
        return [
            {
                "label": "CRM",
                "href": None,
                "children": [
                    {
                        "label": "Sales",
                        "href": None,
                        "children": [
                            {
                                "label": "Leads",
                                "href": "/web/views/crm/lead.list",
                                "children": [],
                            },
                        ],
                    },
                ],
            },
        ]

    def test_finds_deep_leaf(self):
        parent, leaf = find_menu_entry(
            self._tree(), "/web/views/crm/lead.list"
        )
        self.assertEqual(leaf["label"], "Leads")
        self.assertEqual(parent["label"], "Sales")

    def test_missing_returns_none(self):
        self.assertEqual(find_menu_entry(self._tree(), "/nope"), (None, None))


class MenuLayoutTests(unittest.TestCase):
    def test_default_apps(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PYVELM_MENU_LAYOUT", None)
            self.assertEqual(menu_layout(), MENU_LAYOUT_APPS)

    def test_sidebar_from_env(self):
        with patch.dict(os.environ, {"PYVELM_MENU_LAYOUT": "sidebar"}):
            self.assertEqual(menu_layout(), MENU_LAYOUT_SIDEBAR)

    def test_unknown_falls_back_to_apps(self):
        with patch.dict(os.environ, {"PYVELM_MENU_LAYOUT": "tabs"}):
            self.assertEqual(menu_layout(), MENU_LAYOUT_APPS)

    def test_odoo_alias_maps_to_apps(self):
        with patch.dict(os.environ, {"PYVELM_MENU_LAYOUT": "odoo"}):
            self.assertEqual(menu_layout(), MENU_LAYOUT_APPS)

    def test_layout_context_defaults_to_apps(self):
        tree = [{"label": "Home", "href": "/web/admin", "children": []}]
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PYVELM_MENU_LAYOUT", None)
            ctx = menu_layout_context(tree, "/web/admin")
        self.assertEqual(ctx["menu_layout"], MENU_LAYOUT_APPS)
        self.assertIn("menu_roots", ctx)
        self.assertIn("menu_secondary", ctx)

    def test_layout_context_apps_secondary(self):
        tree = [
            {
                "label": "Settings",
                "href": None,
                "children": [
                    {"label": "Users", "href": "/web/views/admin/user.list",
                     "children": []},
                ],
            },
        ]
        ctx = menu_layout_context(
            tree,
            "/web/views/admin/user.list",
            layout=MENU_LAYOUT_APPS,
        )
        self.assertEqual(ctx["menu_layout"], MENU_LAYOUT_APPS)
        self.assertEqual(ctx["menu_active_root"]["label"], "Settings")
        self.assertEqual(ctx["menu_active_root_index"], 0)
        self.assertEqual(len(ctx["menu_secondary"]), 1)
        self.assertEqual(ctx["menu_roots"][0]["nav_href"],
                         "/web/views/admin/user.list")


class MenuActivePathTests(unittest.TestCase):
    def test_form_uses_parent_list_crumb(self):
        crumbs = [
            {"label": "Home", "href": "/web/admin"},
            {"label": "Leads", "href": "/web/views/crm/lead.list"},
        ]
        path = menu_active_path_from_breadcrumbs(
            crumbs,
            current_path="/web/views/crm/lead.form/record/7/edit",
            home_href="/web/admin",
        )
        self.assertEqual(path, "/web/views/crm/lead.list")

    def test_list_page_falls_back_to_current_path(self):
        crumbs = [
            {"label": "Home", "href": "/web/admin"},
            {"label": "Leads", "href": None},
        ]
        path = menu_active_path_from_breadcrumbs(
            crumbs,
            current_path="/web/views/crm/lead.list",
            home_href="/web/admin",
        )
        self.assertEqual(path, "/web/views/crm/lead.list")

    def test_kanban_parent_from_deep_trail(self):
        crumbs = [
            {"label": "Home", "href": "/web/admin"},
            {"label": "Comments", "href": "/web/views/demo/comment.list"},
            {
                "label": "Kanban",
                "href": "/web/views/demo/comment.kanban?search=x",
            },
        ]
        path = menu_active_path_from_breadcrumbs(
            crumbs,
            current_path="/web/views/demo/comment.form/record/1/edit",
            home_href="/web/admin",
        )
        self.assertEqual(path, "/web/views/demo/comment.kanban")


class ActiveRootTests(unittest.TestCase):
    def test_picks_root_by_path(self):
        tree = [
            {"label": "A", "href": None, "children": []},
            {
                "label": "B",
                "href": None,
                "children": [
                    {"label": "X", "href": "/web/b", "children": []},
                ],
            },
        ]
        root, index = active_menu_root(tree, "/web/b")
        self.assertEqual(root["label"], "B")
        self.assertEqual(index, 1)

    def test_form_path_highlights_list_menu(self):
        tree = [
            {
                "label": "Dashboard",
                "href": "/web/admin",
                "children": [],
            },
            {
                "label": "CRM",
                "href": None,
                "children": [
                    {
                        "label": "Leads",
                        "href": "/web/views/crm/lead.list",
                        "children": [],
                    },
                ],
            },
        ]
        for node in tree:
            _mark_active(node, "/web/views/crm/lead.list")
        root, index = active_menu_root(
            tree, "/web/views/crm/lead.list"
        )
        self.assertEqual(root["label"], "CRM")
        self.assertEqual(index, 1)
        self.assertTrue(tree[1]["children"][0]["active"])


class MenuEntryHrefTests(unittest.TestCase):
    def test_first_descendant(self):
        node = {
            "label": "G",
            "href": None,
            "children": [
                {"label": "L", "href": "/leaf", "children": []},
            ],
        }
        self.assertEqual(menu_entry_href(node), "/leaf")


class MenuNodeVisibleDeepTests(unittest.TestCase):
    """Visibility pruning on nested trees (mirrors test_security.MenuAclTests)."""

    class _Env:
        def __init__(self, granted):
            self._granted = set(granted)

        def has_access(self, model, perm):
            return (model, perm) in self._granted

        def can(self, *_a, **_k):
            return True

    def test_prunes_empty_nested_group(self):
        tree = [
            {
                "label": "CRM",
                "href": None,
                "children": [
                    {
                        "label": "Hidden",
                        "href": None,
                        "children": [
                            {
                                "label": "Leads",
                                "href": "/web/views/crm/lead.list",
                                "children": [],
                            },
                        ],
                    },
                ],
            },
        ]
        env = self._Env(set())
        with patch("pyvelm.menu.menu_target_model",
                   return_value="crm.lead"):
            out = [n for n in tree if menu_node_visible(env, n)]
        self.assertEqual(out, [])


class MenuParentResolutionTests(unittest.TestCase):
    def test_dotted_menu_name_scoped_to_module(self):
        from pyvelm.builders import _resolve_menu_parent

        self.assertEqual(
            _resolve_menu_parent("settings.organization", menu_module="admin"),
            "admin.settings.organization",
        )

    def test_short_name_scoped_to_module(self):
        from pyvelm.builders import _resolve_menu_parent

        self.assertEqual(
            _resolve_menu_parent("settings", menu_module="admin"),
            "admin.settings",
        )

    def test_cross_module_tuple(self):
        from pyvelm.builders import _resolve_menu_parent

        self.assertEqual(
            _resolve_menu_parent(("admin", "settings.access"), menu_module="partners"),
            "admin.settings.access",
        )


class MenuViewHrefTests(unittest.TestCase):
    def test_view_module_overrides_menu_module(self):
        from pyvelm.builders import _resolve_menu_href

        href = _resolve_menu_href(
            href=None,
            view="workflow_instance.list",
            view_module="workflow",
            menu_module="admin",
        )
        self.assertEqual(href, "/web/views/workflow/workflow_instance.list")


class MenuSyncOrderTests(unittest.TestCase):
    def test_nested_groups_before_leaves(self):
        from pyvelm.loader import _menu_sync_order

        menus = [
            {"name": "settings", "label": "Settings", "sequence": 1},
            {
                "name": "settings.companies",
                "label": "Companies",
                "parent": "admin.settings.organization",
                "sequence": 10,
            },
            {
                "name": "settings.organization",
                "label": "Organization",
                "parent": "admin.settings",
                "sequence": 5,
            },
        ]
        ordered = _menu_sync_order(menus, "admin")
        names = [m["name"] for m in ordered]
        self.assertEqual(names.index("settings.organization"),
                         names.index("settings") + 1)
        self.assertLess(
            names.index("settings.organization"),
            names.index("settings.companies"),
        )


class DevOnlyMenuVisibilityTests(unittest.TestCase):
    """``dev_only`` entries are hidden outside ``PYVELM_ENV=development``."""

    class _Env:
        def has_access(self, model, perm):
            return True

        def can(self, *_a, **_k):
            return True

    def _node(self, *, dev_only: bool, with_children: bool = False) -> dict:
        children = []
        if with_children:
            children.append({
                "label": "Leaf",
                "href": "/web/views/technical/menu.list",
                "children": [],
                "dev_only": dev_only,
                # access_model so menu_node_visible doesn't fall into the
                # view-resolution branch (which needs env.sudo()).
                "access_model": "ir.ui.menu",
                "access_perm": "write",
            })
        return {
            "label": "Technical",
            "href": None,
            "children": children,
            "dev_only": dev_only,
            "access_model": "ir.ui.menu",
            "access_perm": "write",
        }

    def test_hidden_in_production(self):
        env = self._Env()
        node = self._node(dev_only=True, with_children=True)
        with patch("pyvelm.runtime.is_development", return_value=False):
            visible = menu_node_visible(env, node)
        self.assertFalse(visible)

    def test_visible_in_development(self):
        env = self._Env()
        node = self._node(dev_only=True, with_children=True)
        with patch("pyvelm.runtime.is_development", return_value=True):
            visible = menu_node_visible(env, node)
        self.assertTrue(visible)

    def test_non_dev_only_unaffected(self):
        env = self._Env()
        node = self._node(dev_only=False, with_children=True)
        with patch("pyvelm.runtime.is_development", return_value=False):
            self.assertTrue(menu_node_visible(env, node))
        with patch("pyvelm.runtime.is_development", return_value=True):
            self.assertTrue(menu_node_visible(env, node))

    def test_dev_only_child_hidden_inside_visible_parent(self):
        env = self._Env()
        node = {
            "label": "Settings",
            "href": None,
            "children": [
                {
                    "label": "Admin tool",
                    "href": "/web/views/technical/menu.list",
                    "children": [],
                    "dev_only": True,
                    "access_model": "ir.ui.menu",
                    "access_perm": "write",
                },
                {
                    "label": "Users",
                    "href": "/web/views/admin/user.list",
                    "children": [],
                    "dev_only": False,
                    "access_model": "res.users",
                    "access_perm": "read",
                },
            ],
            "dev_only": False,
            "access_model": "ir.ui.menu",
            "access_perm": "read",
        }
        with patch("pyvelm.runtime.is_development", return_value=False):
            self.assertTrue(menu_node_visible(env, node))
        # Only the non-dev child survives the prune.
        labels = [c["label"] for c in node["children"]]
        self.assertEqual(labels, ["Users"])


class BuildMenuTreeIntegrationTests(unittest.TestCase):
    """Uses in-memory registry when PYVELM_DSN_TEST is unavailable — skip."""

    @unittest.skipUnless(
        os.environ.get("PYVELM_DSN_TEST"),
        "PYVELM_DSN_TEST not set",
    )
    def test_build_from_db(self):
        from pyvelm import BUILTIN_MODULE_ROOTS, loader
        from pyvelm.env import Environment
        from pyvelm.registry import Registry
        from pyvelm.tests.support.db import db_connection, dsn_from_env, install_modules

        if not dsn_from_env():
            self.skipTest("PYVELM_DSN_TEST not set")

        with db_connection() as conn:
            reg = Registry()
            env = Environment(conn, reg, uid=1)
            install_modules(env, BUILTIN_MODULE_ROOTS, install_all=True)
            tree = build_menu_tree(env, "/web/admin")
        self.assertIsInstance(tree, list)
        for node in tree:
            self.assertIn("label", node)
            self.assertIn("children", node)
