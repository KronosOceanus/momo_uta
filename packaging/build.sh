#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

VARIANT="${1:-thin}"
case "$VARIANT" in
  thin|full) ;;
  *) echo "usage: $0 thin|full" >&2; exit 2 ;;
esac

NAME="momo-uta-$VARIANT"
MOMO_VARIANT="$VARIANT" .venv/bin/pyinstaller --clean --noconfirm \
  --distpath "dist/$VARIANT" --workpath "build/$VARIANT" \
  packaging/momo_uta.spec

APP="dist/$VARIANT/$NAME.app"
ZIP="dist/$NAME.zip"
rm -f "$ZIP"
if command -v ditto >/dev/null 2>&1; then
  ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
else
  (cd "dist/$VARIANT" && zip -qry "../$NAME.zip" "$NAME.app")
fi

{
  echo "momo uta — 打包版本"
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
echo "built $APP"
echo "built $ZIP"
