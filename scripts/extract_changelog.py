#!/usr/bin/env python3
"""Extract a version section from CHANGELOG.md for git tags / GitHub releases."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def extract(version: str, changelog: Path | None = None) -> str:
    path = changelog or Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    pattern = (
        rf"(## \[{re.escape(version)}\][^\n]*\n.*?)(?=\n## \[|\Z)"
    )
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        raise SystemExit(f"No CHANGELOG section for version {version!r}")
    return match.group(1).strip()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <version>")
    print(extract(sys.argv[1]))


if __name__ == "__main__":
    main()
