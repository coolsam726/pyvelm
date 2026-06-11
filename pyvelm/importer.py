"""Intelligent CSV/Excel import and export for list views."""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from pyvelm.fields import (
    Boolean,
    Char,
    Date,
    Datetime,
    Float,
    Integer,
    Many2one,
    Monetary,
    One2many,
    Many2many,
    Text,
)

_IMPORTABLE = (
    Boolean,
    Char,
    Text,
    Integer,
    Float,
    Monetary,
    Date,
    Datetime,
    Many2one,
)

_MAX_IMPORT_ROWS = 2000
_PREVIEW_ROWS = 5


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def list_importable_fields(env, model: str) -> list[dict[str, Any]]:
    """Stored, writable scalar fields suitable for tabular import."""
    if model not in env.registry:
        return []
    cls = env.registry[model]
    out: list[dict[str, Any]] = []
    for fname, field in sorted(cls._fields.items()):
        if fname == "id":
            out.append({
                "name": "id",
                "label": "ID",
                "type": "Integer",
                "required": False,
            })
            continue
        if not isinstance(field, _IMPORTABLE):
            continue
        if field.compute or field.readonly or not field.is_stored:
            continue
        if isinstance(field, Many2one):
            try:
                env.check_access(field.comodel_name, "read")
            except PermissionError:
                continue
        out.append({
            "name": fname,
            "label": field.string or fname,
            "type": type(field).__name__,
            "required": bool(field.required),
            "comodel": getattr(field, "comodel_name", None),
            "choices": getattr(field, "choices", None),
        })
    return out


def suggest_column_mapping(
    headers: list[str],
    fields: list[dict[str, Any]],
) -> dict[int, str]:
    """Map file column indexes to model field names by header heuristics."""
    lookup: dict[str, str] = {}
    for spec in fields:
        lookup[_normalize_key(spec["name"])] = spec["name"]
        lookup[_normalize_key(spec["label"])] = spec["name"]
    mapping: dict[int, str] = {}
    for idx, header in enumerate(headers):
        key = _normalize_key(header)
        if key in lookup:
            mapping[idx] = lookup[key]
    return mapping


def parse_tabular_upload(content: bytes, filename: str) -> tuple[list[str], list[list[Any]]]:
    """Parse CSV or Excel upload into headers + data rows."""
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xlsm", ".xltx", ".xltm")):
        return _parse_xlsx(content)
    return _parse_csv(content)


def _parse_csv(content: bytes) -> tuple[list[str], list[list[Any]]]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    headers = [str(h).strip() for h in rows[0]]
    data = [[_clean_cell(c) for c in row] for row in rows[1:] if any(str(c).strip() for c in row)]
    return headers, data


def _parse_xlsx(content: bytes) -> tuple[list[str], list[list[Any]]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError(
            "openpyxl is required for Excel import (pip install openpyxl)"
        ) from exc
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    raw_rows = list(ws.iter_rows(values_only=True))
    if not raw_rows:
        return [], []
    headers = [str(h or "").strip() for h in raw_rows[0]]
    data = []
    for row in raw_rows[1:]:
        cells = [_clean_cell(c) for c in row]
        if any(str(c).strip() for c in cells):
            data.append(cells)
    return headers, data


def _clean_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    return value


def _resolve_m2o(env, comodel: str, raw: Any) -> int | None:
    if raw is None or raw == "" or raw is False:
        return None
    Model = env[comodel]
    text = str(raw).strip()
    if text.isdigit():
        rec = Model.browse(int(text))
        if rec.exists():
            return rec.id
    name_field = "name" if "name" in Model._fields else None
    if name_field:
        found = Model.search([(name_field, "=", text)], limit=1)
        if found:
            return found.id
        found = Model.search([(name_field, "ilike", text)], limit=1)
        if found:
            return found.id
    raise ValueError(f"Cannot resolve {comodel} reference {text!r}")


def _coerce_field_value(env, model: str, fname: str, raw: Any) -> Any:
    cls = env.registry[model]
    field = cls._fields.get(fname)
    if field is None:
        raise ValueError(f"Unknown field {fname!r}")
    if isinstance(field, Many2one):
        return _resolve_m2o(env, field.comodel_name, raw)
    if isinstance(field, Boolean):
        if raw is None or raw == "":
            return False
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in ("1", "true", "yes", "y", "on"):
            return True
        if text in ("0", "false", "no", "n", "off"):
            return False
        raise ValueError(f"Invalid boolean value {raw!r}")
    if isinstance(field, Char) and getattr(field, "choices", None):
        if raw is None or raw == "":
            return None
        text = str(raw).strip()
        for value, label in field.choices or []:
            if text == value or text == label:
                return value
        raise ValueError(f"Invalid selection {text!r} for {fname}")
    return field.to_python(raw)


def build_row_vals(
    env,
    model: str,
    row: list[Any],
    mapping: dict[int, str],
) -> dict[str, Any]:
    vals: dict[str, Any] = {}
    for col_idx, fname in mapping.items():
        if not fname or fname == "_skip":
            continue
        if col_idx >= len(row):
            continue
        raw = row[col_idx]
        if raw is None or raw == "":
            continue
        vals[fname] = _coerce_field_value(env, model, fname, raw)
    return vals


def import_rows(
    env,
    model: str,
    rows: list[list[Any]],
    mapping: dict[int, str],
    *,
    update_by_id: bool = False,
) -> dict[str, Any]:
    """Create or update records from parsed tabular rows."""
    env.check_access(model, "create")
    Model = env[model]
    created = 0
    updated = 0
    errors: list[dict[str, Any]] = []
    for line_no, row in enumerate(rows, start=2):
        try:
            vals = build_row_vals(env, model, row, mapping)
            if not vals:
                continue
            record_id = vals.pop("id", None)
            if update_by_id and record_id:
                env.check_access(model, "write")
                rec = Model.browse(int(record_id))
                if not rec.exists():
                    raise ValueError(f"Record id={record_id} not found")
                rec.write(vals)
                updated += 1
            else:
                Model.create(vals)
                created += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"line": line_no, "error": str(exc)})
    return {
        "created": created,
        "updated": updated,
        "errors": errors,
        "total": len(rows),
    }


