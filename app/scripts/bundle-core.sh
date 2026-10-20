#!/usr/bin/env bash
# Copies the HelixSR core next to a built Flutter bundle so the app finds it
# without HELIXSR_CORE. Usage: scripts/bundle-core.sh [bundle-dir]
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
bundle="${1:-$here/build/linux/x64/release/bundle}"
core="$here/../helixsr_core"
[ -d "$core" ] || { echo "helixsr_core not found at $core" >&2; exit 1; }
rm -rf "$bundle/helixsr_core"
cp -r "$core" "$bundle/helixsr_core"
echo "core bundled into $bundle/helixsr_core"
