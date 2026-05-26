"""Discover Jinja placeholders for ``mail.template`` editors."""

from __future__ import annotations

from .fields import (
    Boolean,
    Char,
    Date,
    Datetime,
    Float,
    Integer,
    Many2one,
    Monetary,
    Text,
    Time,
)

_SCALAR_TYPES = (
    Boolean,
    Char,
    Date,
    Datetime,
    Float,
    Integer,
    Monetary,
    Text,
    Time,
)
_MAX_OBJECT_DEPTH = 2


def _model_label(env, name: str) -> str:
    if name not in env.registry:
        return name
    cls = env.registry[name]
    return getattr(cls, "_description", None) or name


def _collect_model_vars(
    env,
    *,
    root: str,
    model_name: str,
    prefix: str,
    label_prefix: str,
    depth: int,
    max_depth: int,
    out: list[dict],
) -> None:
    if model_name not in env.registry:
        return
    try:
        env.check_access(model_name, "read")
    except PermissionError:
        return

    cls = env.registry[model_name]
    for fname, field in sorted(getattr(cls, "_fields", {}).items()):
        if fname.startswith("_"):
            continue
        if getattr(field, "private", False) or not field.is_stored:
            continue

        expr = f"{prefix}.{fname}" if prefix else f"{root}.{fname}"
        leaf = field.string or fname.replace("_", " ").title()
        label = f"{label_prefix} → {leaf}" if label_prefix else f"{root} → {leaf}"

        if isinstance(field, Many2one):
            out.append({
                "expr": expr,
                "label": label,
                "root": root,
                "type": "many2one",
                "snippet": f"{{{{ {expr} }}}}",
            })
            if depth < max_depth:
                _collect_model_vars(
                    env,
                    root=root,
                    model_name=field.comodel_name,
                    prefix=expr,
                    label_prefix=label,
                    depth=depth + 1,
                    max_depth=max_depth,
                    out=out,
                )
            continue

        if not isinstance(field, _SCALAR_TYPES):
            continue

        out.append({
            "expr": expr,
            "label": label,
            "root": root,
            "type": type(field).__name__,
            "snippet": f"{{{{ {expr} }}}}",
        })


def list_template_variables(env, model: str) -> dict:
    """Variables available in ``mail.template`` Jinja (object / user / company)."""
    variables: list[dict] = []

    if model:
        _collect_model_vars(
            env,
            root="object",
            model_name=model,
            prefix="object",
            label_prefix=_model_label(env, model),
            depth=0,
            max_depth=_MAX_OBJECT_DEPTH,
            out=variables,
        )

    if "res.users" in env.registry:
        _collect_model_vars(
            env,
            root="user",
            model_name="res.users",
            prefix="user",
            label_prefix="User",
            depth=0,
            max_depth=1,
            out=variables,
        )

    if "res.company" in env.registry:
        _collect_model_vars(
            env,
            root="company",
            model_name="res.company",
            prefix="company",
            label_prefix="Company",
            depth=0,
            max_depth=1,
            out=variables,
        )

    variables.append({
        "expr": "ctx",
        "label": "Custom context (ctx)",
        "root": "ctx",
        "type": "dict",
        "snippet": "{{ ctx['key'] }}",
    })

    return {"model": model or "", "variables": variables}
