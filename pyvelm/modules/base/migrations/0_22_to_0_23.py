"""Self-read on res.users + read res.groups."""

from base import hooks


def upgrade(env):
    hooks._seed_res_users_self_read(env)
    hooks._seed_res_groups_read_access(env)
