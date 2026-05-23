"""Report definition validation (schema v1)."""
from __future__ import annotations

from typing import Any

from ..paths import O2mHop, M2mHop, parse_path
from .format import _VALID_ALIGNS, _VALID_FORMAT_TYPES

REPORT_VERSION = 1
_VALID_AGGREGATES = frozenset({"sum", "avg", "min", "max", "count"})
_VALID_SUBAGGREGATES = frozenset({"string_agg", "count", "sum", "avg", "min", "max"})
_VALID_PARAM_TYPES = frozenset({"string", "integer", "float", "boolean", "date", "datetime"})


class ReportDefinitionError(ValueError):
    """Raised when a report definition fails validation."""


def validate_definition(defn: dict[str, Any], registry) -> None:
    """Validate *defn* in place; raise ``ReportDefinitionError`` on failure."""
    if not isinstance(defn, dict):
        raise ReportDefinitionError("Definition must be a JSON object")
    version = defn.get("version", 1)
    if version != REPORT_VERSION:
        raise ReportDefinitionError(
            f"Unsupported report version {version!r} (expected {REPORT_VERSION})"
        )
    root = defn.get("root")
    if not root or not isinstance(root, str):
        raise ReportDefinitionError("'root' must be a model technical name")
    if root not in registry:
        raise ReportDefinitionError(f"Unknown root model {root!r}")
    columns = defn.get("columns") or []
    groupby = defn.get("groupby") or []
    measures = defn.get("measures") or []
    is_aggregate = bool(groupby and measures)
    if not is_aggregate:
        if not columns or not isinstance(columns, list):
            raise ReportDefinitionError("'columns' must be a non-empty list")
    elif not isinstance(columns, list):
        raise ReportDefinitionError("'columns' must be a list when provided")
    if not isinstance(groupby, list):
        raise ReportDefinitionError("'groupby' must be a list")
    if not isinstance(measures, list):
        raise ReportDefinitionError("'measures' must be a list")
    if measures and not groupby:
        raise ReportDefinitionError("'measures' requires non-empty 'groupby'")
    if groupby and measures:
        # Aggregated report — columns with aggregates or groupby fields only.
        pass
    elif groupby:
        raise ReportDefinitionError(
            "'groupby' without 'measures' is not supported in v1 "
            "(add measures or clear groupby for detail reports)"
        )

    root_cls = registry[root]
    seen_keys: set[str] = set()
    if columns:
        for i, col in enumerate(columns):
            if not isinstance(col, dict):
                raise ReportDefinitionError(f"columns[{i}] must be an object")
            expr = col.get("expr")
            if not expr or not isinstance(expr, str):
                raise ReportDefinitionError(f"columns[{i}].expr must be a string")
            if expr in seen_keys:
                raise ReportDefinitionError(f"Duplicate column expr {expr!r}")
            seen_keys.add(expr)
            label = col.get("label")
            if not label or not isinstance(label, str):
                raise ReportDefinitionError(f"columns[{i}].label must be a string")
            agg = col.get("aggregate")
            subagg = col.get("subaggregate")
            if subagg is not None and subagg not in _VALID_SUBAGGREGATES:
                raise ReportDefinitionError(
                    f"columns[{i}].subaggregate {subagg!r} invalid"
                )
            if agg is not None:
                if agg not in _VALID_AGGREGATES:
                    raise ReportDefinitionError(
                        f"columns[{i}].aggregate {agg!r} invalid "
                        f"(expected one of {sorted(_VALID_AGGREGATES)})"
                    )
                if not groupby:
                    raise ReportDefinitionError(
                        f"columns[{i}].aggregate requires 'groupby'"
                    )
            _validate_column_format(col.get("format"), i)
            _validate_column_path(
                root_cls, expr, registry,
                allow_aggregate=agg is not None,
                subaggregate=subagg,
            )

    for spec in groupby:
        if not isinstance(spec, str):
            raise ReportDefinitionError("groupby entries must be strings")
        _validate_groupby_spec(root_cls, spec, registry)

    for spec in measures:
        if not isinstance(spec, str):
            raise ReportDefinitionError("measures entries must be strings")
        _validate_measure_spec(root_cls, spec, registry)

    filters = defn.get("filters") or []
    if not isinstance(filters, list):
        raise ReportDefinitionError("'filters' must be a list")
    for leaf in filters:
        _validate_domain_leaf(root_cls, leaf, registry, param_mode=False)

    param_filters = defn.get("parameter_filters") or []
    if not isinstance(param_filters, list):
        raise ReportDefinitionError("'parameter_filters' must be a list")
    for leaf in param_filters:
        _validate_domain_leaf(root_cls, leaf, registry, param_mode=True)

    parameters = defn.get("parameters") or []
    if not isinstance(parameters, list):
        raise ReportDefinitionError("'parameters' must be a list")
    param_names: set[str] = set()
    for i, p in enumerate(parameters):
        if not isinstance(p, dict):
            raise ReportDefinitionError(f"parameters[{i}] must be an object")
        name = p.get("name")
        if not name or not isinstance(name, str):
            raise ReportDefinitionError(f"parameters[{i}].name must be a string")
        if name in param_names:
            raise ReportDefinitionError(f"Duplicate parameter name {name!r}")
        param_names.add(name)
        ptype = p.get("type", "string")
        if ptype not in _VALID_PARAM_TYPES:
            raise ReportDefinitionError(
                f"parameters[{i}].type {ptype!r} invalid"
            )

    for leaf in param_filters:
        _check_param_refs(leaf, param_names)

    order = defn.get("order") or []
    if not isinstance(order, list):
        raise ReportDefinitionError("'order' must be a list")
    for item in order:
        if not isinstance(item, str):
            raise ReportDefinitionError("order entries must be strings")
        parts = item.strip().rsplit(None, 1)
        if len(parts) != 2 or parts[1].lower() not in ("asc", "desc"):
            raise ReportDefinitionError(
                f"Invalid order {item!r} (expected 'field asc' or 'field desc')"
            )
        if is_aggregate:
            _validate_aggregate_order_spec(root_cls, parts[0], groupby, measures, registry)
        else:
            _validate_order_field(root_cls, parts[0], registry)


