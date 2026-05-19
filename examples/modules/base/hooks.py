"""Install / upgrade hooks for the base module.

`install(env)` runs on first install only (after schema setup, before
view sync). Seeds a default Admin group and a superuser with id=1
plus a Public group for unauthenticated access grants.
"""


def install(env):
    Group = env["res.groups"]
    User = env["res.users"]

    admin_group = Group.create({"name": "Admin"})
    Group.create({"name": "Public"})

    # The superuser is hard-coded to uid=1 — that's what
    # `Environment.is_superuser()` checks. Postgres SERIAL hands out
    # 1 to the first INSERT, and we INSERT this user before any other
    # in the install lifecycle, so the convention holds.
    User.create({
        "name": "Administrator",
        "login": "admin",
        "password": "admin",   # bcrypt-hashed by the Password field
        "group_ids": [admin_group],
    })
