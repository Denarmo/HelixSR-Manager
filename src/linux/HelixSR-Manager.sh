#!/usr/bin/env bash
set -euo pipefail

export PATH="$PATH:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:/var/lib/flatpak/exports/bin:$HOME/.local/share/flatpak/exports/bin"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/HelixSR"
mkdir -p "$DATA_DIR" 2>/dev/null || true
printf '%s\n' "$HERE" > "$DATA_DIR/app_dir.txt" 2>/dev/null || true

chmod +x "$HERE/HelixSR-Manager.sh" "$HERE/HelixSR-Manager.desktop" "$HERE/helixsr_swapper_linux.py" 2>/dev/null || true

for f in "$HERE"/helixsr_core/HelixSR-*/*.sh "$HERE"/helixsr_core/HelixSR-*/setup/lib/model/launch_synth; do
    [ -f "$f" ] && chmod +x "$f" 2>/dev/null || true
done

PY=""
if command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
elif [ -x "/usr/bin/python3" ]; then
    PY="/usr/bin/python3"
elif [ -x "$DATA_DIR/python/bin/python3" ]; then
    PY="$DATA_DIR/python/bin/python3"
else
    MSG="[HelixSR Manager] Error: python3 not found. Please install python3."
    echo "$MSG" >&2
    if command -v kdialog >/dev/null 2>&1; then
        kdialog --title "HelixSR Manager" --error "$MSG" >/dev/null 2>&1 || true
    elif command -v zenity >/dev/null 2>&1; then
        zenity --error --title="HelixSR Manager" --text="$MSG" >/dev/null 2>&1 || true
    fi
    exit 1
fi

exec "$PY" "$HERE/helixsr_swapper_linux.py" "$@"
