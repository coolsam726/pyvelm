#!/usr/bin/env bash
# Bump version across pyproject.toml, __init__.py, CHANGELOG, and docs.
# Usage: ./scripts/bump_version.sh 1.4.0 [--date YYYY-MM-DD]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/bump_version.py" "$@"
