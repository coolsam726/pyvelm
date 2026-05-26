"""Install / upgrade hooks for the base module.

`install(env)` runs on first install only (after schema setup, before
view sync). Seeds a default Admin group and a superuser with id=1
plus a Public group for unauthenticated access grants.

The mail-dispatcher seed (``_seed_mail_dispatcher``) is factored out
so the 0_8_to_0_9 migration can call it for already-installed
databases that won't re-run ``install()``.
"""
from __future__ import annotations

import json
import re

# UI-chrome image fields whose Char value may hold an
# `/api/attachment/<id>/download` URL. Attachments behind these are
# served to everyone, so they're flagged ``public`` (see
# ``classify_chrome_attachments_public``).
_CHROME_IMAGE_FIELDS: dict[str, tuple[str, ...]] = {
    "res.company": ("logo_url", "logo_url_dark", "favicon_url"),
    "res.users": ("avatar_url",),
}

_DOWNLOAD_URL_RE = re.compile(r"/api/attachment/(\d+)/download")


def attachment_id_from_download_url(value: str | None) -> int | None:
    """Return the attachment id embedded in a download URL, or None.

    Only matches the framework's own ``/api/attachment/<id>/download``
    shape — external URLs (``https://…``) yield None and stay untouched.
    """
    if not value:
        return None
    m = _DOWNLOAD_URL_RE.search(value)
    return int(m.group(1)) if m else None


def install(env):
    Group = env["res.groups"]
    User = env["res.users"]

    admin_group = Group.create({"name": "Admin"})
    Group.create({"name": "User"})
    Group.create({"name": "Public"})

    # Seed the currency list before the company so the company can be
    # created with a non-NULL currency_id.
    _seed_currencies(env)

    # Seed the default company before creating users/partners so that
    # FK constraints are satisfied.
    company = None
    if "res.company" in env.registry:
        company_vals = {"name": "My Company", "active": True}
        if "res.currency" in env.registry:
            usd = env["res.currency"].search([("code", "=", "USD")], limit=1)
            if usd:
                company_vals["currency_id"] = usd
        company = env["res.company"].create(company_vals)

    # The superuser is hard-coded to uid=1 — that's what
    # `Environment.is_superuser()` checks. Postgres SERIAL hands out
    # 1 to the first INSERT, and we INSERT this user before any other
    # in the install lifecycle, so the convention holds.
    user_vals = {
        "name": "Administrator",
        "login": "admin",
        "password": "admin",  # bcrypt-hashed by the Password field
        "group_ids": [admin_group],
    }
    if company is not None:
        user_vals["company_id"] = company
    User.create(user_vals)

    # Grant Admin full CRUD on the base-owned management surface.
    if "ir.model.access" in env.registry:
        Access = env["ir.model.access"]
        for model in (
            "ir.actions.server",
            "base.automation",
            "ir.cron",
            "mail.message",
            "res.company",
            "ir.ui.menu",
            "ir.ui.view",
            "res.currency",
            "res.currency.rate",
            "ir.attachment",
        ):
            if model in env.registry:
                Access.create(
                    {
                        "name": f"Admin/{model}",
                        "model": model,
                        "group_id": admin_group,
                        "perm_read": True,
                        "perm_write": True,
                        "perm_create": True,
                        "perm_unlink": True,
                    }
                )

    # UI arch is not business data — every authenticated session needs
    # read access to render list/form/kanban views (menus already bypass
    # ACL in the renderer; views do not).
    _seed_ui_view_read_access(env)
    _seed_res_users_self_read(env)
    _seed_res_groups_read_access(env)

    # NOTE: company scoping is enforced at the model level by
    # `BaseModel.search` for any model that opts in via
    # `_company_scoped = True`. Earlier versions also seeded a global
    # `ir.rule` for res.partner doing the same job — the rule was
    # redundant and contradicted the model filter (the rule allowed
    # records with NULL company_id; the model filter excluded them).
    # Module-level filter wins; ir.rule company scoping intentionally
    # NOT seeded. Apps that need richer per-group company logic should
    # add their own rules.

    # Mail dispatcher: server action + ir.cron entry that drains
    # mail.message rows in state="outgoing".
    _seed_mail_dispatcher(env)

    # ECB exchange-rate fetcher: server action + ir.cron entry that
    # refreshes res.currency.rate from the ECB daily feed. Seeded
    # inactive — admins opt in from Settings → Scheduled Actions.
    _seed_rate_fetcher(env)


def sync(env):
    """Runs on Apps Sync — housekeeping that should not require reinstall."""
    _purge_smoke_test_cron(env)
    # Backfill on every sync/upgrade — idempotent; fixes DBs that never
    # ran the 0_21→0_22 migration or were synced at matching VERSION.
    _seed_ui_view_read_access(env)
    _seed_res_users_self_read(env)
    _seed_res_groups_read_access(env)
    classify_chrome_attachments_public(env)
    # Do not call assign_user_group_to_active_users here — it ran on
    # upgrade via migration 0_23→0_24 and must not re-add **User** on
    # every dev reload (serve.py runs load_and_install) after an admin
    # removes the group from an account (e.g. Sales-only operators).


