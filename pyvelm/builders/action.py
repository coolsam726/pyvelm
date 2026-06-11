"""Toolbar action builders for list ``page_actions`` and form ``header_actions``."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .layout import Section


class ActionForm:
    """Inline form schema for view-action dialogs."""

    def __init__(self) -> None:
        self._sections: list[dict] = []
        self._cols: int | None = None
        self._model: str | None = None

    @classmethod
    def make(cls) -> ActionForm:
        return cls()

    def model(self, model: str) -> ActionForm:
        self._model = model
        return self

    def cols(self, cols: int) -> ActionForm:
        self._cols = cols
        return self

    def section(
        self,
        name: str,
        title: str,
        fields: list[Any],
    ) -> ActionForm:
        section = Section.make(name, title).fields(fields)
        if self._cols is not None:
            section.cols(self._cols)
        self._sections.append(section.to_dict())
        return self

    def to_dict(self) -> dict:
        arch: dict = {"sections": list(self._sections)}
        if self._cols is not None:
            arch["cols"] = self._cols
        if self._model:
            arch["model"] = self._model
        return arch


class Action:
    """Declares a toolbar action on list or form/detail views."""

    def __init__(self, label: str) -> None:
        self._label = label
        self._url: str | None = None
        self._method: str | None = None
        self._confirm: str | None = None
        self._perm: str | None = None
        self._model: str | None = None
        self._policy: str | None = None
        self._full_page: bool | None = None
        self._form: dict | None = None
        self._form_view: str | None = None
        self._form_module: str | None = None

    @classmethod
    def make(cls, label: str) -> Action:
        return cls(label)

    def url(self, url: str) -> Action:
        self._url = url
        return self

    def method(self, method: str) -> Action:
        self._method = method.upper()
        return self

    def confirm(self, confirm: str) -> Action:
        self._confirm = confirm
        return self

    def perm(self, perm: str) -> Action:
        self._perm = perm
        return self

    def model(self, model: str) -> Action:
        self._model = model
        return self

    def policy(self, policy: str) -> Action:
        self._policy = policy
        return self

    def full_page(self, full_page: bool = True) -> Action:
        self._full_page = full_page
        return self

    def form_view(self, form_view: str, module: str | None = None) -> Action:
        self._form_view = form_view
        if module:
            self._form_module = module
        return self

    def form(
        self,
        form: ActionForm | Callable[[ActionForm], ActionForm],
    ) -> Action:
        schema = form if isinstance(form, ActionForm) else form(ActionForm.make())
        arch = schema.to_dict()
        if not arch.get("sections"):
            raise ValueError(
                f"Action {self._label!r} inline form requires at least one section."
            )
        self._form = arch
        if self._model is None and arch.get("model"):
            self._model = str(arch["model"])
        return self

    def to_dict(self) -> dict:
        if not self._label:
            raise ValueError("View action requires a label.")
        has_inline = bool(
            self._form and (self._form.get("sections") or [])
        )
        has_stored = bool(self._form_view)
        has_url = bool(self._url)
        if not has_inline and not has_stored and not has_url:
            raise ValueError(
                f"Action {self._label!r} requires url(), formView(), or form()."
            )
        if has_inline and not self._model:
            raise ValueError(
                f"Action {self._label!r} inline form requires model() "
                "on the action or ActionForm."
            )
        action: dict = {"label": self._label}
        if has_url:
            action["url"] = self._url
        if self._method:
            action["method"] = self._method
        if self._confirm:
            action["confirm"] = self._confirm
        if self._perm:
            action["perm"] = self._perm
        if self._model:
            action["model"] = self._model
        if self._policy:
            action["policy"] = self._policy
        if self._full_page is not None:
            action["full_page"] = self._full_page
        if has_stored:
            action["form_view"] = self._form_view
        if self._form_module:
            action["form_module"] = self._form_module
        if has_inline:
            action["form"] = self._form
        return action


def action_specs(actions: list[Any]) -> list[dict]:
    """Normalize a list of :class:`Action` instances or raw dicts."""
    out: list[dict] = []
    for item in actions:
        if isinstance(item, Action):
            out.append(item.to_dict())
        else:
            out.append(dict(item))
    return out
