#!/usr/bin/env bash
# Create or update a GitHub Release with the CHANGELOG section as the body.
# Requires: gh auth login, tag already pushed to origin.
# Usage: ./scripts/github_release.sh 0.2.9
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="${1:?usage: $0 <version>}"
NOTES="$(mktemp)"
python3 scripts/extract_changelog.py "$VERSION" > "$NOTES"
if gh release view "v${VERSION}" >/dev/null 2>&1; then
  gh release edit "v${VERSION}" --notes-file "$NOTES"
  echo "Updated GitHub release v${VERSION}"
else
  gh release create "v${VERSION}" --notes-file "$NOTES"
  echo "Created GitHub release v${VERSION}"
fi
rm -f "$NOTES"
