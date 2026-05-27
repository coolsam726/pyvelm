"""Navigation menu tree and layout modes for the web shell.

Layouts (``PYVELM_MENU_LAYOUT``):

- ``apps`` (default) — root applications in the sidebar; pages for the
  active app in the top bar.
- ``sidebar`` — three-level sidebar: root sections as subheadings,
  level-2 links, level-3 nested under collapsible groups.

Both modes share the same recursive tree from :func:`build_menu_tree`.

User guide: ``docs/navigation.md``.
"""
from __future__ import annotations

import os
from typing import Any, Literal

MenuLayout = Literal["sidebar", "apps"]

MENU_LAYOUT_SIDEBAR: MenuLayout = "sidebar"
MENU_LAYOUT_APPS: MenuLayout = "apps"
_VALID_LAYOUTS = frozenset({MENU_LAYOUT_SIDEBAR, MENU_LAYOUT_APPS})
# Deprecated env value; still accepted so older deployments keep working.
_LAYOUT_ALIASES = {"odoo": MENU_LAYOUT_APPS}


def menu_layout() -> MenuLayout:
    """Resolved shell navigation layout (env: ``PYVELM_MENU_LAYOUT``)."""
    raw = (os.environ.get("PYVELM_MENU_LAYOUT") or MENU_LAYOUT_APPS).strip().lower()
    raw = _LAYOUT_ALIASES.get(raw, raw)
    if raw in _VALID_LAYOUTS:
        return raw  # type: ignore[return-value]
    return MENU_LAYOUT_APPS


def menu_target_model(env, href: str | None) -> str | None:
    """Model a menu entry ultimately lists, or None when it is not a view."""
    if not href:
        return None
    from pyvelm.render import _load_ui_view

    path = href.split("?", 1)[0].rstrip("/")
    if not path.startswith("/web/views/"):
        return None
    parts = path.split("/")
    if len(parts) < 5:
        return None
    view = _load_ui_view(env.sudo(), parts[3], parts[4])
    return view.model if view else None


def menu_node_visible(env, node: dict) -> bool:
    """Prune ``node``'s children to the permitted set; return its visibility."""
    children = node.get("children") or []
    if children:
        node["children"] = [c for c in children if menu_node_visible(env, c)]
        if node["children"]:
            return True
        if not node.get("href"):
            return False
    # Delegate through render so tests can patch ``render._menu_target_model``.
    from pyvelm import render

    model = node.get("access_model") or render._menu_target_model(
        env, node.get("href")
    )
    if model is None:
        return True
    perm = node.get("access_perm") or "read"
    if not env.has_access(model, perm):
        return False
    policy = node.get("access_policy")
    if policy:
        return env.can(model, str(policy), perm=perm, model=model)
    return True


def _resolve_menu_icon(icon: str | None):
    from pyvelm.icons import resolve_icon

    return resolve_icon(icon)


def _record_to_entry(r) -> dict[str, Any]:
    return {
        "label": r.label,
        "href": r.href or None,
        "icon": _resolve_menu_icon(r.icon),
        "access_model": r.access_model or None,
        "access_perm": r.access_perm or None,
        "access_policy": getattr(r, "access_policy", None) or None,
        "children": [],
    }


def _attach_children(nodes_by_id: dict[int, dict], ordered_ids: list[int]) -> list[dict]:
    """Wire parent/child links preserving ``ordered_ids`` sequence."""
    roots: list[dict] = []
    for rid in ordered_ids:
        entry = nodes_by_id[rid]
        parent_id = entry.pop("_parent_id", None)
        if parent_id is None:
            roots.append(entry)
        else:
            parent = nodes_by_id.get(parent_id)
            if parent is not None:
                parent["children"].append(entry)
    return roots


