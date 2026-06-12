"""Evaluate view-schema predicates (visibility, required, readonly, domains).

Callables may accept ``(ctx)``, ``(record, env, get)``, ``(record, env)``, or
no arguments. Domain shortcuts (``visible_when``, ``required_when``, …) compile
to the same evaluator used for list search domains.
"""
from __future__ import annotations

import inspect
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Callable

from pyvelm.domain import expand_or_groups, is_domain_leaf, normalize_domain

SchemaPredicate = bool | Callable[..., bool] | list | tuple | None
GetFn = Callable[[str, Any], Any]


@dataclass
class SchemaContext:
    """Runtime context for schema field predicates."""

    env: Any
    record: Any = None
    submitted: dict[str, Any] = field(default_factory=dict)
    mode: str = "edit"
    model_cls: Any = None

    def get(self, name: str, default: Any = None) -> Any:
        if name in self.submitted:
            return self.submitted[name]
        if self.record is not None and getattr(self.record, "_ids", None):
            try:
                value = getattr(self.record, name)
            except (AttributeError, KeyError):
                return default
            from pyvelm.fields import Many2one

            field = self.record._fields.get(name)
            if field is not None and isinstance(field, Many2one):
                if value is None or not getattr(value, "_ids", None):
                    return None
                return value.id
            return value
        return default


def _model_for_ctx(ctx: SchemaContext):
    if ctx.model_cls is not None:
        return ctx.model_cls
    if ctx.record is not None:
        return type(ctx.record)
    return None


def _coerce_relational_value(
    ctx: SchemaContext,
    model_cls,
    fname: str,
    raw: Any,
) -> Any:
    """Turn submitted M2O ids into recordsets so dotted paths can be walked."""
    if raw is None or raw is False or raw == "":
        return None
    if hasattr(raw, "_fields"):
        return raw if getattr(raw, "_ids", None) else None
    if model_cls is None or ctx.env is None:
        return raw
    from pyvelm.fields import Many2one

    fld = model_cls._fields.get(fname)
    if fld is None or not isinstance(fld, Many2one):
        return raw
    try:
        rid = int(raw)
    except (TypeError, ValueError):
        return raw
    if rid <= 0:
        return None
    rec = ctx.env[fld.comodel_name].browse(rid)
    return rec if rec._ids else None


def _walk_relational_path(record: Any, tail: str) -> Any:
    """Follow ``tail`` across browseable recordsets (``country_id.code``, …)."""
    parts = tail.split(".")
    cur = record
    for part in parts:
        if cur is None:
            return None
        if not getattr(cur, "_fields", None):
            return getattr(cur, part, None) if part == parts[-1] else None
        if not getattr(cur, "_ids", None):
            return None
        try:
            cur = getattr(cur, part)
        except (AttributeError, KeyError):
            return None
    from pyvelm.fields import Many2one

    if (
        parts
        and getattr(cur, "_fields", None)
        and parts[-1] in cur._fields
        and isinstance(cur._fields[parts[-1]], Many2one)
        and cur is not None
        and getattr(cur, "_ids", None)
    ):
        v = getattr(cur, parts[-1], None)
        if v is not None and getattr(v, "_ids", None):
            return v.id
    return cur


def _call_value_fn(fn: Callable[..., Any], ctx: SchemaContext) -> Any:
    """Invoke a schema ``default`` callable (same arity rules as predicates)."""
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return fn(ctx)
    if not params:
        return fn()
    if len(params) == 1:
        return fn(ctx)
    if len(params) == 2:
        return fn(ctx.record, ctx.env)
    return fn(ctx.record, ctx.env, ctx.get)


def resolve_spec_default(spec: dict, field, ctx: SchemaContext) -> Any:
    """Evaluate ``Field.default()`` for live / computed display values."""
    fn = spec.get("default")
    if not callable(fn):
        return None
    return _call_value_fn(fn, ctx)


def _call_predicate(fn: Callable[..., bool], ctx: SchemaContext) -> bool:
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return bool(fn(ctx))
    if not params:
        return bool(fn())
    if len(params) == 1:
        return bool(fn(ctx))
    if len(params) == 2:
        return bool(fn(ctx.record, ctx.env))
    return bool(fn(ctx.record, ctx.env, ctx.get))


