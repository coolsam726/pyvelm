"""Fluent menu declaration builders."""
from __future__ import annotations

from collections.abc import Sequence

from pyvelm.types import Menu


def view_href(module: str, view: str) -> str:
    return f"/web/views/{module}/{view}"


def menu_ref(module: str, name: str) -> str:
    return f"{module}.{name}"


def _resolve_menu_parent(
    parent: str | tuple[str, str],
    *,
    menu_module: str,
) -> str:
    if isinstance(parent, tuple):
        return menu_ref(parent[0], parent[1])
    return menu_ref(menu_module, parent)


def _resolve_menu_href(
    *,
    href: str | None,
    view: str | None,
    view_module: str | None,
    menu_module: str | None,
) -> str:
    if href is not None and view is not None:
        raise ValueError("menu item: pass href= or view=, not both")
    if href is not None:
        return href
    if view is None:
        raise ValueError("menu item: href= or view= is required")
    mod = view_module or menu_module
    if not mod:
        raise ValueError(
            "menu item: view= requires view_module= or menu_module= "
            "(or use Menus(module).item(...))"
        )
    return view_href(mod, view)


class MenuItem:
    """Fluent leaf menu entry (``MenuItem.make(...).view('partner.list')``)."""

    __slots__ = (
        "_module",
        "_name",
        "_label",
        "_href",
        "_view",
        "_view_module",
        "_parent",
        "_icon",
        "_sequence",
        "_perm",
        "_model",
        "_policy",
        "_dev_only",
        "_built",
    )

    def __init__(self, module: str, name: str, label: str) -> None:
        self._module = module
        self._name = name
        self._label = label
        self._href: str | None = None
        self._view: str | None = None
        self._view_module: str | None = None
        self._parent: str | tuple[str, str] | None = None
        self._icon: str | None = None
        self._sequence = 10
        self._perm: str | None = None
        self._model: str | None = None
        self._policy: str | None = None
        self._dev_only = False
        self._built: Menu | None = None

    @classmethod
    def make(cls, module: str, name: str, label: str) -> MenuItem:
        return cls(module, name, label)

    def href(self, href: str) -> MenuItem:
        self._href = href
        return self

    def view(self, view: str, *, module: str | None = None) -> MenuItem:
        self._view = view
        self._view_module = module
        return self

    def parent(self, parent: str | tuple[str, str]) -> MenuItem:
        self._parent = parent
        return self

    def parent_ref(self, module_dot_name: str) -> MenuItem:
        self._parent = module_dot_name
        return self

    def icon(self, icon: str) -> MenuItem:
        self._icon = icon
        return self

    def sequence(self, sequence: int) -> MenuItem:
        self._sequence = sequence
        return self

    def perm(self, perm: str) -> MenuItem:
        self._perm = perm
        return self

    def model(self, model: str) -> MenuItem:
        self._model = model
        return self

    def policy(self, policy: str) -> MenuItem:
        self._policy = policy
        return self

    def dev_only(self, dev_only: bool = True) -> MenuItem:
        self._dev_only = dev_only
        return self

    def to_dict(self) -> Menu:
        if self._built is not None:
            return self._built
        resolved_parent: str | None = None
        if self._parent is not None:
            if isinstance(self._parent, tuple):
                resolved_parent = menu_ref(self._parent[0], self._parent[1])
            else:
                resolved_parent = _resolve_menu_parent(
                    self._parent, menu_module=self._module
                )
        self._built = menu_item(
            self._name,
            self._label,
            href=self._href,
            view=self._view,
            menu_module=self._module,
            view_module=self._view_module,
            parent=resolved_parent,
            icon=self._icon,
            sequence=self._sequence,
            perm=self._perm,
            model=self._model,
            policy=self._policy,
            dev_only=self._dev_only,
        )
        return self._built

    def flatten(self) -> list[Menu]:
        return [self.to_dict()]


def _set_menu_parent_if_missing(
    entry: Menu | MenuBranch | MenuItem,
    parent_name: str,
    *,
    menu_module: str,
) -> None:
    parent_ref = _resolve_menu_parent(parent_name, menu_module=menu_module)
    if isinstance(entry, MenuBranch):
        if "parent" not in entry.menu:
            entry.menu["parent"] = parent_ref
    elif isinstance(entry, MenuItem):
        if entry._parent is None:
            entry._parent = parent_name
    elif "parent" not in entry:
        entry["parent"] = parent_ref


class MenuBranch:
    """Menu group with optional nested children."""

    __slots__ = ("menu", "_children", "_menu_module")

    def __init__(
        self,
        menu: Menu,
        *,
        menu_module: str,
        children: Sequence[Menu | MenuBranch | MenuItem] | None = None,
    ) -> None:
        self.menu = menu
        self._menu_module = menu_module
        self._children: list[Menu | MenuBranch | MenuItem] = []
        if children:
            self.children(children)

    @classmethod
    def make(cls, module: str, name: str, label: str) -> MenuBranch:
        return cls(menu_group(name, label, menu_module=module), menu_module=module)

    def children(
        self,
        entries: Sequence[Menu | MenuBranch | MenuItem],
    ) -> MenuBranch:
        parent_name = self.menu["name"]
        for entry in entries:
            _set_menu_parent_if_missing(
                entry, parent_name, menu_module=self._menu_module
            )
            self._children.append(entry)
        return self

    def sequence(self, sequence: int) -> MenuBranch:
        self.menu["sequence"] = sequence
        return self

    def icon(self, icon: str) -> MenuBranch:
        self.menu["icon"] = icon
        return self

    def parent(self, parent: str | tuple[str, str]) -> MenuBranch:
        self.menu["parent"] = _resolve_menu_parent(
            parent, menu_module=self._menu_module
        )
        return self

    def dev_only(self, dev_only: bool = True) -> MenuBranch:
        if dev_only:
            self.menu["dev_only"] = True
        return self

    def flatten(self) -> list[Menu]:
        out: list[Menu] = [self.menu]
        for child in self._children:
            if isinstance(child, MenuBranch):
                out.extend(child.flatten())
            elif isinstance(child, MenuItem):
                out.extend(child.flatten())
            else:
                out.append(child)
        return out