def _validate_order_field(root_cls, expr: str, registry) -> None:
    if expr == "id":
        return
    if "." not in expr:
        if expr not in root_cls._fields:
            raise ReportDefinitionError(f"order field {expr!r} unknown on {root_cls._name}")
        return
    parse_path(root_cls, expr, registry)


def _validate_aggregate_order_spec(
    root_cls, spec: str, groupby: list, measures: list, registry,
) -> None:
    allowed = set(groupby) | set(measures)
    if spec not in allowed:
        raise ReportDefinitionError(
            f"order field {spec!r} must be a groupby or measure in summary reports"
        )


def _validate_column_format(fmt: Any, index: int) -> None:
    if fmt is None:
        return
    if not isinstance(fmt, dict):
        raise ReportDefinitionError(f"columns[{index}].format must be an object")
    ftype = fmt.get("type", "text")
    if ftype not in _VALID_FORMAT_TYPES:
        raise ReportDefinitionError(
            f"columns[{index}].format.type {ftype!r} invalid"
        )
    align = fmt.get("align", "left")
    if align not in _VALID_ALIGNS:
        raise ReportDefinitionError(
            f"columns[{index}].format.align {align!r} invalid"
        )
    decimals = fmt.get("decimals")
    if decimals is not None and not isinstance(decimals, int):
        raise ReportDefinitionError(
            f"columns[{index}].format.decimals must be an integer"
        )
    symbol = fmt.get("symbol")
    if symbol is not None and not isinstance(symbol, str):
        raise ReportDefinitionError(
            f"columns[{index}].format.symbol must be a string"
        )
    if ftype == "currency":
        src = fmt.get("currency_source", "field")
        if src not in ("field", "fixed"):
            raise ReportDefinitionError(
                f"columns[{index}].format.currency_source {src!r} invalid"
            )
        if src == "fixed":
            cid = fmt.get("currency_id")
            if cid is not None and not isinstance(cid, int):
                raise ReportDefinitionError(
                    f"columns[{index}].format.currency_id must be an integer"
                )
        else:
            cf = fmt.get("currency_field")
            if cf is not None and not isinstance(cf, str):
                raise ReportDefinitionError(
                    f"columns[{index}].format.currency_field must be a string"
                )


