#!/usr/bin/env bash
# Render the Auth0 split-cover background image (2880x1800 PNG) from the source HTML.
# Output: frontend/public/auth-bg-split.png (served at app.com-compass.com/auth-bg-split.png)
#
# Usage (from repo root):
#   bash infra/auth0/render-bg.sh
#
# Requires: Google Chrome installed at the standard macOS location.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_HTML="$REPO_ROOT/mockup/login/auth-bg-source.html"
OUTPUT_PNG="$REPO_ROOT/frontend/public/auth-bg-split.png"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [[ ! -f "$SOURCE_HTML" ]]; then
  echo "ERROR: source not found: $SOURCE_HTML" >&2
  exit 1
fi

if [[ ! -x "$CHROME" ]]; then
  echo "ERROR: Chrome not found at $CHROME" >&2
  echo "Install Chrome or edit CHROME path in this script." >&2
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT_PNG")"

# Use a temp profile dir so headless doesn't conflict with a running Chrome
TMP_PROFILE="$(mktemp -d)"
trap 'rm -rf "$TMP_PROFILE"' EXIT

echo "Rendering $SOURCE_HTML → $OUTPUT_PNG (2880x1800)..."

"$CHROME" \
  --headless=new \
  --disable-gpu \
  --hide-scrollbars \
  --no-sandbox \
  --user-data-dir="$TMP_PROFILE" \
  --window-size=2880,1800 \
  --virtual-time-budget=5000 \
  --screenshot="$OUTPUT_PNG" \
  "file://$SOURCE_HTML" 2>/dev/null

if [[ ! -f "$OUTPUT_PNG" ]]; then
  echo "ERROR: PNG not generated" >&2
  exit 1
fi

SIZE_KB=$(du -k "$OUTPUT_PNG" | awk '{print $1}')
DIMENSIONS=$(sips -g pixelWidth -g pixelHeight "$OUTPUT_PNG" 2>/dev/null | awk '/pixel(Width|Height):/ {print $2}' | paste -sd 'x' -)

echo ""
echo "✓ Done."
echo "  File:       $OUTPUT_PNG"
echo "  Size:       ${SIZE_KB} KB"
echo "  Dimensions: ${DIMENSIONS}"
echo ""
echo "Next:"
echo "  1. git add frontend/public/auth-bg-split.png && commit + deploy"
echo "  2. Auth0 dashboard → Update branding theme → Page → Background image url ="
echo "     https://app.com-compass.com/auth-bg-split.png"
echo "  3. Page layout → right (3rd option)"
