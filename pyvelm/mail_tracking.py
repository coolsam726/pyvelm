"""Odoo-style field tracking for MailThread models.

Declare ``tracking=True`` on a field; when ``write()`` changes that field,
the framework posts a ``mail.message`` with ``subtype="mail_tracking"``.
"""
from __future__ import annotations

from typing import Any

from .fields import Boolean, Field, Many2many, Many2one

_EMPTY = "(empty)"


def model_has_mail_thread(model_cls: type) -> bool:
    try:
        from .mail import MailThread
    except ImportError:
        return False
    return any(
        isinstance(base, type) and issubclass(base, MailThread)
        for base in model_cls.__mro__
    )


def tracked_field_names(model_cls: type, fname_iter) -> list[str]:
    names: list[str] = []
    for fname in fname_iter:
        field = model_cls._fields.get(fname)
        if field is None or not getattr(field, "tracking", False):
            continue
        if field.private or field.related:
            continue
        if field.compute and not field.is_stored:
            continue
        names.append(fname)
    return names


def _normalize_scalar(field: Field, value: Any) -> Any:
    if value is None or value is False or value == "":
        return None
    if isinstance(field, Many2one):
        if hasattr(value, "_ids"):
            return value._ids[0] if value._ids else None
        return int(value)
    if isinstance(field, Boolean):
        return bool(value)
    return field.to_python(value)


def _values_equal(field: Field, old: Any, new: Any) -> bool:
    if isinstance(field, Many2many):
        return frozenset(old or ()) == frozenset(new or ())
    return _normalize_scalar(field, old) == _normalize_scalar(field, new)


def _field_label(field: Field, fname: str) -> str:
    return field.string or fname.replace("_", " ").title()


def _format_m2o(env, field: Many2one, raw_id: Any) -> str:
    if raw_id is None:
        return _EMPTY
    comodel = env.registry[field.comodel_name]
    rec = comodel(env, (int(raw_id),))
    if not rec:
        return _EMPTY
    rec.ensure_one()
    display = getattr(rec, "display_name", None)
    if display:
        return str(display)
    name = getattr(rec, "name", None)
    return str(name) if name else str(raw_id)


def _format_m2m(env, field: Many2many, ids: Any) -> str:
    id_set = sorted(int(i) for i in (ids or ()))
    if not id_set:
        return _EMPTY
    comodel = env.registry[field.comodel_name]
    labels: list[str] = []
    for rid in id_set:
        rec = comodel(env, (rid,))
        if not rec:
            continue
        rec.ensure_one()
        display = getattr(rec, "display_name", None)
        if display:
            labels.append(str(display))
        elif getattr(rec, "name", None):
            labels.append(str(rec.name))
        else:
            labels.append(str(rid))
    return ", ".join(labels) if labels else _EMPTY


def format_field_value(env, field: Field, value: Any) -> str:
    if isinstance(field, Many2many):
        return _format_m2m(env, field, value)
    if isinstance(field, Many2one):
        return _format_m2o(env, field, value)
    if value is None or value is False or value == "":
        return _EMPTY
    if isinstance(field, Boolean):
        return "Yes" if value else "No"
    choices = getattr(field, "choices", None)
    if choices:
        text = str(value)
        for val, label in choices:
            if str(val) == text:
                return label
    return str(field.to_python(value))


def snapshot_m2m_per_record(recordset, fname: str) -> dict[int, frozenset[int]]:
    from .fields import Many2many

    field = recordset._fields[fname]
    if not isinstance(field, Many2many) or not recordset._ids:
        return {}
    relation, col1, col2, _, _ = field.resolve_spec(
        type(recordset), recordset.env.registry
    )
    out: dict[int, frozenset[int]] = {}
    for rid in recordset._ids:
        rows = recordset.env.conn.execute(
            f'SELECT "{col2}" FROM "{relation}" WHERE "{col1}" = %s '
            f'ORDER BY "{col2}"',
            [rid],
        ).fetchall()
        out[rid] = frozenset(int(r[0]) for r in rows)
    return out


def snapshot_before_write(
    recordset,
    column_fnames: list[str],
    m2m_fnames: list[str],
) -> dict[int, dict[str, Any]]:
    snapshots: dict[int, dict[str, Any]] = {rid: {} for rid in recordset._ids}
    if column_fnames:
        recordset._read(column_fnames)
        cache = recordset.env.cache
        for rid in recordset._ids:
            for fname in column_fnames:
                if cache.contains(recordset._name, rid, fname):
                    snapshots[rid][fname] = cache.get(recordset._name, rid, fname)
                else:
                    snapshots[rid][fname] = None
    for fname in m2m_fnames:
        for rid, peer_ids in snapshot_m2m_per_record(recordset, fname).items():
            snapshots[rid][fname] = peer_ids
    return snapshots


def _current_column_values(recordset, fname: str) -> dict[int, Any]:
    cache = recordset.env.cache
    out: dict[int, Any] = {}
    for rid in recordset._ids:
        if cache.contains(recordset._name, rid, fname):
            out[rid] = cache.get(recordset._name, rid, fname)
        else:
            recordset.browse(rid)._read([fname])
            out[rid] = cache.get(recordset._name, rid, fname)
    return out


def post_write_tracking(
    recordset,
    column_vals: dict[str, Any],
    m2m_vals: dict[str, Any],
    before: dict[int, dict[str, Any]],
) -> None:
    if getattr(recordset.env, "_mail_tracking_skip", False):
        return
    model_cls = type(recordset)
    if not model_has_mail_thread(model_cls):
        return
    tracked_cols = tracked_field_names(model_cls, column_vals)
    tracked_m2m = tracked_field_names(model_cls, m2m_vals)
    if not tracked_cols and not tracked_m2m:
        return
    if "mail.message" not in recordset.env.registry:
        return

    after_m2m = {
        fname: snapshot_m2m_per_record(recordset, fname) for fname in tracked_m2m
    }
    after_cols = {
        fname: _current_column_values(recordset, fname) for fname in tracked_cols
    }

    for rec in recordset:
        rid = rec.id
        snap = before.get(rid, {})
        lines: list[str] = []
        for fname in tracked_cols:
            field = model_cls._fields[fname]
            old = snap.get(fname)
            new = after_cols[fname].get(rid)
            if _values_equal(field, old, new):
                continue
            label = _field_label(field, fname)
            lines.append(
                f"{label}: {format_field_value(recordset.env, field, old)}"
                f" → {format_field_value(recordset.env, field, new)}"
            )
        for fname in tracked_m2m:
            field = model_cls._fields[fname]
            old = snap.get(fname, frozenset())
            new = after_m2m[fname].get(rid, frozenset())
            if _values_equal(field, old, new):
                continue
            label = _field_label(field, fname)
            lines.append(
                f"{label}: {format_field_value(recordset.env, field, old)}"
                f" → {format_field_value(recordset.env, field, new)}"
            )
        if not lines:
            continue
        rec.message_post(
            "\n".join(lines),
            message_type="notification",
            subtype="mail_tracking",
        )
