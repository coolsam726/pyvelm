"""ECB rate-fetcher cron seed."""

from base import hooks


def upgrade(env):
    hooks._seed_rate_fetcher(env)
