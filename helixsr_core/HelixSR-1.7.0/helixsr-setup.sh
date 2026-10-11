#!/usr/bin/env bash
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
#
# HelixSR setup for Linux, the only thing to run:
#   1. the first time (or with --rebuild): builds HelixSR's network (helixsr_weights.bin, helixsr_kernels.pak) from NVIDIA's DLSS 310.7.0 DLL
#      (downloaded from NVIDIA's GitHub after you agree, or --dlss <file>);
#   2. lists your DLSS games and installs HelixSR + OptiScaler into the ones you pick, or removes them again.
#
#   ./helixsr-setup.sh [GAME_FOLDER].. [--dlss nvngx_dlss.dll] [--rebuild] [--yes]
#
# A GAME_FOLDER adds a game the setup does not find by itself. Needs Python 3 with numpy: the script uses the system's,
# installs them with your distro's package manager (asks first), or downloads a portable Python into
# ~/.local/share/HelixSR (read-only systems such as SteamOS, or if you say no). Shaders are compiled with Microsoft's
# DirectX Shader Compiler (downloaded once from Microsoft's GitHub) through Proton/Wine, which every Linux setup that
# runs HelixSR already has.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PKG="$HERE/setup"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/HelixSR"
PY_URL='https://github.com/astral-sh/python-build-standalone/releases/download/20261003/cpython-3.12.15%2B20261003-x86_64-unknown-linux-gnu-install_only.tar.gz'
PY_SHA='f937814031eab4698ca6d07ec606ede1825768f3f3e99af76d9db3900bee03c5'
DXCWIN_URL='https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2607/dxc_2026_07_29.zip'
DXCWIN_SHA='a1dfb116ba3eeae6a1582291b53a8e7bf65ad760676bd3194685c8f7367cd241'

say() { printf '[helixsr-setup] %s\n' "$*"; }
die() { printf '[helixsr-setup] error: %s\n' "$*" >&2; exit 1; }
ask() {   # ask "question" -> 0 for yes (default yes); --yes answers yes
    [ "$ASSUME_YES" = 1 ] && return 0
    local r; read -r -p "$1 [Y/n] " r || r=n
    case "$r" in ''|y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}
fetch() {   # fetch URL FILE SHA256
    say "downloading $(basename "$2")"
    if command -v curl >/dev/null; then curl -fL --retry 3 -o "$2" "$1"
    elif command -v wget >/dev/null; then wget -q -O "$2" "$1"
    else die "needs curl or wget"; fi
    echo "$3  $2" | sha256sum -c --status || { rm -f "$2"; die "$(basename "$2"): checksum mismatch"; }
}

# --- arguments ---
TARGET="$HERE"; ASSUME_YES=0; PASS=(); INST=(); REBUILD=0
while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y) ASSUME_YES=1; PASS+=(--yes) ;;
        --dlss) PASS+=(--dlss "$(realpath "$2")"); shift ;;
        --rebuild) REBUILD=1 ;;
        --wave64) PASS+=(--wave64); REBUILD=1 ;;   # also the RDNA 3+ shaders (only built for such a GPU otherwise)
        -h|--help) sed -n '3,14p' "$0"; exit 0 ;;
        *) [ -d "$1" ] || die "not a folder: $1"; INST+=(--folder "$(realpath "$1")") ;;
    esac
    shift
done
[ "$(uname -m)" = x86_64 ] || die "x86-64 Linux only"
[ -d "$TARGET" ] || die "not a folder: $TARGET"
mkdir -p "$DATA"

# --- distro ---
ID=unknown; ID_LIKE=""
[ -r /etc/os-release ] && . /etc/os-release
FAMILY=unknown
case " $ID $ID_LIKE " in
    *" arch "*|*" cachyos "*|*" manjaro "*|*" endeavouros "*) FAMILY=arch ;;
    *" debian "*|*" ubuntu "*) FAMILY=debian ;;
    *" fedora "*|*" rhel "*|*" centos "*) FAMILY=fedora ;;
    *" suse "*|*" opensuse "*) FAMILY=suse ;;
esac
IMMUTABLE=0   # SteamOS and ostree systems (Bazzite, Silverblue, Kinoite): no package installs
{ [ "$ID" = steamos ] || [ -e /run/ostree-booted ]; } && IMMUTABLE=1
say "system: ${PRETTY_NAME:-$ID} (family: $FAMILY$([ $IMMUTABLE = 1 ] && echo ', read-only system'))"

