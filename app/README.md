# HelixSR Manager (Flutter)

Brutalist Flutter edition of HelixSR Manager for Linux and Windows, with two
separate shells: a mouse and keyboard desktop UI and a full controller console UI.

Design tokens, fonts (IBM Plex Mono, Archivo Black, both OFL) and widgets follow
the Dena.emu brutalist kit. The engine in `lib/engine` is a Dart port of `src/Engine.cs`.

## Run and build

    flutter pub get
    flutter run -d linux            # or -d windows
    flutter test                    # engine + widget tests
    flutter build linux --release   # or: flutter build windows --release
    scripts/bundle-core.sh          # copy ../helixsr_core next to the Linux bundle

The core is found via `HELIXSR_CORE`, a `helixsr_core` folder next to the
executable, or the repo's `helixsr_core`. Windows: copy `helixsr_core` beside the exe.

## Modes

`Settings > UI MODE`: AUTO (switches to console on the first controller press),
DESKTOP or CONSOLE. `F11` or `--console` toggles console mode.

Console controls: d-pad/stick move, A select, B back, X sort, Y filter,
LB/RB switch page, hold A to uninstall. Keyboard: arrows, Enter, Esc, X, Y, Q/E.
