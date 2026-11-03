#!/usr/bin/env bash
# Builds the Decky plugin zip: out/helixsr-manager-decky-<version>.zip
#   bash scripts/package.sh            # frontend build + zip with the HelixSR core bundled
#   bash scripts/package.sh --no-core  # small zip; the plugin then uses an installed HelixSR Manager's core
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
WITH_CORE=1
[ "${1:-}" = "--no-core" ] && WITH_CORE=0

cd "$HERE"
VERSION="$(python3 -c 'import json;print(json.load(open("package.json"))["version"])')"
NAME="helixsr-manager"
OUT="$HERE/out"
STAGE="$OUT/$NAME"

[ -d node_modules ] || npm ci
npm run --silent build

rm -rf "$STAGE"
mkdir -p "$STAGE/dist" "$STAGE/py_modules"
cp dist/index.js "$STAGE/dist/"
cp main.py plugin.json package.json README.md "$STAGE/"
cp "$REPO/LICENSE" "$STAGE/LICENSE"
cp py_modules/helixsr_bridge.py "$STAGE/py_modules/"
# The Manager's Linux engine, used as a library (one source of truth with the desktop app).
cp "$REPO/src/linux/helixsr_swapper_linux.py" "$STAGE/py_modules/helixsr_engine.py"

if [ "$WITH_CORE" = 1 ]; then
    mkdir -p "$STAGE/helixsr_core"
    for core in "$REPO"/helixsr_core/HelixSR-*; do
        dest="$STAGE/helixsr_core/$(basename "$core")"
        cp -r "$core" "$dest"
        # Never ship a locally compiled network (NVIDIA license / HelixSR license section 4).
        find "$dest" \( -name helixsr_weights.bin -o -name helixsr_kernels.pak -o -name helixsr_setup.json \
            -o -name manual-install -o -name fsr3-drop-in -o -name __pycache__ \) -prune -exec rm -rf {} +
        python3 - "$dest/amd_fidelityfx_dx12.dll" <<'PY'
import sys
data = open(sys.argv[1], "rb").read()
if b"HXSRNET1" in data[-64:]:
    sys.exit("refusing to package: the core DLL has a compiled network embedded")
PY
    done
fi

ZIP="$OUT/$NAME-decky-$VERSION.zip"
rm -f "$ZIP"
python3 - "$OUT" "$NAME" "$ZIP" <<'PY'
import os, sys, zipfile
out, name, dest = sys.argv[1:4]
with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for root, dirs, files in os.walk(os.path.join(out, name)):
        dirs.sort()
        rel = os.path.relpath(root, out)
        z.write(root, rel + "/")
        for f in sorted(files):
            z.write(os.path.join(root, f), os.path.join(rel, f))
PY
echo "Built $ZIP ($(du -h "$ZIP" | cut -f1))"
