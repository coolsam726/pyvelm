"""super_chain_demo: base model with ``button_cancel`` for super()-chain tests.

Install ``super_chain_demo_a`` and ``super_chain_demo_b`` on top to exercise
stacked ``_inherit`` overrides that call ``super().button_cancel()``.
"""
NAME: str = "super_chain_demo"
VERSION: tuple[int, ...] = (0, 1, 0)
SUMMARY: str = "Super-chain order model — base layer of super() chaining example."
CATEGORY: str = "Technical"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["base"]
INSTALL_HOOK: str = "super_chain_demo.hooks:install"
