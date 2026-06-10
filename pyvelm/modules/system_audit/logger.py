"""Append-only CRUD audit rows."""
from __future__ import annotations

import json
from typing import Any

from .context import request_context

_AUDIT_MODELS = frozenset(
    {"ir.audit.log", "ir.login.log", "ir.user.lifecycle"}
)


def is_audit_model(model_name: str) -> bool:
    return model_name in _AUDIT_MODELS


def _json_values(values: dict[str, Any]) -> str | None:
    if not values:
        return None
    return json.dumps(values, default=str)


def _summary(model: str, res_id: int, action: str) -> str:
    return f"{action} {model}#{res_id}"


def _resolve_company_id(
    env,
    model: str,
    res_id: int,
    old_values: dict,
    new_values: dict,
) -> int | None:
    if model == "res.company" and res_id > 0:
        return res_id
    for key in ("company_id",):
        for bag in (new_values, old_values):
            raw = bag.get(key)
            if raw not in (None, "", False):
                if hasattr(raw, "id"):
                    return int(raw.id)
                return int(raw)
    return env.company_id


def log_crud(
    env,
    model: str,
    res_id: int,
    action: str,
    *,
    old_values: dict | None = None,
    new_values: dict | None = None,
    summary: str | None = None,
) -> None:
    if "ir.audit.log" not in env.registry or is_audit_model(model):
        return
    old_values = old_values or {}
    new_values = new_values or {}
    ctx = request_context(env)
    company_id = _resolve_company_id(env, model, res_id, old_values, new_values)
    audit_env = env.with_company(company_id) if company_id is not None else env
    audit_env.sudo()["ir.audit.log"].create(
        {
            "name": summary or _summary(model, res_id, action),
            "model": model,
            "res_id": res_id,
            "action": action,
            "user_id": audit_env.uid,
            "company_id": company_id,
            "old_values": _json_values(old_values),
            "new_values": _json_values(new_values),
            "ip_address": ctx["ip"] or None,
            "user_agent": ctx["user_agent"] or None,
        }
    )
