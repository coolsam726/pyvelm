"""super_chain_demo_a: first ``_inherit`` extension on ``super_chain.order``."""
from pyvelm.manifest import Manifest

manifest = (
    Manifest.make("super_chain_demo_a")
    .version(0, 1, 0)
    .summary("Super-chain demo — middle extension layer.")
    .category("Technical")
    .author("pyvelm")
    .depends("super_chain_demo")
)