# --- Python 3 with numpy ---
has_numpy() { "$1" -c 'import numpy, sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; }
PY=""
# (HELIXSR_FORCE_PORTABLE=1: test switch for the portable-Python path)
[ "${HELIXSR_FORCE_PORTABLE:-0}" = 1 ] && CANDIDATES=("$DATA/python/bin/python3") || CANDIDATES=("$DATA/python/bin/python3" python3)
for c in "${CANDIDATES[@]}"; do
    if command -v "$c" >/dev/null 2>&1 && has_numpy "$c"; then PY=$(command -v "$c"); break; fi
done
if [ -z "$PY" ] && [ "${HELIXSR_FORCE_PORTABLE:-0}" != 1 ] && [ $IMMUTABLE = 0 ] && [ $FAMILY != unknown ] && command -v sudo >/dev/null; then
    case $FAMILY in
        arch)   CMD="sudo pacman -S --needed --noconfirm python python-numpy" ;;
        debian) CMD="sudo apt-get install -y python3 python3-numpy" ;;
        fedora) CMD="sudo dnf install -y python3 python3-numpy" ;;
        suse)   CMD="sudo zypper --non-interactive install python3 python3-numpy" ;;
    esac
    if ask "Install Python 3 + numpy with your package manager ($CMD)?"; then
        if $CMD && has_numpy python3; then PY=$(command -v python3); fi
    fi
fi
if [ -z "$PY" ]; then
    say "using a portable Python in $DATA/python (one-time download, ~67 MB)"
    if [ ! -x "$DATA/python/bin/python3" ]; then
        fetch "$PY_URL" "$DATA/python.tar.gz" "$PY_SHA"
        tar -C "$DATA" -xzf "$DATA/python.tar.gz" && rm -f "$DATA/python.tar.gz"
    fi
    "$DATA/python/bin/python3" -m pip install --quiet --disable-pip-version-check numpy || die "numpy install failed"
    PY="$DATA/python/bin/python3"
fi
say "python: $PY"

# --- network: built into nvngx.dll once ---
if [ "$REBUILD" = 0 ] && [ -s "$TARGET/helixsr_weights.bin" ] && [ -s "$TARGET/helixsr_kernels.pak" ]; then
    say "the network is already built (--rebuild builds it again)"
else
# --- shader compiler: Microsoft's DXC (Windows build) through Proton/Wine ---
WINE=""
# official Proton first, then custom Proton builds, then a system Wine
for p in "$HOME"/.local/share/Steam/steamapps/common/Proton*/files/bin/wine \
         "$HOME"/.steam/steam/steamapps/common/Proton*/files/bin/wine \
         "$HOME"/.local/share/Steam/compatibilitytools.d/*/files/bin/wine \
         "$HOME"/.steam/root/compatibilitytools.d/*/files/bin/wine; do
    if [ -x "$p" ]; then WINE="$p"; break; fi
done
[ -z "$WINE" ] && command -v wine >/dev/null && WINE=$(command -v wine)
[ -n "$WINE" ] || die "no Proton or Wine found (needed to run the shader compiler); install Proton in Steam or Wine"
if [ ! -f "$DATA/dxc-win/bin/x64/dxc.exe" ]; then
    fetch "$DXCWIN_URL" "$DATA/dxc-win.zip" "$DXCWIN_SHA"
    # (the zip stores Windows paths: bin\x64\dxc.exe)
    "$PY" -c 'import os, sys, zipfile
z = zipfile.ZipFile(sys.argv[1]); n_out = 0
for n in z.namelist():
    t = n.replace(chr(92), "/")
    if t.startswith("bin/x64/") and not t.endswith("/"):
        p = os.path.join(sys.argv[2], t); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(z.read(n)); n_out += 1
sys.exit(0 if n_out else 1)' "$DATA/dxc-win.zip" "$DATA/dxc-win" || die "could not unpack the shader compiler"
    rm -f "$DATA/dxc-win.zip"
fi
DXC="$DATA/dxc-wine.sh"
cat > "$DXC" <<EOF
#!/usr/bin/env bash
# DXC through Wine: absolute Linux paths become Z:\\ paths
args=()
for a in "\$@"; do case "\$a" in /*) args+=("Z:\$(printf '%s' "\$a" | tr / '\\\\')") ;; *) args+=("\$a") ;; esac; done
WINEPREFIX="$DATA/wineprefix" WINEDEBUG=-all exec "$WINE" "$DATA/dxc-win/bin/x64/dxc.exe" "\${args[@]}"
EOF
chmod +x "$DXC"
say "shader compiler: Windows DXC through $(dirname "$(dirname "$(dirname "$WINE")")")"

# --- build ---
"$PY" "$PKG/helixsr_setup.py" "$TARGET" --dxc "$DXC" "${PASS[@]}"
rm -rf "$DATA/wineprefix"   # the Wine compiler's temporary prefix (only created on older distros)
fi

# --- games ---
exec "$PY" "$PKG/helixsr_install.py" "$TARGET" "${INST[@]}"
