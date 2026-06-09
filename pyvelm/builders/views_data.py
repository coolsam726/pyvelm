"""Fluent container for module DATA view files (velmphp ``ViewsData`` parity)."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pyvelm.types import Menu

from .menus import MenuBranch, MenuItem, flatten_menus


class ViewsData:
    """Assign to ``views_data`` in a module DATA file."""

    def __init__(self) -> None:
        self._views: list[Any] = []
        self._inherits: list[Any] = []
        self._menus: list[MenuBranch | MenuItem | Menu] = []

    @classmethod
    def make(cls) -> ViewsData:
        return cls()

    def views(self, *views: Any) -> ViewsData:
        self._views.extend(views)
        return self

    def view(self, view: Any) -> ViewsData:
        self._views.append(view)
        return self

    def inherits(self, *inherits: Any) -> ViewsData:
        self._inherits.extend(inherits)
        return self

    def inherit(self, inherit: Any) -> ViewsData:
        self._inherits.append(inherit)
        return self

    def menus(self, *menus: MenuBranch | MenuItem | Menu) -> ViewsData:
        self._menus.extend(menus)
        return self

    def menu(self, menu: MenuBranch | MenuItem | Menu) -> ViewsData:
        self._menus.append(menu)
        return self

    def _view_dicts(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for view in self._views:
            if hasattr(view, "to_dict"):
                out.append(view.to_dict())
            else:
                out.append(view)
        return out

    def _inherit_dicts(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for inherit in self._inherits:
            if hasattr(inherit, "to_dict"):
                out.append(inherit.to_dict())
            else:
                out.append(inherit)
        return out

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self._views:
            data["VIEWS"] = self._view_dicts()
        if self._inherits:
            data["VIEW_INHERITS"] = self._inherit_dicts()
        if self._menus:
            flat: list[Menu] = []
            for entry in self._menus:
                flat.extend(flatten_menus([entry]))
            data["MENUS"] = flat
        return data