def _mark_active(item: dict, current_path: str | None) -> dict:
    href = item.get("href")
    active = bool(
        href
        and current_path
        and (current_path == href or current_path.startswith(href + "/"))
    )
    item["active"] = active
    for child in item.get("children", []) or []:
        _mark_active(child, current_path)
        if child.get("active"):
            item["active"] = True
    return item


def build_menu_tree(env, current_path: str | None = None) -> list[dict]:
    """Build the full menu tree from ``ir.ui.menu`` (unlimited depth).

    Entries are ordered by (sequence, label). The tree is filtered to
    what the current user may access, then ``active`` is set from
    *current_path*.
    """
    if "ir.ui.menu" not in env.registry:
        return []

    prev = env._acl_bypass
    env._acl_bypass = True
    try:
        Menu = env["ir.ui.menu"]
        records = Menu.search(
            [("active", "=", True)], order='"sequence" ASC, "label" ASC'
        )
        nodes_by_id: dict[int, dict] = {}
        ordered_ids: list[int] = []
        for r in records:
            entry = _record_to_entry(r)
            entry["_parent_id"] = r.parent_id.id if r.parent_id else None
            nodes_by_id[r.id] = entry
            ordered_ids.append(r.id)
    finally:
        env._acl_bypass = prev

    items = _attach_children(nodes_by_id, ordered_ids)
    items = [item for item in items if menu_node_visible(env, item)]
    return [_mark_active(item, current_path) for item in items]


def find_menu_entry(
    menu_tree: list, href: str
) -> tuple[dict | None, dict | None]:
    """Return ``(parent, leaf)`` whose ``href`` equals *href* (depth-first)."""
    parent: dict | None = None

    def walk(nodes: list, ancestor: dict | None) -> dict | None:
        nonlocal parent
        for node in nodes:
            if node.get("href") == href:
                parent = ancestor
                return node
            children = node.get("children") or []
            if children:
                found = walk(children, node)
                if found is not None:
                    return found
        return None

    for root in menu_tree:
        leaf = walk([root], None)
        if leaf is not None:
            return parent, leaf
    return None, None


def _node_matches_path(node: dict, current_path: str) -> bool:
    href = node.get("href")
    if href and (
        current_path == href or current_path.startswith(href + "/")
    ):
        return True
    for child in node.get("children") or []:
        if _node_matches_path(child, current_path):
            return True
    return False


def active_menu_root(
    menu_tree: list, current_path: str | None
) -> tuple[dict | None, int | None]:
    """Return ``(root, index)`` for the app matching *current_path*.

    Falls back to the first root with an ``active`` descendant, then the
    first root in the tree.
    """
    if not menu_tree:
        return None, None
    if current_path:
        for index, root in enumerate(menu_tree):
            if _node_matches_path(root, current_path):
                return root, index
        for index, root in enumerate(menu_tree):
            if root.get("active"):
                return root, index
    return menu_tree[0], 0


def menu_entry_href(node: dict) -> str | None:
    """Best navigation target for a group node (own href or first descendant)."""
    href = node.get("href")
    if href:
        return href
    for child in node.get("children") or []:
        child_href = menu_entry_href(child)
        if child_href:
            return child_href
    return None


def menu_layout_context(
    menu_tree: list,
    current_path: str | None,
    *,
    layout: MenuLayout | None = None,
) -> dict[str, Any]:
    """Template keys for sidebar / top-bar navigation chrome."""
    mode = layout or menu_layout()
    ctx: dict[str, Any] = {
        "menu": menu_tree,
        "menu_layout": mode,
    }
    if mode == MENU_LAYOUT_APPS:
        root, root_index = active_menu_root(menu_tree, current_path)
        ctx["menu_roots"] = [
            {**node, "nav_href": menu_entry_href(node), "root_index": index}
            for index, node in enumerate(menu_tree)
        ]
        ctx["menu_active_root"] = root
        ctx["menu_active_root_index"] = root_index
        ctx["menu_secondary"] = (root.get("children") or []) if root else []
    return ctx
