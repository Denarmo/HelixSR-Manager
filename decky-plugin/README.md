# HelixSR Manager for Decky

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that brings HelixSR Manager into SteamOS Game Mode (Steam Deck, Legion Go S, ROG Ally on SteamOS or Bazzite). Open the Quick Access Menu (the `...` button), pick the HelixSR tab, and install, switch or remove HelixSR per game without going to Desktop Mode.

## What it does

- Picks the game you are playing (or any supported game in your library) and shows whether HelixSR is installed, with which method and version.
- Installs HelixSR with the same options as the desktop app: OptiScaler (proxy DLL choice, frame generation mode, FakeNVAPI), Direct FSR 3.1 replacement, the experimental DLSS Loader, and REFramework Nightly for RE Engine games.
- **FSR 4 Lite (AMD 4.1.2 INT8)** per game: AMD's driver FSR 4.1.2 with the small INT8 Lite model, through OptiScaler 10. It is the default method on AMD handhelds (Steam Deck, Legion Go S and others) for games where it can go in. See [FSR 4 Lite](#fsr-4-lite) below.
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

Decky settings > **Developer** > **Install Plugin from URL**, and enter:

```
https://github.com/Denarmo/HelixSR-Manager/releases/download/decky-v1.0.0/helixsr-manager-decky.zip
```

The `Decky plugin` GitHub workflow builds the zip and publishes it as the `decky-v<version>` release whenever the plugin, the Linux engine or the core changes on `main`.

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

## FSR 4 Lite

FSR 4 Lite runs AMD's FSR 4.1.2 upscaler with its INT8 Lite model (the one AMD made for APUs) in Proton games. OptiScaler intercepts the game's own temporal upscaler (DLSS, XeSS or FSR 2/3), which gives it the colour, depth, motion vectors and jitter of every frame, and hands them to AMD's driver FSR 4 provider. That is why the game needs an upscaler of its own: a finished frame (for example a Gamescope screenshot) does not carry those inputs.

### Using it

1. Pick the game, set **Method** to **FSR 4 Lite (AMD 4.1.2 INT8, OptiScaler 10)** (preselected on AMD handhelds when the game qualifies).
2. The first time, press **Download runtime** (108 MB, once). It fetches the pinned payload described below and checks every file by SHA-256 and the two AMD providers for the 4.1.2 version and the INT8 Lite model.
3. Press **Enable FSR 4 Lite**. The plugin copies OptiScaler and the providers next to the game's .exe and adds `WINEDLLOVERRIDES="dxgi=n,b"` (or the proxy it picked) to the launch options.
4. Start the game, turn on its DLSS, XeSS or FSR in the graphics settings, play a few seconds, then quit or open the Quick Access Menu and press **Check what ran**.

The status only says **Active** once the game's `OptiScaler.log`, from a launch after the install, shows all three: the 4.1.2 driver provider loaded, INT8 Lite as the model the driver accepted, and upscaler dispatches without errors. It then shows the render and display resolution (for example `1280x720 → 2560x1440`). Until then it says *Enabled, not verified* and names what is missing. The first launch logs at Debug level (that is where OptiScaler prints the per-model result and each dispatch); after a verified run the plugin turns it down to Info.

**Use fallback (FSR 2.2)** switches the game to OptiScaler's built-in FSR 2.2: same game inputs, no AMD DLL and no FSR 4 support needed, so it works if the driver path does not. Turn it off to go back to Lite. **Disable FSR 4 Lite (restore)** removes every file the plugin placed and puts the launch options back: exactly as they were if you did not edit them since, otherwise only the override the plugin added is taken out (one you already had stays).

The plugin never overwrites a file it did not place. If another mod uses `dxgi.dll` (ReShade, for example) it takes the next free proxy name; if another OptiScaler is installed in the game, or HelixSR is (both use OptiScaler), it asks you to remove that first. Games with anti-cheat (Easy Anti-Cheat, BattlEye and similar) are refused.

### What is pinned

| Piece | Version | Check |
|---|---|---|
| OptiScaler | 10.0.0-pre1, reports `10.0.0-dev (10911bcb)`, built from [optiscaler/OptiScaler@b686ef4](https://github.com/optiscaler/OptiScaler/tree/b686ef4bc1e755185685b47a2da2d8095f5467ce) ("4.1.2 model selection") | SHA-256 |
| `amdxcffx64.dll` (DX12, also DX11 through DX11on12) | AMD-signed, 2.4.0.4370, providers 4.0.0 / 4.0.2 / **4.1.2**, has `ffxProvider_FSR4Lite_Int8` | SHA-256 + strings |
| `amdvkffx64.dll` (Vulkan games) | AMD-signed, 2.4.0.4370, providers 4.0.0 / 4.0.2 / **4.1.2**, has `ffxProvider_FSR4Lite_Int8` | SHA-256 + strings |
| Source of the files | [Decky OptiScaler v0.0.9](https://github.com/n1ckmp3/decky-optiscaler/releases/tag/v0.0.9) release zip | SHA-256 of the zip and of the inner 7z |

Settings written to `OptiScaler.ini`, checked against `OptiScaler/OptiTypes.h` at that commit (`FSR4Support::INT8Lite = 4`, `FSR4Model::INT8Lite = 3`):

```ini
[Upscalers]
Dx12Upscaler=ffx
Dx11Upscaler=ffx_12
VulkanUpscaler=ffx
[FSR]
Fsr4GpuSupport=4   ; INT8 Lite
Fsr4Model=3        ; INT8 Lite
UpscalerIndex=0
```

OptiScaler picks the model by hooking `ffxProvider::IsSupported` of the provider classes it finds by RTTI name in whichever AMD DLL it loads (`fsr4/FSR4Models.cpp`), so nothing depends on fixed offsets in one binary.

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
| `py_modules/fsr4lite.py` | FSR 4 Lite: pinned runtime, provider check, per-game install/fallback/uninstall, log verification |
| `scripts/package.sh` | Builds the installable zip |
