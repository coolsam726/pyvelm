"""ORM hooks — called from :mod:`pyvelm.model` after create/write/unlink."""
from __future__ import annotations

from typing import Any

from pyvelm.fields import Boolean, Many2many, Many2one

from .lifecycle import track_create, track_delete, track_write
from .logger import is_audit_model, log_crud


def _serialize_value(field, value: Any) -> Any:
    if value is None or value is False or value == "":
        return None
    if isinstance(field, Many2one):
        if hasattr(value, "_ids"):
            return value._ids[0] if value._ids else None
        return int(value)
    if isinstance(field, Many2many):
        if hasattr(value, "_ids"):
            return list(value._ids)
        return list(value or [])
    if isinstance(field, Boolean):
        return bool(value)
    return field.to_python(value)


def snapshot_record(record, field_names: list[str] | None = None) -> dict[str, Any]:
    """Read stored scalar values for audit snapshots."""
    record.ensure_one()
    names = field_names or list(record._fields.keys())
    out: dict[str, Any] = {}
    for fname in names:
        field = record._fields.get(fname)
        if field is None or not field.is_stored or field.compute:
            continue
        try:
            out[fname] = _serialize_value(field, record[fname])
        except Exception:  # noqa: BLE001
            continue
    return out


def fire_on_create(env, record, vals: dict[str, Any]) -> None:
    if "ir.audit.log" not in env.registry:
        return
    model = record._name
    if is_audit_model(model):
        return
    rid = record.id
    log_crud(env, model, rid, "create", old_values={}, new_values=dict(vals))
    if model == "res.users":
        track_create(env, rid, vals)


def fire_on_write(
    env,
    records,
    vals: dict[str, Any],
    *,
    before_by_id: dict[int, dict[str, Any]] | None = None,
) -> None:
    if "ir.audit.log" not in env.registry or not records._ids:
        return
    model = records._name
    if is_audit_model(model):
        return
    before_by_id = before_by_id or {}
    for rid in records._ids:
        before = before_by_id.get(rid, {})
        log_crud(
            env,
            model,
            rid,
            "write",
            old_values=before,
            new_values=dict(vals),
        )
        if model == "res.users":
            track_write(env, rid, vals, before)


def fire_on_unlink(
    env,
    records,
    *,
    before_by_id: dict[int, dict[str, Any]] | None = None,
) -> None:
    if "ir.audit.log" not in env.registry or not records._ids:
        return
    model = records._name
    if is_audit_model(model):
        return
    before_by_id = before_by_id or {}
    for rid in records._ids:
        before = before_by_id.get(rid, {})
        log_crud(
            env,
            model,
            rid,
            "unlink",
            old_values=before,
            new_values={},
        )
        if model == "res.users":
            track_delete(env, rid)
