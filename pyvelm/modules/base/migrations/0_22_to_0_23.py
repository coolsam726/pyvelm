"""Migration 0.22.0 → 0.23.0 — self-read on ``res.users`` + read ``res.groups``.

Non-admin web sessions need their own ``res.users`` row (shell, profile) and
group names; fresh installs and sync get the same seeds from ``base.hooks``.
"""


def migrate(env):
    from base import hooks

    hooks._seed_res_users_self_read(env)
    hooks._seed_res_groups_read_access(env)