def flatten_menus(
    entries: Sequence[Menu | MenuBranch | MenuItem],
) -> list[Menu]:
    out: list[Menu] = []
    for entry in entries:
        if isinstance(entry, MenuBranch):
            out.extend(entry.flatten())
        elif isinstance(entry, MenuItem):
            out.extend(entry.flatten())
        else:
            out.append(entry)
    return out


class Menus:
    """Module-scoped fluent menu builder."""

    def __init__(self, module: str) -> None:
        self.module = module

    def ref(self, name: str) -> str:
        return menu_ref(self.module, name)

    def parent(self, name: str, *, module: str | None = None) -> str:
        return menu_ref(module or self.module, name)

    def view(self, name: str, *, module: str | None = None) -> str:
        return view_href(module or self.module, name)

    def group(
        self,
        name: str,
        label: str,
        *,
        icon: str | None = None,
        sequence: int = 10,
        parent: str | tuple[str, str] | None = None,
        dev_only: bool = False,
    ) -> MenuBranch:
        result = menu_group(
            name,
            label,
            icon=icon,
            sequence=sequence,
            dev_only=dev_only,
            menu_module=self.module,
        )
        if parent is not None:
            result["parent"] = _resolve_menu_parent(
                parent, menu_module=self.module
            )
        return MenuBranch(result, menu_module=self.module)

    def item(
        self,
        name: str,
        label: str,
        *,
        href: str | None = None,
        view: str | None = None,
        view_module: str | None = None,
        parent: str | tuple[str, str] | None = None,
        icon: str | None = None,
        sequence: int = 10,
        perm: str | None = None,
        model: str | None = None,
        policy: str | None = None,
        dev_only: bool = False,
    ) -> MenuItem:
        item = MenuItem.make(self.module, name, label).sequence(sequence)
        if href is not None:
            item.href(href)
        if view is not None:
            item.view(view, module=view_module)
        if parent is not None:
            item.parent(parent)
        if icon is not None:
            item.icon(icon)
        if perm is not None:
            item.perm(perm)
        if model is not None:
            item.model(model)
        if policy is not None:
            item.policy(policy)
        if dev_only:
            item.dev_only(True)
        return item


def menu_group(
    name: str,
    label: str,
    *,
    icon: str | None = None,
    sequence: int = 10,
    parent: str | tuple[str, str] | None = None,
    menu_module: str | None = None,
    dev_only: bool = False,
) -> Menu:
    result: Menu = {"name": name, "label": label, "sequence": sequence}
    if icon is not None:
        result["icon"] = icon
    if parent is not None:
        result["parent"] = _resolve_menu_parent(
            parent, menu_module=menu_module or ""
        )
    if dev_only:
        result["dev_only"] = True
    return result


def menu_item(
    name: str,
    label: str,
    *,
    href: str | None = None,
    view: str | None = None,
    menu_module: str | None = None,
    view_module: str | None = None,
    parent: str | tuple[str, str] | None = None,
    icon: str | None = None,
    sequence: int = 10,
    perm: str | None = None,
    model: str | None = None,
    policy: str | None = None,
    dev_only: bool = False,
) -> Menu:
    resolved_href = _resolve_menu_href(
        href=href,
        view=view,
        view_module=view_module,
        menu_module=menu_module,
    )
    if perm is not None and model is None and not (
        (resolved_href or "").startswith("/web/views/")
    ):
        raise ValueError(
            f"Menu item {name!r}: perm= needs model= for a non-view href "
            f"(nothing to infer the model from)"
        )
    result: Menu = {
        "name": name,
        "label": label,
        "href": resolved_href,
        "sequence": sequence,
    }
    if perm is not None:
        result["access_perm"] = perm
    if model is not None:
        result["access_model"] = model
    if policy is not None:
        result["access_policy"] = str(policy)
    if dev_only:
        result["dev_only"] = True
    if parent is not None:
        if (
            menu_module is None
            and isinstance(parent, str)
            and "." not in parent
        ):
            raise ValueError(
                f"Menu parent {parent!r} is a short name; pass menu_module= "
                "or use Menus(module).item(...)"
            )
        if isinstance(parent, tuple):
            result["parent"] = menu_ref(parent[0], parent[1])
        elif isinstance(parent, str) and "." in parent:
            result["parent"] = parent
        else:
            result["parent"] = menu_ref(menu_module, parent)  # type: ignore[arg-type]
    if icon is not None:
        result["icon"] = icon
    return result