def _resolve_leaf_value(ctx: SchemaContext, path: str) -> Any:
    """Resolve a dotted path against submitted vals and/or the record.

  Scalars and M2O ids from live forms are coerced through ``env`` so
  nested domains like ``company_id.currency_id.code`` work the same as
  in SQL search domains.
    """
    if "." not in path:
        return ctx.get(path)
    head, tail = path.split(".", 1)
    model_cls = _model_for_ctx(ctx)
    raw = ctx.get(head)
    if raw is None:
        return None
    value = (
        _coerce_relational_value(ctx, model_cls, head, raw)
        if model_cls is not None
        else raw
    )
    if value is None:
        return None
    if hasattr(value, "_fields"):
        return _walk_relational_path(value, tail)
    return getattr(value, tail, None)


def _compare_leaf(value: Any, op: str, expected: Any) -> bool:
    if op == "=":
        return value == expected
    if op == "!=":
        return value != expected
    if op == "<":
        return value is not None and expected is not None and value < expected
    if op == "<=":
        return value is not None and expected is not None and value <= expected
    if op == ">":
        return value is not None and expected is not None and value > expected
    if op == ">=":
        return value is not None and expected is not None and value >= expected
    if op == "in":
        items = expected if isinstance(expected, (list, tuple, set)) else [expected]
        return value in items
    if op == "not in":
        items = expected if isinstance(expected, (list, tuple, set)) else [expected]
        return value not in items
    if op == "like":
        return value is not None and expected is not None and str(expected) in str(value)
    if op == "ilike":
        return (
            value is not None
            and expected is not None
            and str(expected).lower() in str(value).lower()
        )
    raise ValueError(f"Unsupported domain operator {op!r}")


def _eval_domain_tree(tree, ctx: SchemaContext) -> bool:
    kind = tree[0]
    if kind == "leaf":
        leaf = tree[1]
        path, op, expected = leaf[0], leaf[1], leaf[2]
        return _compare_leaf(_resolve_leaf_value(ctx, path), op, expected)
    if kind == "!":
        return not _eval_domain_tree(tree[1], ctx)
    if kind == "&":
        return _eval_domain_tree(tree[1], ctx) and _eval_domain_tree(tree[2], ctx)
    if kind == "|":
        return _eval_domain_tree(tree[1], ctx) or _eval_domain_tree(tree[2], ctx)
    raise ValueError(f"Invalid domain tree node {kind!r}")


def record_matches_domain(domain: list, ctx: SchemaContext) -> bool:
    """Return whether *ctx* satisfies an Odoo-style domain in memory."""
    if not domain:
        return True
    from pyvelm.domain import _parse_polish

    normalized = normalize_domain(expand_or_groups(list(domain)))
    tree, _ = _parse_polish(normalized)
    return _eval_domain_tree(tree, ctx)


def resolve_schema_bool(
    value: SchemaPredicate,
    ctx: SchemaContext,
    *,
    default: bool = True,
) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if callable(value):
        return _call_predicate(value, ctx)
    if isinstance(value, (list, tuple)):
        return record_matches_domain(list(value), ctx)
    return bool(value)


def spec_visible(spec: dict, ctx: SchemaContext) -> bool:
    if spec.get("hidden") is True:
        return False
    hidden = spec.get("hidden")
    if hidden is not None and hidden is not True:
        if not resolve_schema_bool(hidden, ctx, default=False):
            return True
        return False
    if "visible_when" in spec:
        return resolve_schema_bool(spec["visible_when"], ctx, default=True)
    if "visible" in spec:
        return resolve_schema_bool(spec["visible"], ctx, default=True)
    return True


def spec_required(spec: dict, field, ctx: SchemaContext) -> bool:
    if "required_when" in spec:
        if resolve_schema_bool(spec["required_when"], ctx, default=False):
            return True
    if "required" in spec:
        return resolve_schema_bool(spec["required"], ctx, default=False)
    return bool(getattr(field, "required", False))


