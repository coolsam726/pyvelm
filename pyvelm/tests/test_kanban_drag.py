"""Kanban drag-drop helpers."""

from pyvelm import BaseModel, fields
from pyvelm.registry import Registry
from pyvelm.render import (
    _kanban_group_write_value,
    _kanban_resolve_group_field,
)


def _kanban_registry():
    reg = Registry()
    with reg.activate():

        class KanbanStage(BaseModel):
            _name = "test.kanban.stage"
            name = fields.Char()

        class KanbanCard(BaseModel):
            _name = "test.kanban.card"
            stage_id = fields.Many2one("test.kanban.stage")
            done = fields.Boolean(default=False)
            priority = fields.Char()
            sequence = fields.Integer(default=10)

    return reg


def test_kanban_resolve_group_field_arch():
    arch = {"group_by": "stage_id", "sequence": "sequence"}
    view = type("V", (), {"module": "t", "name": "c.kanban", "model": "test.kanban.card"})()
    assert _kanban_resolve_group_field(view, arch, "stage_id") == "stage_id"


def test_kanban_resolve_group_field_url():
    arch = {}
    view = type("V", (), {"module": "t", "name": "c.kanban", "model": "test.kanban.card"})()
    assert _kanban_resolve_group_field(view, arch, "done") == "done"


def test_kanban_group_write_value_m2o():
    reg = _kanban_registry()
    cls = reg["test.kanban.card"]
    assert _kanban_group_write_value(cls, "stage_id", 7) == 7
    assert _kanban_group_write_value(cls, "stage_id", None) is False


def test_kanban_group_write_value_boolean():
    reg = _kanban_registry()
    cls = reg["test.kanban.card"]
    assert _kanban_group_write_value(cls, "done", True) is True
    assert _kanban_group_write_value(cls, "done", False) is False
