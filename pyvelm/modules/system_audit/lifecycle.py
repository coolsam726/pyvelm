"""User lifecycle events on ``res.users``."""
from __future__ import annotations

import json
from typing import Any


def log_event(
    env,
    user_id: int,
    event: str,
    detail: dict | None = None,
) -> None:
    if "ir.user.lifecycle" not in env.registry:
        return
    env.sudo()["ir.user.lifecycle"].create(
        {
            "user_id": user_id,
            "event": event,
            "detail": json.dumps(detail, default=str) if detail else None,
            "actor_id": env.uid,
        }
    )


def track_create(env, user_id: int, values: dict[str, Any]) -> None:
    log_event(
        env,
        user_id,
        "created",
        {
            "name": values.get("name"),
            "email": values.get("email") or values.get("login"),
            "active": values.get("active", True),
        },
    )


def track_write(
    env,
    user_id: int,
    values: dict[str, Any],
    before: dict[str, Any] | None = None,
) -> None:
    if not values:
        return
    row = before or {}
    if "active" in values:
        was_active = bool(row.get("active", True))
        now_active = bool(values["active"])
        if was_active != now_active:
            log_event(
                env,
                user_id,
                "activated" if now_active else "deactivated",
                {"active": now_active},
            )
    if "password" in values:
        log_event(env, user_id, "password_changed")
    if "group_ids" in values:
        log_event(
            env,
            user_id,
            "groups_changed",
            {
                "before": row.get("group_ids"),
                "after": values["group_ids"],
            },
        )


def track_delete(env, user_id: int) -> None:
    log_event(env, user_id, "deleted")
