"""Install / upgrade hooks for the base module.

`install(env)` runs on first install only (after schema setup, before
view sync). Seeds a default Admin group and a superuser with id=1
plus a Public group for unauthenticated access grants.

The mail-dispatcher seed (``_seed_mail_dispatcher``) is factored out
so the 0_8_to_0_9 migration can call it for already-installed
databases that won't re-run ``install()``.
"""


def install(env):
    Group = env["res.groups"]
    User = env["res.users"]

    admin_group = Group.create({"name": "Admin"})
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
            "res.currency",
            "res.currency.rate",
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
    action_name = "ECB rate fetcher"
    cron_name = "ECB rate fetcher"

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
