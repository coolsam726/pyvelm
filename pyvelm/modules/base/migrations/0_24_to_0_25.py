"""Classify UI-chrome attachments as public."""

from base import hooks


def upgrade(env):
    hooks.classify_chrome_attachments_public(env)
