#!/usr/bin/env bash
# Create an annotated git tag with the CHANGELOG section as the message.
# Usage: ./scripts/tag_release.sh 0.2.9
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="${1:?usage: $0 <version>}"
NOTES="$(mktemp)"
python3 scripts/extract_changelog.py "$VERSION" > "$NOTES"
git -c core.commentChar='!' tag -a "v${VERSION}" -F "$NOTES"
rm -f "$NOTES"
echo "Tagged v${VERSION} (message from CHANGELOG.md)"
