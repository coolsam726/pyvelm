"""Discover exportable models and field paths for the report builder."""
from __future__ import annotations

from ..fields import (
    Boolean, Date, Datetime, Float, Integer, Many2many, Many2one, Monetary, One2many, Text,
)
from ..paths import O2mHop, M2mHop, M2oHop, parse_path

_MAX_PATH_DEPTH = 4
_COLLECTION_SUBAGG = ("string_agg", "count", "sum", "avg", "min", "max")


def _search_text(expr: str, label: str) -> str:
    """Lowercase haystack for client-side combobox search."""
    parts = [expr.replace("_", " "), label, expr]
    parts.extend(expr.split("."))
    return " ".join(dict.fromkeys(p for p in parts if p)).lower()


def monetary_currency_path(amount_expr: str, currency_field: str) -> str:
    """Path from report root to the currency Many2one for a monetary amount."""
    if "." not in amount_expr:
        return currency_field
    prefix = amount_expr.rsplit(".", 1)[0]
    return f"{prefix}.{currency_field}"


def list_active_currencies(env) -> list[dict]:
    """Active currencies for report column formatting."""
    if "res.currency" not in env.registry:
        return []
    try:
        env.check_access("res.currency", "read")
    except PermissionError:
        return []
    Currency = env["res.currency"]
    recs = Currency.search([("active", "=", True)])
    out: list[dict] = []
    for rec in sorted(recs, key=lambda r: (r.code or "", r.id)):
        code = rec.code or ""
        name = rec.name or code
        sym = rec.symbol or code or "$"
        out.append({
            "id": rec.id,
            "code": code,
            "name": name,
            "symbol": sym,
            "label": f"{sym} {code} — {name}".strip(),
        })
    return out


def list_readable_models(env) -> list[dict]:
    """Models the current user may read, sorted by technical name."""
    out: list[dict] = []
    for name, cls in sorted(env.registry.items()):
        if name.startswith("_") or not hasattr(cls, "_fields"):
            continue
        try:
            env.check_access(name, "read")
        except PermissionError:
            continue
        label = getattr(cls, "_description", None) or name
        out.append({"value": name, "label": label})
    return out


def _field_type_name(field) -> str:
    return type(field).__name__


def _is_exportable(field) -> bool:
    return field.is_stored and not getattr(field, "private", False)


def list_exportable_fields(env, model: str, *, max_depth: int = _MAX_PATH_DEPTH) -> dict:
    """Return flat field list + relation paths for the builder picker."""
    if model not in env.registry:
        raise ValueError(f"Unknown model {model!r}")
    env.check_access(model, "read")
    root_cls = env.registry[model]
    fields: list[dict] = []
    paths: list[dict] = []

    def walk(cls, prefix: str, label_prefix: str, depth: int, hop_chain: list) -> None:
        if depth > max_depth:
            return
        for fname, field in sorted(cls._fields.items()):
            if fname == "id":
                if not prefix:
                    fields.append({
                        "expr": "id",
                        "label": "ID",
                        "type": "Integer",
                        "kind": "scalar",
                        "searchText": _search_text("id", "ID"),
                    })
                continue
            if not _is_exportable(field):
                continue
            expr = f"{prefix}.{fname}" if prefix else fname
            leaf_label = field.string or fname
            label = f"{label_prefix} → {leaf_label}" if label_prefix else leaf_label
            ft = _field_type_name(field)

            if isinstance(field, (Many2one, One2many, Many2many)):
                if depth < max_depth:
                    comodel = env.registry[field.comodel_name]
                    try:
                        env.check_access(comodel._name, "read")
                    except PermissionError:
                        continue
                    if isinstance(field, Many2one):
                        paths.append({
                            "expr": expr,
                            "label": label,
                            "type": ft,
                            "kind": "m2o",
                            "comodel": field.comodel_name,
                            "searchText": _search_text(expr, label),
                        })
                        walk(comodel, expr, label, depth + 1, hop_chain + [fname])
                    elif isinstance(field, (One2many, Many2many)):
                        paths.append({
                            "expr": expr,
                            "label": label,
                            "type": ft,
                            "kind": "collection",
                            "comodel": field.comodel_name,
                            "subaggregates": list(_COLLECTION_SUBAGG),
                            "searchText": _search_text(expr, label),
                        })
                        walk(comodel, expr, label, depth + 1, hop_chain + [fname])
                continue

            fields.append({
                "expr": expr,
                "label": label,
                "type": ft,
                "kind": "scalar",
                "subaggregates": None,
                "searchText": _search_text(expr, label),
                **(
                    {"currency_field": field.currency_field}
                    if isinstance(field, Monetary)
                    else {}
                ),
            })

    walk(root_cls, "", "", 0, [])
    return {
        "model": model,
        "fields": fields,
        "paths": paths,
    }


def _model_label(registry, model_name: str) -> str:
    cls = registry[model_name]
    return getattr(cls, "_description", None) or model_name


