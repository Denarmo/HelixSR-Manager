#!/usr/bin/env bash
set -euo pipefail

export PATH="$PATH:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:/var/lib/flatpak/exports/bin:$HOME/.local/share/flatpak/exports/bin"

# Strip Steam overlay / pressure-vessel preload & library paths so standalone GUI and system tools run cleanly
unset LD_PRELOAD 2>/dev/null || true
if [ -n "${SYSTEM_LD_LIBRARY_PATH:-}" ]; then
    export LD_LIBRARY_PATH="$SYSTEM_LD_LIBRARY_PATH"
elif [ -n "${LD_LIBRARY_PATH:-}" ]; then
    CLEAN_LD=""
    IFS=':' read -ra LD_PARTS <<< "$LD_LIBRARY_PATH"
    for p in "${LD_PARTS[@]}"; do
        case "${p,,}" in
            *steam*|*pressure-vessel*|*sniper*|*soldier*|*scout*) ;;
            "") ;;
            *) CLEAN_LD="${CLEAN_LD:+$CLEAN_LD:}$p" ;;
        esac
    done
    if [ -n "$CLEAN_LD" ]; then
        export LD_LIBRARY_PATH="$CLEAN_LD"
    else
        unset LD_LIBRARY_PATH 2>/dev/null || true
    fi
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/HelixSR"
mkdir -p "$DATA_DIR" 2>/dev/null || true
printf '%s\n' "$HERE" > "$DATA_DIR/app_dir.txt" 2>/dev/null || true

chmod +x "$HERE/HelixSR-Manager.sh" "$HERE/HelixSR-Manager.desktop" "$HERE/helixsr_swapper_linux.py" 2>/dev/null || true

for f in "$HERE"/helixsr_core/HelixSR-*/*.sh "$HERE"/helixsr_core/HelixSR-*/setup/lib/model/launch_synth; do
    [ -f "$f" ] && chmod +x "$f" 2>/dev/null || true
done

PY_URL='https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.12.15%2B20261003-x86_64-unknown-linux-gnu-install_only.tar.gz'
PY_SHA='f937814031eab4698ca6d07ec606ede1825768f3f3e99af76d9db3900bee03c5'

show_error() {
    local msg="$1"
    echo "[HelixSR Manager] Error: $msg" >&2
    if command -v kdialog >/dev/null 2>&1; then
        kdialog --title "HelixSR Manager" --error "$msg" >/dev/null 2>&1 || true
    elif command -v zenity >/dev/null 2>&1; then
        zenity --error --title="HelixSR Manager" --text="$msg" >/dev/null 2>&1 || true
    fi
}

show_info_passive() {
    local msg="$1"
    echo "[HelixSR Manager] $msg"
    if command -v kdialog >/dev/null 2>&1; then
        kdialog --title "HelixSR Manager" --passivepopup "$msg" 8 >/dev/null 2>&1 &
    elif command -v notify-send >/dev/null 2>&1; then
        notify-send "HelixSR Manager" "$msg" >/dev/null 2>&1 || true
    fi
}

# For --list CLI mode, any python3 is sufficient
if [[ " $* " == *" --list "* ]]; then
    if [ -x "$DATA_DIR/python/bin/python3" ]; then
        exec "$DATA_DIR/python/bin/python3" "$HERE/helixsr_swapper_linux.py" "$@"
    elif command -v python3 >/dev/null 2>&1; then
        exec python3 "$HERE/helixsr_swapper_linux.py" "$@"
    fi
fi

has_tk() {
    local py="$1"
    [ -x "$py" ] || return 1
    local pdir
    pdir="$(cd "$(dirname "$py")/.." && pwd)"
    if [ -d "$pdir/lib/tcl9.0" ] && [ -d "$pdir/lib/tk9.0" ]; then
        LD_LIBRARY_PATH="$pdir/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
        TCL_LIBRARY="$pdir/lib/tcl9.0" \
        TK_LIBRARY="$pdir/lib/tk9.0" \
        "$py" -c "import tkinter" >/dev/null 2>&1
    else
        "$py" -c "import tkinter" >/dev/null 2>&1
    fi
}

PY=""
if has_tk "$DATA_DIR/python/bin/python3"; then
    PY="$DATA_DIR/python/bin/python3"
elif command -v python3 >/dev/null 2>&1 && has_tk "$(command -v python3)"; then
    PY="$(command -v python3)"
elif has_tk "/usr/bin/python3"; then
    PY="/usr/bin/python3"
fi

# On SteamOS / immutable distros where system python3 lacks tkinter, bootstrap portable Python + Tk 9.0
if [ -z "$PY" ]; then
    LOCK_FILE="$DATA_DIR/runtime_setup.lock"
    exec 9>"$LOCK_FILE"
    if command -v flock >/dev/null 2>&1; then
        flock 9
    fi

    if has_tk "$DATA_DIR/python/bin/python3"; then
        PY="$DATA_DIR/python/bin/python3"
    else
        show_info_passive "Preparing standalone GUI runtime in $DATA_DIR/python (one-time download, ~67 MB)..."
        TMP_TAR="$DATA_DIR/python.tar.gz.$$"
        rm -f "$TMP_TAR"
        DL_OK=0
        if command -v curl >/dev/null 2>&1; then
            curl -fL --retry 3 -o "$TMP_TAR" "$PY_URL" && DL_OK=1
        elif command -v wget >/dev/null 2>&1; then
            wget -q -O "$TMP_TAR" "$PY_URL" && DL_OK=1
        fi
        if [ "$DL_OK" = 1 ] && [ -f "$TMP_TAR" ]; then
            if echo "$PY_SHA  $TMP_TAR" | sha256sum -c --status 2>/dev/null; then
                rm -rf "$DATA_DIR/python"
                tar -C "$DATA_DIR" -xzf "$TMP_TAR" && rm -f "$TMP_TAR"
            else
                rm -f "$TMP_TAR"
                show_error "Standalone runtime download checksum mismatch. Please check your internet connection and try again."
                exit 1
            fi
        else
            rm -f "$TMP_TAR"
            show_error "Could not download the standalone GUI runtime (needs internet connection on first launch on SteamOS, or install python3-tk)."
            exit 1
        fi

        if has_tk "$DATA_DIR/python/bin/python3"; then
            PY="$DATA_DIR/python/bin/python3"
        else
            show_error "Standalone GUI runtime failed to initialize tkinter."
            exit 1
        fi
    fi
    exec 9>&-
fi

PY_ROOT="$(cd "$(dirname "$PY")/.." && pwd)"
if [ -d "$PY_ROOT/lib/tcl9.0" ] && [ -d "$PY_ROOT/lib/tk9.0" ]; then
    export TCL_LIBRARY="$PY_ROOT/lib/tcl9.0"
    export TK_LIBRARY="$PY_ROOT/lib/tk9.0"
    export LD_LIBRARY_PATH="$PY_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

exec "$PY" "$HERE/helixsr_swapper_linux.py" "$@"
