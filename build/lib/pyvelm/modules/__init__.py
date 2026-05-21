"""Poison file: ``pyvelm.modules`` is NOT importable as a package.

This directory ships bundled modules (``base``, ``admin``) inside the
pyvelm wheel, but the loader picks them up through the same sys.path
injection it uses for example addons — they're imported as top-level
``base``, ``admin``, etc.

Without this poison file Python would treat the directory as an
implicit namespace package, letting users ``import pyvelm.modules.base``
and get a SECOND copy of every model class (the loader-discovered
``base.models.X`` and the namespace-imported
``pyvelm.modules.base.models.X``). Two copies of the same model
register separately, and the resulting registry is silently broken.

Reach for the modules via ``pyvelm.BUILTIN_MODULE_ROOTS`` + the
loader instead.
"""

raise ImportError(
    "pyvelm.modules is a module-discovery root, not an importable "
    "package. Use pyvelm.BUILTIN_MODULE_ROOTS with pyvelm.loader."
)
