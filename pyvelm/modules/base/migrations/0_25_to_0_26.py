"""Email templates — Admin ACL backfill."""

from pyvelm.security import grant_model_access


def upgrade(env):
    grant_model_access(env, "mail.template", admin="crud", user=None, public=None)