def classify_chrome_attachments_public(env) -> None:
    """Flag attachments behind UI-chrome image fields as ``public``.

    Backfill for assets uploaded before the ``public`` flag existed: scan
    ``res.company`` logos/favicon and ``res.users`` avatars for
    ``/api/attachment/<id>/download`` URLs and mark those rows public so
    they render for non-admins (and the anonymous login screen). New
    uploads set the flag at upload time; this only repairs old data.

    Idempotent — only writes rows not already public. Runs under sudo so
    it works regardless of the syncing user's grants.
    """
    if "ir.attachment" not in env.registry:
        return
    senv = env.sudo()
    ids: set[int] = set()
    for model, fields in _CHROME_IMAGE_FIELDS.items():
        if model not in env.registry:
            continue
        present = [f for f in fields if f in env.registry[model]._fields]
        if not present:
            continue
        for rec in senv[model].search([]):
            for fname in present:
                att_id = attachment_id_from_download_url(getattr(rec, fname))
                if att_id is not None:
                    ids.add(att_id)
    if not ids:
        return
    Attachment = senv["ir.attachment"]
    rows = Attachment.search([("id", "in", list(ids)), ("public", "=", False)])
    for att in rows:
        att.write({"public": True})


def _purge_smoke_test_cron(env) -> None:
    """Remove cron rows left by ``examples/basic.py`` Stage 6 (pre-0.6 cleanup).

    Those tests used to create ``Test cron`` / ``Cron tick`` targeting
    ``res.partner`` without deleting them, which spams the cron runner on
    databases that do not load the partners example module.
    """
    if "ir.cron" not in env.registry or "ir.actions.server" not in env.registry:
        return
    Cron = env["ir.cron"]
    Action = env["ir.actions.server"]
    prev = env._acl_bypass
    env._acl_bypass = True
    try:
        for cron in Cron.search([("name", "=", "Test cron")]):
            action = cron.action_id
            with env.transaction():
                cron.unlink()
            if action:
                action.ensure_one()
                if action.name == "Cron tick":
                    with env.transaction():
                        action.unlink()
        for action in Action.search([("name", "=", "Cron tick")]):
            action.ensure_one()
            with env.transaction():
                action.unlink()
    finally:
        env._acl_bypass = prev


def _seed_ui_view_read_access(env):
    """Idempotently grant read on ``ir.ui.view`` to everyone (group_id=None).

    Callable from the install hook and from migrations so databases that
    already ran ``install()`` before this grant existed still work for
    non-admin users.
    """
    if "ir.model.access" not in env.registry:
        return
    if "ir.ui.view" not in env.registry:
        return
    Access = env["ir.model.access"]
    if Access.search(
        [("model", "=", "ir.ui.view"), ("group_id", "=", None)],
        limit=1,
    ):
        return
    Access.create(
        {
            "name": "Everyone/ir.ui.view",
            "model": "ir.ui.view",
            "group_id": None,
            "perm_read": True,
        }
    )


def _seed_res_users_self_read(env) -> None:
    """Grant read on ``res.users`` for everyone, scoped to the active uid.

    Authenticated users must load their own row for the shell, session, and
    profile flows. ``perm_write`` is intentionally omitted — self-service
    profile/password routes use ACL bypass; only Admin may edit other users.
    """
    if "ir.model.access" not in env.registry or "ir.rule" not in env.registry:
        return
    if "res.users" not in env.registry:
        return
    Access = env["ir.model.access"]
    Rule = env["ir.rule"]
    if not Access.search(
        [
            ("model", "=", "res.users"),
            ("group_id", "=", None),
            ("perm_read", "=", True),
        ],
        limit=1,
    ):
        Access.create(
            {
                "name": "Everyone/res.users",
                "model": "res.users",
                "group_id": None,
                "perm_read": True,
            }
        )
    rule_name = "Own user record only"
    if not Rule.search(
        [("model", "=", "res.users"), ("name", "=", rule_name)],
        limit=1,
    ):
        Rule.create(
            {
                "name": rule_name,
                "model": "res.users",
                "group_id": None,
                "perm_read": True,
                "domain": json.dumps([["id", "=", {"placeholder": "uid"}]]),
            }
        )


def _seed_res_groups_read_access(env) -> None:
    """Read-only on ``res.groups`` for everyone — group labels in the shell."""
    if "ir.model.access" not in env.registry:
        return
    if "res.groups" not in env.registry:
        return
    Access = env["ir.model.access"]
    if Access.search(
        [
            ("model", "=", "res.groups"),
            ("group_id", "=", None),
            ("perm_read", "=", True),
        ],
        limit=1,
    ):
        return
    Access.create(
        {
            "name": "Everyone/res.groups",
            "model": "res.groups",
            "group_id": None,
            "perm_read": True,
        }
    )


