from __future__ import annotations

from typing import Any, Iterable

# Stage 2 domain language: a list of (attr, operator, value) leaves,
# implicitly AND-ed. Attr names are validated against the model and
# translated to SQL columns; values flow through the field's
# to_sql_param so Many2one accepts recordsets. No polish notation,
# no relational traversal yet.

_SIMPLE_OPS = {"=", "!=", "<", "<=", ">", ">="}


def _resolve(model_cls, attr: str) -> tuple[str, Any]:
    """Return (sql_column, field_or_None) for `attr` on this model.

    `id` is a pseudo-field — not in `_fields` but always queryable.
    Unknown attrs raise; this is the upgrade that catches typos that
    would otherwise reach Postgres as 'column does not exist'.
    """
    if attr == "id":
        return "id", None
    if attr not in model_cls._fields:
        raise ValueError(
            f"Unknown field {attr!r} on {model_cls._name} in domain"
        )
    field = model_cls._fields[attr]
    return field.column, field


def _coerce(field, value):
    """Run value through the field's SQL normalizer if there is one.

    Lets `[('country', '=', france_record)]` work: Many2one.to_sql_param
    extracts the id from the recordset.
    """
    if field is None:
        return value
    return field.to_sql_param(value)


def domain_to_sql(
    domain: Iterable[tuple[str, str, Any]] | None,
    model_cls,
) -> tuple[str, list[Any]]:
    if not domain:
        return "TRUE", []

    clauses: list[str] = []
    params: list[Any] = []

    for leaf in domain:
        if not (isinstance(leaf, (list, tuple)) and len(leaf) == 3):
            raise ValueError(f"Invalid domain leaf: {leaf!r}")
        attr, op, value = leaf
        column, field = _resolve(model_cls, attr)
        col = f'"{column}"'

        if op in _SIMPLE_OPS:
            v = _coerce(field, value)
            if v is None and op == "=":
                clauses.append(f"{col} IS NULL")
            elif v is None and op == "!=":
                clauses.append(f"{col} IS NOT NULL")
            else:
                clauses.append(f"{col} {op} %s")
                params.append(v)
        elif op == "in":
            values = [_coerce(field, v) for v in value]
            if not values:
                clauses.append("FALSE")
            else:
                placeholders = ",".join(["%s"] * len(values))
                clauses.append(f"{col} IN ({placeholders})")
                params.extend(values)
        elif op == "not in":
            values = [_coerce(field, v) for v in value]
            if not values:
                clauses.append("TRUE")
            else:
                placeholders = ",".join(["%s"] * len(values))
                clauses.append(f"{col} NOT IN ({placeholders})")
                params.extend(values)
        elif op == "like":
            clauses.append(f"{col} LIKE %s")
            params.append(value)
        elif op == "ilike":
            clauses.append(f"{col} ILIKE %s")
            params.append(value)
        else:
            raise ValueError(f"Unknown operator: {op!r}")

    return " AND ".join(clauses), params
