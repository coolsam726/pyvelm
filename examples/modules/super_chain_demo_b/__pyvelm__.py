"""super_chain_demo_b: outermost ``_inherit`` extension on ``super_chain.order``."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("super_chain_demo_b")
    .version(0, 1, 0)
    .summary("Super-chain demo — outer extension layer.")
    .category("Technical")
    .author("pyvelm")
    .depends("super_chain_demo_a")
)