def _resolve_drill_context(root_model: str, prefix: str, registry) -> tuple[type, list[dict]]:
    """Return the model class at *prefix* and breadcrumb crumbs."""
    root_cls = registry[root_model]
    if not prefix:
        return root_cls, [{
            "prefix": "",
            "label": _model_label(registry, root_model),
            "model": root_model,
        }]
    current = root_cls
    crumbs = [{
        "prefix": "",
        "label": _model_label(registry, root_model),
        "model": root_model,
    }]
    built: list[str] = []
    for attr in prefix.split("."):
        if attr not in current._fields:
            raise ValueError(f"Invalid path segment {attr!r} on {current._name}")
        field = current._fields[attr]
        if not isinstance(field, (Many2one, One2many, Many2many)):
            raise ValueError(f"Path segment {attr!r} is not relational")
        built.append(attr)
        seg = ".".join(built)
        comodel = registry[field.comodel_name]
        crumbs.append({
            "prefix": seg,
            "label": field.string or attr,
            "model": comodel._name,
        })
        current = comodel
    return current, crumbs


def list_fields_level(env, root_model: str, prefix: str = "") -> dict:
    """One level of fields for Odoo-style drill-down picker."""
    if root_model not in env.registry:
        raise ValueError(f"Unknown model {root_model!r}")
    env.check_access(root_model, "read")
    prefix = (prefix or "").strip()
    current_cls, breadcrumb = _resolve_drill_context(root_model, prefix, env.registry)
    env.check_access(current_cls._name, "read")
    depth = len(prefix.split(".")) if prefix else 0
    items: list[dict] = []

    for fname, field in sorted(current_cls._fields.items()):
        if fname == "id":
            expr = f"{prefix}.id" if prefix else "id"
            items.append({
                "name": "id",
                "label": "ID",
                "expr": expr,
                "type": "Integer",
                "kind": "scalar",
                "drillable": False,
                "selectable": True,
            })
            continue
        if not _is_exportable(field):
            continue
        expr = f"{prefix}.{fname}" if prefix else fname
        label = field.string or fname
        ft = _field_type_name(field)

        if isinstance(field, Many2one):
            try:
                env.check_access(field.comodel_name, "read")
            except PermissionError:
                continue
            items.append({
                "name": fname,
                "label": label,
                "expr": expr,
                "type": ft,
                "kind": "m2o",
                "drillable": depth + 1 < _MAX_PATH_DEPTH,
                "selectable": True,
                "comodel": field.comodel_name,
            })
        elif isinstance(field, (One2many, Many2many)):
            try:
                env.check_access(field.comodel_name, "read")
            except PermissionError:
                continue
            items.append({
                "name": fname,
                "label": label,
                "expr": expr,
                "type": ft,
                "kind": "collection",
                "drillable": depth + 1 < _MAX_PATH_DEPTH,
                "selectable": True,
                "comodel": field.comodel_name,
                "subaggregates": list(_COLLECTION_SUBAGG),
            })
        else:
            item = {
                "name": fname,
                "label": label,
                "expr": expr,
                "type": ft,
                "kind": "scalar",
                "drillable": False,
                "selectable": True,
            }
            if isinstance(field, Monetary):
                item["currency_field"] = field.currency_field
            items.append(item)

    return {
        "root": root_model,
        "prefix": prefix,
        "model": current_cls._name,
        "breadcrumb": breadcrumb,
        "items": items,
    }


def models_in_definition(defn: dict, registry) -> set[str]:
    """All model technical names referenced by a definition."""
    root = defn["root"]
    models = {root}
    root_cls = registry[root]

    for col in defn.get("columns") or []:
        expr = col.get("expr", "")
        if "." in expr:
            path = parse_path(root_cls, expr, registry)
            models.add(path.leaf_model)
            for hop in path.hops:
                models.add(hop.target_model)

    for spec in (defn.get("groupby") or []) + (defn.get("measures") or []):
        if spec == "__count":
            continue
        fname = spec.split(":", 1)[0]
        if fname in root_cls._fields:
            f = root_cls._fields[fname]
            if isinstance(f, Many2one):
                models.add(f.comodel_name)

    def walk_domain(leaves):
        for leaf in leaves:
            if isinstance(leaf, (list, tuple)) and len(leaf) == 3 and leaf[0] == "__or__":
                walk_domain(leaf[2] or [])
                continue
            if not isinstance(leaf, (list, tuple)) or len(leaf) < 3:
                continue
            attr = leaf[0]
            if "." in attr:
                path = parse_path(root_cls, attr, registry)
                models.add(path.leaf_model)
                for hop in path.hops:
                    models.add(hop.target_model)

    walk_domain(defn.get("filters") or [])
    walk_domain(defn.get("parameter_filters") or [])
    return models


def check_definition_access(env, defn: dict) -> None:
    """Raise PermissionError if user cannot read any referenced model."""
    for model in models_in_definition(defn, env.registry):
        env.check_access(model, "read")
