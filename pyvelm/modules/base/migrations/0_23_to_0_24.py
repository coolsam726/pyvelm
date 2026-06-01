"""User group and membership backfill."""

from base import hooks
from pyvelm.security import assign_user_group_to_active_users, ensure_user_group


def upgrade(env):
    if "res.groups" in env.registry:
        ensure_user_group(env)
    assign_user_group_to_active_users(env)
    hooks._seed_res_users_self_read(env)
    hooks._seed_res_groups_read_access(env)
