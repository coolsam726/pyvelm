"""ECB rate-fetcher cron seed.

Adds a server action + ir.cron entry that calls
``env["res.currency.rate"].fetch_from_ecb(env)``. The cron is seeded
inactive — operators flip ``active=True`` in Settings → Scheduled
Actions when they want daily refreshes.

Implementation lives in ``hooks._seed_rate_fetcher`` so a fresh
install (which doesn't run this migration) calls the same code from
the install hook.

Idempotent: both rows are looked up by name before creating.
"""


def migrate(env):
    from base import hooks

    hooks._seed_rate_fetcher(env)
