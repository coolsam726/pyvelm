NAME: str = "base"
VERSION: tuple[int, ...] = (0, 3, 0)
DEPENDS: list[str] = []

# Seed default Admin group + uid=1 superuser on first install so the
# loader has a sane authenticated identity to run as. See
# base/hooks.py.
INSTALL_HOOK: str = "base.hooks:install"
