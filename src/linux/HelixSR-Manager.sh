#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [ -f "$HERE/helixsr_core/HelixSR-1.7.0/helixsr-setup.sh" ]; then
    chmod +x "$HERE/helixsr_core/HelixSR-1.7.0/helixsr-setup.sh" 2>/dev/null || true
fi

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
