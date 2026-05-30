"""Access-control helpers for module install hooks and the web UI.

Convention:

- **Admin** — full CRUD on app models (management UI).
- **User** — internal operators; modules typically grant at least **read**
  so list/form pages load. Omit ``user=`` on sensitive models.
- **Public** — ``group_id=None`` grants (unauthenticated + authenticated).

Use :func:`grant_model_access` in ``hooks.py`` instead of hand-rolling
``ir.model.access`` rows.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyvelm.env import Environment

GROUP_ADMIN = "Admin"
GROUP_USER = "User"
GROUP_PUBLIC = "Public"

_PERM_BITS = ("read", "write", "create", "unlink")


def _perm_dict(spec: str | None) -> dict[str, bool] | None:
    if not spec:
        return None
    key = spec.strip().lower()
    if key in ("crud", "full", "all"):
        return {p: True for p in _PERM_BITS}
    if key == "read":
        return {
            "read": True,
            "write": False,
            "create": False,
            "unlink": False,
        }
    if key in ("rw", "readwrite", "read_write"):
        return {
            "read": True,
            "write": True,
            "create": False,
            "unlink": False,
        }
    if key in ("ru", "read_unlink"):
        return {
            "read": True,
            "write": False,
            "create": False,
            "unlink": True,
        }
    raise ValueError(
        f"Unknown access spec {spec!r}; use crud, read, rw, or read_unlink"
    )


def _group_by_name(env: Environment, name: str):
    if "res.groups" not in env.registry:
        return None
    return env["res.groups"].search([("name", "=", name)], limit=1)


def _ensure_access_row(
    env: Environment,
    *,
    name: str,
    model: str,
    group,
    perms: dict[str, bool],
) -> None:
    if "ir.model.access" not in env.registry:
        return
    Access = env["ir.model.access"]
    domain = [("name", "=", name)]
    if group is None:
        domain.append(("group_id", "=", None))
    else:
        domain.append(("group_id", "=", group.id))
    if Access.search(domain, limit=1):
        return
    Access.create(
        {
            "name": name,
            "model": model,
            "group_id": group,
            "perm_read": perms["read"],
            "perm_write": perms["write"],
            "perm_create": perms["create"],
            "perm_unlink": perms["unlink"],
        }
    )


def grant_model_access(
    env: Environment,
    model: str,
    *,
    admin: str | None = "crud",
    user: str | None = "read",
    public: str | None = None,
) -> None:
    """Seed ``ir.model.access`` rows for *model* (idempotent by row name)."""
    if model not in env.registry:
        return
    specs: list[tuple[str, object, str | None]] = [
        ("Admin", _group_by_name(env, GROUP_ADMIN), admin),
        ("User", _group_by_name(env, GROUP_USER), user),
        ("Public", None, public),
    ]
    for prefix, group, spec in specs:
        perms = _perm_dict(spec)
        if perms is None:
            continue
        if prefix != "Public" and not group:
            continue
        _ensure_access_row(
            env,
            name=f"{prefix}/{model}",
            model=model,
            group=group,
            perms=perms,
        )


def ensure_user_group(env: Environment):
    """Return the internal **User** group, creating it if needed."""
    if "res.groups" not in env.registry:
        return None
    Group = env["res.groups"]
    grp = Group.search([("name", "=", GROUP_USER)], limit=1)
    if grp:
        return grp
    return Group.create({"name": GROUP_USER})


def assign_user_group_to_active_users(env: Environment) -> None:
    """Add **User** to every active non-superuser that lacks it.

    Idempotent one-shot backfill (e.g. migration ``0_23→0_24``). **Not**
    run on every Apps Sync — otherwise dev reloads and upgrades would undo
    deliberate group edits in Settings → Users.
    """
    if "res.users" not in env.registry:
        return
    user_grp = ensure_user_group(env)
    if not user_grp:
        return
    # sudo: bulk user-management write that must touch every account
    # regardless of the caller's grants.
    User = env.sudo()["res.users"]
    for user in User.search([("active", "=", True)]):
        if user.id == env.SUPERUSER_ID:
            continue
        ids = set(user.group_ids.ids)
        if user_grp.id in ids:
            continue
        user.write({"group_ids": list(ids | {user_grp.id})})


def can_view_apps_catalog(env: Environment) -> bool:
    """Return whether the user may open the Apps installer/catalog UI."""
    if env.is_superuser():
        return True
    if "res.users" not in env.registry:
        return False
    return env.can("res.users", "view_any", perm="read")


def user_in_group(env: Environment, group_name: str) -> bool:
    """Return whether the active user belongs to *group_name*."""
    if env.is_superuser():
        return True
    if env.uid is None or "res.users" not in env.registry:
        return False
    grp = _group_by_name(env, group_name)
    if not grp:
        return False
    if env.sudo()["res.users"].search_count([("id", "=", env.uid)]) == 0:
        return False
    user = env["res.users"].browse(env.uid)
    return grp.id in set(user.group_ids.ids)


def template_access(env: Environment, model: str) -> dict[str, bool]:
    """Template-friendly CRUD flags for *model* (hide actions without access)."""
    flags = env.access_flags(model)
    return {
        "can_read": flags["read"],
        "can_write": flags["write"],
        "can_create": flags["create"],
        "can_unlink": flags["unlink"],
    }
