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
from contextvars import ContextVar, Token
from typing import Any, Literal

MenuLayout = Literal["sidebar", "apps"]

MENU_LAYOUT_SIDEBAR: MenuLayout = "sidebar"
MENU_LAYOUT_APPS: MenuLayout = "apps"
_VALID_LAYOUTS = frozenset({MENU_LAYOUT_SIDEBAR, MENU_LAYOUT_APPS})
# Deprecated env value; still accepted so older deployments keep working.
_LAYOUT_ALIASES = {"odoo": MENU_LAYOUT_APPS}

request_menu_layout: ContextVar[str | None] = ContextVar(
    "pyvelm.menu.request_menu_layout", default=None
)


def normalize_menu_layout_slug(raw: str | None) -> str | None:
    """Return a validated layout slug, or ``None`` when *raw* is empty/unknown."""
    if not raw or not str(raw).strip():
        return None
    slug = str(raw).strip().lower()
    slug = _LAYOUT_ALIASES.get(slug, slug)
    if slug in _VALID_LAYOUTS:
        return slug  # type: ignore[return-value]
    return None


def resolve_menu_layout(*, context_value: str | None = None) -> MenuLayout:
    """Resolve layout: per-request override → env var → ``apps``."""
    slug = normalize_menu_layout_slug(context_value)
    if slug:
        return slug  # type: ignore[return-value]
    slug = normalize_menu_layout_slug(os.environ.get("PYVELM_MENU_LAYOUT"))
    if slug:
        return slug  # type: ignore[return-value]
    return MENU_LAYOUT_APPS


def set_request_menu_layout(layout: str | None) -> Token:
    return request_menu_layout.set(layout)


def reset_request_menu_layout(token: Token) -> None:
    request_menu_layout.reset(token)


def menu_layout() -> MenuLayout:
    """Resolved shell navigation layout (request override → env var → apps)."""
    return resolve_menu_layout(context_value=request_menu_layout.get())


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
    # Dev-only entries (e.g. the ``technical`` module's editors) are
    # hidden outside ``PYVELM_ENV=development`` so they never reach a
    # production sidebar even if the install hook fired there.
    if node.get("dev_only"):
        from pyvelm.runtime import is_development

        if not is_development():
            return False
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
        "dev_only": bool(getattr(r, "dev_only", False)),
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


def _normalize_menu_path(path: str | None) -> str | None:
    if not path:
        return None
    base = path.split("?", 1)[0].rstrip("/")
    return base or "/"


def menu_active_path_from_breadcrumbs(
    crumbs: list | None,
    *,
    current_path: str | None = None,
    home_href: str | None = None,
) -> str | None:
    """Path used to mark the active menu entry.

    On form and record pages the last breadcrumb with an ``href`` is
    usually the parent list or kanban view. List pages only expose a
    leaf crumb without ``href``, so *current_path* is used instead.
    """
    from pyvelm.home import home_url

    home = _normalize_menu_path(home_href or home_url())
    if crumbs:
        for crumb in reversed(crumbs):
            href = crumb.get("href")
            if not href:
                continue
            path = _normalize_menu_path(href)
            if path == home:
                continue
            return path
    return _normalize_menu_path(current_path)


def _mark_active(item: dict, current_path: str | None) -> dict:
    norm_current = _normalize_menu_path(current_path)
    href = item.get("href")
    norm_href = _normalize_menu_path(href)
    active = bool(
        norm_href
        and norm_current
        and (
            norm_current == norm_href
            or norm_current.startswith(norm_href + "/")
        )
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
    norm_current = _normalize_menu_path(current_path)
    href = node.get("href")
    norm_href = _normalize_menu_path(href)
    if norm_href and norm_current and (
        norm_current == norm_href or norm_current.startswith(norm_href + "/")
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
