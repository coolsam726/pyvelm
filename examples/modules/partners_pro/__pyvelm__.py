"""partners_pro: a pure view-extension module.

Demonstrates view inheritance by patching the `partners.partner.list`
view: drops `age` (hypothetical privacy concern), adds the partner's
tags after `country_id`, and decorates `active` with a widget hint.

No models — Stage 7's `_inherit` is what'll let modules extend each
other's model classes. Until then, extension modules are limited to
view-only patches and brand-new models of their own.
"""
NAME: str = "partners_pro"
VERSION: tuple[int, ...] = (0, 1, 0)
DEPENDS: list[str] = ["partners"]
DATA: list[str] = [
    "views/partner.py",
]
INSTALL_HOOK: str = "partners_pro.hooks:install"