def _validate_column_path(
    root_cls, expr: str, registry, *, allow_aggregate: bool, subaggregate: str | None = None,
) -> None:
    if expr == "id":
        return
    if "." not in expr:
        if expr not in root_cls._fields:
            raise ReportDefinitionError(
                f"Unknown field {expr!r} on {root_cls._name}"
            )
        field = root_cls._fields[expr]
        if field.private:
            raise ReportDefinitionError(f"Field {expr!r} is private and cannot be exported")
        if not field.is_stored and not allow_aggregate:
            raise ReportDefinitionError(
                f"Field {expr!r} is not stored (cannot use in detail report v1)"
            )
        return
    path = parse_path(root_cls, expr, registry)
    if path.is_m2o_only():
        leaf_cls = registry[path.leaf_model]
        if path.leaf_attr not in leaf_cls._fields:
            raise ReportDefinitionError(f"Unknown leaf field in {expr!r}")
        leaf_field = leaf_cls._fields[path.leaf_attr]
        if leaf_field.private:
            raise ReportDefinitionError(f"Field {expr!r} is private")
        if not leaf_field.is_stored:
            raise ReportDefinitionError(f"Field {expr!r} is not stored")
        return
    # O2m / M2m path — requires subaggregate (default applied at compile time).
    for hop in path.hops:
        if isinstance(hop, (O2mHop, M2mHop)):
            if hop.target_model not in registry:
                raise ReportDefinitionError(f"Unknown comodel in {expr!r}")
    leaf_cls = registry[path.leaf_model]
    if path.leaf_attr not in leaf_cls._fields and path.leaf_attr != "id":
        raise ReportDefinitionError(f"Unknown leaf field in {expr!r}")
    if path.leaf_attr != "id":
        leaf_field = leaf_cls._fields[path.leaf_attr]
        if leaf_field.private:
            raise ReportDefinitionError(f"Field {expr!r} is private")
        if not leaf_field.is_stored:
            raise ReportDefinitionError(f"Field {expr!r} is not stored")
        if subaggregate is None and not allow_aggregate:
            # Implicit default is OK
            pass


def _validate_groupby_spec(root_cls, spec: str, registry) -> None:
    fname = spec.split(":", 1)[0]
    if fname not in root_cls._fields:
        raise ReportDefinitionError(f"groupby field {fname!r} unknown on {root_cls._name}")
    field = root_cls._fields[fname]
    if not field.is_stored:
        raise ReportDefinitionError(f"Cannot group by non-stored field {fname!r}")


def _validate_measure_spec(root_cls, spec: str, registry) -> None:
    if spec == "__count":
        return
    fname = spec.split(":", 1)[0]
    if fname not in root_cls._fields:
        raise ReportDefinitionError(f"measure field {fname!r} unknown on {root_cls._name}")
    field = root_cls._fields[fname]
    if not field.is_stored:
        raise ReportDefinitionError(f"Cannot measure non-stored field {fname!r}")


def _validate_domain_leaf(root_cls, leaf, registry, *, param_mode: bool) -> None:
    if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == "__or__":
        for sub in leaf[2] or []:
            _validate_domain_leaf(root_cls, sub, registry, param_mode=param_mode)
        return
    if not isinstance(leaf, (list, tuple)) or len(leaf) not in (3, 4):
        raise ReportDefinitionError(f"Invalid domain leaf: {leaf!r}")
    attr, op, value = leaf[0], leaf[1], leaf[2]
    if not isinstance(attr, str):
        raise ReportDefinitionError(f"Invalid domain attr: {attr!r}")
    if param_mode and isinstance(value, dict) and "param" in value:
        return
    # Validate path exists (domain compiler will catch op issues).
    if attr == "id":
        return
    if "." not in attr:
        if attr not in root_cls._fields:
            raise ReportDefinitionError(f"Filter field {attr!r} unknown on {root_cls._name}")
        return
    parse_path(root_cls, attr, registry)


def _check_param_refs(leaf, param_names: set[str]) -> None:
    if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == "__or__":
        for sub in leaf[2] or []:
            _check_param_refs(sub, param_names)
        return
    if len(leaf) >= 3 and isinstance(leaf[2], dict) and "param" in leaf[2]:
        pname = leaf[2]["param"]
        if pname not in param_names:
            raise ReportDefinitionError(
                f"parameter_filters references unknown parameter {pname!r}"
            )
