"""super_chain_demo_b: outermost ``_inherit`` extension on ``super_chain.order``."""
NAME: str = "super_chain_demo_b"
VERSION: tuple[int, ...] = (0, 1, 0)
SUMMARY: str = "Super-chain demo — outer extension layer."
CATEGORY: str = "Technical"
AUTHOR: str = "pyvelm"
DEPENDS: list[str] = ["super_chain_demo_a"]
