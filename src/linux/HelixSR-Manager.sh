#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

for f in "$HERE"/helixsr_core/HelixSR-1.8.1/*.sh; do
    [ -f "$f" ] && chmod +x "$f" 2>/dev/null || true
done

PY=""
if command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
elif [ -x "${XDG_DATA_HOME:-$HOME/.local/share}/HelixSR/python/bin/python3" ]; then
    PY="${XDG_DATA_HOME:-$HOME/.local/share}/HelixSR/python/bin/python3"
else
    echo "[HelixSR Manager] Error: python3 not found. Please install python3." >&2
    exit 1
fi

exec "$PY" "$HERE/helixsr_swapper_linux.py" "$@"