def export_list_data(
    env,
    model: str,
    fields_spec: list[dict],
    records,
) -> tuple[list[str], list[list[Any]]]:
    """Build export headers and rows for a recordset."""
    cls = env.registry[model]
    columns: list[tuple[str, str]] = []
    for spec in fields_spec:
        fname = spec["name"]
        if fname not in cls._fields:
            continue
        field = cls._fields[fname]
        if isinstance(field, (One2many, Many2many)):
            continue
        columns.append((fname, spec.get("label") or field.string or fname))

    headers = [label for _fname, label in columns]
    rows: list[list[Any]] = []
    for rec in records:
        row: list[Any] = []
        for fname, _label in columns:
            row.append(_export_cell(getattr(rec, fname, None)))
        rows.append(row)
    return headers, rows


def _export_cell(value: Any) -> Any:
    if value is None or value is False:
        return ""
    if hasattr(value, "_ids"):
        if len(value._ids) == 1:
            rec = value
            if hasattr(rec, "display_name"):
                return rec.display_name
            if hasattr(rec, "name"):
                return rec.name
            return value._ids[0]
        return ",".join(str(i) for i in value._ids)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, default=str)
    return value


def import_template_fields_for_view(env, view) -> list[dict[str, Any]]:
    """Importable fields for a list view template, in column order (+ id)."""
    importable = list_importable_fields(env, view.model)
    by_name = {spec["name"]: spec for spec in importable}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    if "id" in by_name:
        ordered.append(by_name["id"])
        seen.add("id")
    from .views import resolve_arch

    arch = resolve_arch(view)
    for spec in arch.get("fields", []):
        fname = spec["name"]
        if fname in by_name and fname not in seen:
            ordered.append(by_name[fname])
            seen.add(fname)
    for spec in importable:
        if spec["name"] not in seen:
            ordered.append(spec)
    return ordered


def import_template_headers(fields: list[dict[str, Any]]) -> list[str]:
    """Column headers for a blank import template (Odoo-style labels)."""
    return [spec.get("label") or spec["name"] for spec in fields]


def import_template_xlsx_bytes(
    headers: list[str],
    *,
    title: str = "Import",
) -> bytes:
    """Blank Excel import template (header row only) via openpyxl."""
    return export_xlsx_bytes(headers, [], title=title)


def export_csv_bytes(headers: list[str], rows: list[list[Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8-sig")


def export_xlsx_bytes(headers: list[str], rows: list[list[Any]], *, title: str = "Export") -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError(
            "openpyxl is required for Excel export (pip install openpyxl)"
        ) from exc
    wb = Workbook()
    ws = wb.active
    ws.title = (title[:31] if title else "Export") or "Export"
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def encode_import_payload(headers: list[str], rows: list[list[Any]]) -> str:
    """JSON payload for the preview → run step (capped)."""
    capped = rows[:_MAX_IMPORT_ROWS]
    return json.dumps({"headers": headers, "rows": capped})


def decode_import_payload(raw: str) -> tuple[list[str], list[list[Any]]]:
    data = json.loads(raw)
    return list(data.get("headers") or []), list(data.get("rows") or [])


def mapping_from_form(
    form,
    headers: list[str],
    fields: list[dict[str, Any]],
) -> dict[int, str]:
    """Read column mapping selects from the import preview form."""
    mapping: dict[int, str] = {}
    for key, value in form.items():
        if not str(key).startswith("map_"):
            continue
        try:
            idx = int(str(key)[4:])
        except ValueError:
            continue
        if value:
            mapping[idx] = str(value)
    if not mapping:
        mapping = suggest_column_mapping(headers, fields)
    return mapping


class ImportTestAbort(Exception):
    """Raised to roll back a dry-run import test transaction."""