def _seed_currencies(env):
    """Idempotently seed a small list of currencies + opening rates.

    Looks each currency up by ``code`` before creating so re-running
    (from either the install hook or the 0_9_to_0_10 migration) is a
    no-op. Rates are stored as "units per implicit reference" with
    USD = 1.0; conversion math doesn't reference USD by name.
    """
    if "res.currency" not in env.registry:
        return
    if "res.currency.rate" not in env.registry:
        return
    from datetime import datetime

    Currency = env["res.currency"]
    Rate = env["res.currency.rate"]
    seeded_at = datetime.utcnow()

    # (code, name, symbol, rounding, opening rate vs. implicit reference).
    # Real-world rates change daily — these are illustrative starter
    # values, not advice. Operators should replace via the UI.
    seed = [
        ("USD", "US Dollar", "$", 0.01, 1.00),
        ("EUR", "Euro", "€", 0.01, 0.92),
        ("GBP", "Pound Sterling", "£", 0.01, 0.79),
        ("JPY", "Japanese Yen", "¥", 1.0, 149.5),
    ]
    for code, name, symbol, rounding, rate in seed:
        existing = Currency.search([("code", "=", code)], limit=1)
        if existing:
            ccy = existing
        else:
            ccy = Currency.create(
                {
                    "code": code,
                    "name": name,
                    "symbol": symbol,
                    "rounding": rounding,
                    "active": True,
                }
            )
        # Only create an opening rate if the currency has none. We
        # never overwrite existing rates — operators manage them.
        if not Rate.search([("currency_id", "=", ccy.id)], limit=1):
            Rate.create(
                {
                    "currency_id": ccy.id,
                    "date": seeded_at,
                    "rate": rate,
                }
            )


def _seed_mail_dispatcher(env):
    """Idempotently install the outgoing-mail dispatcher cron.

    Creates ``ir.actions.server`` "Mail dispatcher" + ``ir.cron``
    "Mail dispatcher" pointing at it. The action runs a tiny code
    snippet that calls ``Message.dispatch_outgoing(env)``.

    Both rows are looked up by name first so re-running this (from
    either the install hook or the 0_8_to_0_9 migration) is a no-op.
    """
    if "ir.actions.server" not in env.registry:
        return
    if "ir.cron" not in env.registry:
        return
    if "mail.message" not in env.registry:
        return

    Action = env["ir.actions.server"]
    Cron = env["ir.cron"]
    action_name = "Mail dispatcher"
    cron_name = "Mail dispatcher"

    action = Action.search([("name", "=", action_name)], limit=1)
    if not action:
        action = Action.create(
            {
                "name": action_name,
                "model": "mail.message",
                "action_type": "code",
                # `env` is in scope inside server-action code.
                "code": "env['mail.message'].dispatch_outgoing(env)\n",
            }
        )

    if not Cron.search([("name", "=", cron_name)], limit=1):
        Cron.create(
            {
                "name": cron_name,
                "action_id": action,
                # Tick once a minute — matches the cron runner's default
                # interval so messages don't pile up.
                "interval_number": 1,
                "interval_type": "minutes",
                "active": True,
            }
        )


def _seed_rate_fetcher(env):
    """Idempotently install the ECB rate-fetcher cron.

    Mirrors ``_seed_mail_dispatcher`` but seeds the cron with
    ``active=False`` so a fresh install never makes outbound HTTP
    requests until an operator opts in. Admins flip the switch in
    Settings → Scheduled Actions when they want daily refreshes.

    Both rows are looked up by name first so re-running this (from
    either the install hook or the 0_12_to_0_13 migration) is a no-op.
    """
    if "ir.actions.server" not in env.registry:
        return
    if "ir.cron" not in env.registry:
        return
    if "res.currency.rate" not in env.registry:
        return

    Action = env["ir.actions.server"]
    Cron = env["ir.cron"]
    action_name = "Currency Rate Sync from ECB"
    cron_name = "Currency Rate Sync from ECB"

    action = Action.search([("name", "=", action_name)], limit=1)
    if not action:
        action = Action.create(
            {
                "name": action_name,
                "model": "res.currency.rate",
                "action_type": "code",
                "code": "env['res.currency.rate'].fetch_from_ecb(env)\n",
            }
        )

    if not Cron.search([("name", "=", cron_name)], limit=1):
        Cron.create(
            {
                "name": cron_name,
                "action_id": action,
                # Daily — ECB publishes once per business day around
                # 16:00 CET. The exact tick doesn't matter; the fetch
                # itself is idempotent per ECB publication date.
                "interval_number": 1,
                "interval_type": "days",
                # Seeded inactive: opt-in keeps fresh installs
                # network-silent.
                "active": False,
            }
        )
