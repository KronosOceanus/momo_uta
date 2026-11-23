#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
VARIANT="${1:-base}"
case "$VARIANT" in
  base|thin|full) ;;
  *) echo "usage: $0 base|thin|full" >&2; exit 2 ;;
esac
MOMO_VARIANT="$VARIANT" .venv/bin/pyinstaller --clean --noconfirm \
  --distpath "dist/$VARIANT" --workpath "build/$VARIANT" \
  packaging/momo_uta.spec
