"""vellum module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("vellum")
    .version(0, 1, 0)
    .summary("Eloquent-style query builder and recordset helpers (opt-in per model).")
    .category("Technical")
    .author("pyvelm")
    .depends("base")
)
