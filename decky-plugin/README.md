# HelixSR Manager for Decky

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that brings HelixSR Manager into SteamOS Game Mode (Steam Deck, Legion Go S, ROG Ally on SteamOS or Bazzite). Open the Quick Access Menu (the `...` button), pick the HelixSR tab, and install, switch or remove HelixSR per game without going to Desktop Mode.

## What it does

- Picks the game you are playing (or any supported game in your library) and shows whether HelixSR is installed, with which method and version.
- Installs HelixSR with the same options as the desktop app: OptiScaler (proxy DLL choice, frame generation mode, FakeNVAPI), Direct FSR 3.1 replacement, the experimental DLSS Loader, and REFramework Nightly for RE Engine games.
- **FSR 4 model picker** (OptiScaler route): full FSR 4 or **FSR 4 Lite**, the lighter INT8 model for handheld APUs. The picker appears once the HelixSR engine in your build supports it, and defaults to Lite.
- Sets the game's Steam launch options (`WINEDLLOVERRIDES="dxgi=n,b" %command%` and friends) for you on install, switches them when you change the proxy DLL, and takes them out again on uninstall. Anything else you have in the launch options is left alone. You can turn this off in the plugin's settings.
- Builds the HelixSR network on the device (same compiler as the desktop app), clears shader caches and rescans the library.

Everything is done by the HelixSR Manager Linux engine (`src/linux/helixsr_swapper_linux.py`), which the plugin ships as a library, so the plugin and the desktop app install files the same way and see each other's installs.

## Which HelixSR core it uses

The plugin uses the first of these that has a built network, else the first one it can write to:

1. `corePath` in the plugin's `settings.json`, or `$HELIXSR_CORE`
2. the core of an installed HelixSR Manager (Python edition, found through `~/.local/share/HelixSR/app_dir.txt`)
3. `~/.local/share/HelixSR/core/HelixSR-<version>` (the copy the Flutter app makes)
4. the core bundled in the plugin, copied to (3) so the network can be built into it

So if you already built the network in HelixSR Manager, the plugin uses it straight away. If not, press **Build network** in the plugin.

## Install on the handheld

You need Decky Loader installed (see its README). Then use one of these:

**A. From the zip in Game Mode (no terminal)**

1. Get `helixsr-manager-decky-<version>.zip` onto the handheld, for example in `~/Downloads` (Desktop Mode browser download, a USB stick or a network share).
2. Quick Access Menu > Decky (plug icon) > gear icon > **General** > turn on **Developer mode**.
3. Decky settings > **Developer** > **Install Plugin from ZIP File** > browse to the zip > Install.

**B. From a URL in Game Mode**

Decky settings > **Developer** > **Install Plugin from URL**, and enter the zip's download link (for example a GitHub release asset).

**C. From Desktop Mode or SSH**

```bash
sudo rm -rf ~/homebrew/plugins/helixsr-manager
sudo python3 -m zipfile -e helixsr-manager-decky-1.0.0.zip ~/homebrew/plugins/
sudo systemctl restart plugin_loader
```

The plugin runs as your user (no root), so the files it puts into your games belong to you, the same as with the desktop app.

## Using it

1. Start the game once without HelixSR so its config files exist, then open the Quick Access Menu > HelixSR.
2. If **Engine** says *Network not built*, press **Build network** (several minutes, keep the device plugged in).
3. Under **Game**, the running game is picked for you. Choose the method and options, then **Install HelixSR**.
4. Restart the game. In OptiScaler games, press Insert (or the OptiScaler overlay key you set) to check that HelixSR is the active upscaler.

## Building

```bash
cd decky-plugin
npm ci
npm run typecheck && npm test          # TypeScript + launch-option merge tests
python3 -m unittest discover -s tests  # backend bridge tests against a fake Steam library
bash scripts/package.sh                # out/helixsr-manager-decky-<version>.zip (core bundled)
bash scripts/package.sh --no-core      # small zip that relies on an installed HelixSR Manager core
```

The package script copies the engine from `src/linux/` and the core from `helixsr_core/`, and refuses to package a core DLL with a compiled network in it (those must never be redistributed).

## Layout

| Path | What |
|---|---|
| `plugin.json`, `package.json` | Decky metadata |
| `src/index.tsx` | Quick Access Menu UI (`@decky/ui`) |
| `src/launchOptions.ts` | Merges HelixSR's `WINEDLLOVERRIDES` into existing launch options |
| `main.py` | Decky backend; runs the bridge with the system `python3` |
| `py_modules/helixsr_bridge.py` | JSON bridge to the Manager engine (core lookup, scan cache, install, build) |
| `scripts/package.sh` | Builds the installable zip |
