"""Form and kanban layout building blocks."""
from __future__ import annotations

from typing import Any

from pyvelm.types import ArchKanbanCard, ArchNotebook, ArchPage, ArchSection, FieldRefLike

from ._normalize import field_specs


class Section:
    """Form section block."""

    def __init__(self, name: str, title: str) -> None:
        self._name = name
        self._title = title
        self._fields: list[FieldRefLike | Any] = []
        self._cols: int | None = None

    @classmethod
    def make(cls, name: str, title: str) -> Section:
        return cls(name, title)

    def fields(self, fields: list[FieldRefLike | Any]) -> Section:
        self._fields = list(fields)
        return self

    def cols(self, cols: int) -> Section:
        self._cols = cols
        return self

    def to_dict(self) -> ArchSection:
        result: ArchSection = {
            "name": self._name,
            "title": self._title,
            "fields": field_specs(self._fields),
        }
        if self._cols is not None:
            result["cols"] = self._cols
        return result


class Page:
    """One tab page inside a form notebook."""

    def __init__(self, name: str, title: str) -> None:
        self._name = name
        self._title = title
        self._fields: list[FieldRefLike | Any] = []
        self._cols: int | None = None

    @classmethod
    def make(cls, name: str, title: str) -> Page:
        return cls(name, title)

    def fields(self, fields: list[FieldRefLike | Any]) -> Page:
        self._fields = list(fields)
        return self

    def cols(self, cols: int) -> Page:
        self._cols = cols
        return self

    def to_dict(self) -> ArchPage:
        result: ArchPage = {
            "name": self._name,
            "title": self._title,
            "fields": field_specs(self._fields),
        }
        if self._cols is not None:
            result["cols"] = self._cols
        return result


class Notebook:
    """Tabbed notebook block on a parent form."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._title: str | None = None
        self._pages: list[ArchPage] = []

    @classmethod
    def make(cls, name: str) -> Notebook:
        return cls(name)

    def title(self, title: str) -> Notebook:
        self._title = title
        return self

    def pages(self, pages: list[Page | ArchPage]) -> Notebook:
        self._pages = [
            p.to_dict() if isinstance(p, Page) else p for p in pages
        ]
        return self

    def to_dict(self) -> ArchNotebook:
        result: ArchNotebook = {"name": self._name, "pages": self._pages}
        if self._title is not None:
            result["title"] = self._title
        return result


class KanbanCard:
    """Kanban card layout block."""

    def __init__(self, title: str) -> None:
        self._title = title
        self._subtitle: str | None = None
        self._fields: list[FieldRefLike | Any] | None = None
        self._badges: list[FieldRefLike | Any] | None = None
        self._image: str | None = None

    @classmethod
    def make(cls, title: str) -> KanbanCard:
        return cls(title)

    def subtitle(self, subtitle: str) -> KanbanCard:
        self._subtitle = subtitle
        return self

    def fields(self, fields: list[FieldRefLike | Any]) -> KanbanCard:
        self._fields = list(fields)
        return self

    def badges(self, badges: list[FieldRefLike | Any]) -> KanbanCard:
        self._badges = list(badges)
        return self

    def image(self, image: str) -> KanbanCard:
        self._image = image
        return self

    def to_dict(self) -> ArchKanbanCard:
        result: ArchKanbanCard = {"title": self._title}
        if self._subtitle is not None:
            result["subtitle"] = self._subtitle
        if self._fields is not None:
            result["fields"] = field_specs(self._fields)
        if self._badges is not None:
            result["badges"] = field_specs(self._badges)
        if self._image is not None:
            result["image"] = self._image
        return result