def spec_readonly_schema(spec: dict, field, ctx: SchemaContext) -> bool:
    if "readonly_when" in spec:
        if resolve_schema_bool(spec["readonly_when"], ctx, default=False):
            return True
    if "readonly" in spec:
        return resolve_schema_bool(spec["readonly"], ctx, default=False)
    return bool(getattr(field, "readonly", False))


def spec_readonly(spec: dict, field) -> bool:
    """Legacy static readonly check (no record context)."""
    if spec.get("readonly") is not None and not callable(spec.get("readonly")):
        if not isinstance(spec.get("readonly"), (list, tuple)):
            return bool(spec["readonly"])
    return bool(getattr(field, "readonly", False))


def parse_live_spec(raw: Any) -> dict[str, Any] | None:
    if not raw:
        return None
    if raw is True:
        return {"debounce": None, "on_blur": False}
    if isinstance(raw, str) and raw == "blur":
        return {"debounce": None, "on_blur": True}
    if isinstance(raw, int):
        return {"debounce": raw, "on_blur": False}
    if isinstance(raw, dict):
        return {
            "debounce": raw.get("debounce"),
            "on_blur": bool(raw.get("on_blur")),
        }
    return None


def _domain_leaf_heads(domain: list | tuple) -> set[str]:
    """Return root field names referenced in a domain's leaf paths."""
    from pyvelm.domain import iter_domain_leaves

    heads: set[str] = set()
    for leaf in iter_domain_leaves(domain):
        heads.add(str(leaf[0]).split(".", 1)[0])
    return heads


def collect_schema_live_drivers(specs: list[dict]) -> set[str]:
    """Field names that should trigger HTMX live re-renders.

    Includes explicit ``live()`` fields plus any field referenced by a
    sibling's ``depends_on`` or ``*_when`` / ``options_domain`` domain.
    """
    drivers: set[str] = set()
    for spec in specs:
        if parse_live_spec(spec.get("live")):
            drivers.add(spec["name"])
        for dep in spec.get("depends_on") or []:
            drivers.add(str(dep).split(".", 1)[0])
        for key in ("visible_when", "required_when", "readonly_when"):
            dom = spec.get(key)
            if isinstance(dom, (list, tuple)):
                drivers |= _domain_leaf_heads(dom)
        dom = spec.get("options_domain")
        if isinstance(dom, (list, tuple)):
            drivers |= _domain_leaf_heads(dom)
    return drivers


def _resolve_domain_value_ref(ctx: SchemaContext, ref: str) -> Any:
    """Resolve ``$field`` or ``$company_id.currency_id.code`` in a domain value."""
    if ref.startswith("$"):
        return _resolve_leaf_value(ctx, ref[1:])
    return _resolve_leaf_value(ctx, ref)


def _resolve_domain_values(domain: list, ctx: SchemaContext) -> list:
    """Materialize ``$path`` and sibling-field references in domain leaf values."""
    out: list = []
    for token in domain:
        if is_domain_leaf(token):
            field, op, val = token[0], token[1], token[2]
            if isinstance(val, str):
                if val.startswith("$"):
                    val = _resolve_domain_value_ref(ctx, val)
                elif val == str(field).split(".", 1)[0]:
                    val = _resolve_leaf_value(ctx, val)
            leaf = (field, op, val)
            if len(token) > 3:
                leaf = leaf + tuple(token[3:])
            out.append(leaf)
        else:
            out.append(token)
    return out


def resolve_schema_domain(
    raw: list | tuple | Callable[..., Sequence] | None,
    ctx: SchemaContext,
) -> list | None:
    """Evaluate a schema domain from a static list or a module-level callable."""
    if raw is None:
        return None
    if callable(raw):
        result = _call_value_fn(raw, ctx)
        if not result:
            return []
        return _resolve_domain_values(list(result), ctx)
    if isinstance(raw, (list, tuple)):
        return _resolve_domain_values(list(raw), ctx)
    return None


def resolve_options_domain(spec: dict, ctx: SchemaContext) -> list | None:
    """Evaluate ``Field.options_domain()`` for M2O/M2M search filtering."""
    return resolve_schema_domain(spec.get("options_domain"), ctx)
