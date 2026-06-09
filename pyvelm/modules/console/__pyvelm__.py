"""console module manifest."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("console")
    .version(0, 1, 0)
    .summary("Artisan-style CLI commands and generators.")
    .category("System")
    .author("pyvelm")
    .depends("base")
)
