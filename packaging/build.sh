#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

VARIANT="${1:-thin}"
case "$VARIANT" in
  thin|full) ;;
  *) echo "usage: $0 thin|full" >&2; exit 2 ;;
esac

NAME="momo-uta-$VARIANT"
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -n 1)
MOMO_VARIANT="$VARIANT" .venv/bin/pyinstaller --clean --noconfirm \
  --distpath "dist/$VARIANT" --workpath "build/$VARIANT" \
  packaging/momo_uta.spec

APP="dist/$VARIANT/$NAME.app"
IDENTITY="${MOMO_CODESIGN_IDENTITY:-}"
if [ -n "$IDENTITY" ]; then
  codesign --force --deep --options runtime --timestamp --sign "$IDENTITY" "$APP"
else
  codesign --force --deep --sign - "$APP"
fi
ZIP="dist/$NAME.zip"
rm -f "$ZIP"
if command -v ditto >/dev/null 2>&1; then
  ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
else
  (cd "dist/$VARIANT" && zip -qry "../$NAME.zip" "$NAME.app")
fi

{
  echo "momo uta — 打包版本"
  echo "version: ${VERSION:-unknown}"
  echo "commit: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "date: $(date '+%Y-%m-%d %H:%M:%S')"
  echo
  for v in thin full; do
    z="dist/momo-uta-$v.zip"
    if [ -f "$z" ]; then
      sum=$(shasum -a 256 "$z" | awk '{print $1}')
      echo "$v  $z  sha256=$sum"
    fi
  done
} > dist/VERSIONS.txt
if [ -n "${MOMO_NOTARY_PROFILE:-}" ]; then
  xcrun notarytool submit "$ZIP" --keychain-profile "$MOMO_NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP"
fi
echo "built $APP"
echo "built $ZIP"
