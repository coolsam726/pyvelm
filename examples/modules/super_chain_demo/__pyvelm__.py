"""super_chain_demo: base model with ``button_cancel`` for super()-chain tests.

Install ``super_chain_demo_a`` and ``super_chain_demo_b`` on top to exercise
stacked ``_inherit`` overrides that call ``super().button_cancel()``.
"""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("super_chain_demo")
    .version(0, 1, 0)
    .summary("Super-chain order model — base layer of super() chaining example.")
    .category("Technical")
    .author("pyvelm")
    .depends("base")
    .install_hook("super_chain_demo.hooks:install")
)
