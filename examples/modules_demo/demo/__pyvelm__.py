"""Demo content for the pyvelm example app.

This module ships no Python models — it only seeds data into the
existing partners / crm / base models so the running app has
something interesting to click around in. Lives in a separate
discovery root from the framework example modules so the smoke
test (`basic.py`) doesn't see it; only `serve.py` loads this root.

Reinstall is idempotent — every seed checks for existence first.
Uninstall via the Apps catalog drops the ir_module row but does NOT
roll back the seeded partners / leads, because those records live
on tables owned by other modules.
"""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("demo")
    .version(0, 1, 0)
    .summary("Sample partners, leads, and supporting data for live testing.")
    .category("Demo")
    .author("pyvelm")
    .depends("base", "partners", "partners_pro", "crm")
    .install_hook("demo.hooks:install")
)
