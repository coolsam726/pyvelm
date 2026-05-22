"""Accessors (``get_*_attribute``) and mutators (``set_*_attribute``)."""
from __future__ import annotations

from typing import Any


def _accessor_attr(method_name: str) -> str | None:
    prefix, suffix = "get_", "_attribute"
    if method_name.startswith(prefix) and method_name.endswith(suffix):
        core = method_name[len(prefix) : -len(suffix)]
        return core or None
    return None


def _mutator_attr(method_name: str) -> str | None:
    prefix, suffix = "set_", "_attribute"
    if method_name.startswith(prefix) and method_name.endswith(suffix):
        core = method_name[len(prefix) : -len(suffix)]
        return core or None
    return None


def collect_accessors_mutators(namespace: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Return (accessors, mutators) maps of synthetic attr -> method name."""
    accessors: dict[str, str] = {}
    mutators: dict[str, str] = {}
    for name, attr in namespace.items():
        if not callable(attr) or isinstance(attr, type):
            continue
        acc = _accessor_attr(name)
        if acc is not None:
            accessors[acc] = name
            continue
        mut = _mutator_attr(name)
        if mut is not None:
            mutators[mut] = name
    return accessors, mutators


def merge_maps(bases, key: str) -> dict:
    merged: dict = {}
    for base in bases:
        if base is object:
            continue
        merged.update(getattr(base, key, {}) or {})
    return merged


def apply_mutators(
    model_cls,
    env,
    vals: dict[str, Any],
    *,
    mutators: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run ``set_<field>_attribute`` hooks over *vals* keys present."""
    reg = mutators if mutators is not None else getattr(model_cls, "_vellum_mutators", {})
    if not reg:
        return vals
    out = dict(vals)
    empty = model_cls(env, ())
    for fname, value in list(out.items()):
        method_name = reg.get(fname)
        if not method_name:
            continue
        method = getattr(model_cls, method_name)
        out[fname] = method(empty, value)
    return out


def read_accessor(recordset, attr: str, accessors: dict[str, str]):
    """Resolve a synthetic attribute via its accessor method."""
    recordset.ensure_one()
    method = getattr(recordset.__class__, accessors[attr])
    return method(recordset)
