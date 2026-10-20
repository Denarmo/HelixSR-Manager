# HelixSR Unity bridge (prototype)

Game-side half of Unity support, see [../docs/unity-support.md](../docs/unity-support.md). First test game: Art of Rally
(Unity 2019.4.38, Mono, Built-in pipeline, Direct3D 11, confirmed on an installed copy).

| File | State |
|---|---|
| `src/HelixMath.cs` | DLSS render sizes, jitter phases, Halton jitter, mip bias. Unit tested. |
| `src/HelixSRBridgePlugin.cs` | BepInEx 5 plugin, Mono + Built-in: jitters the projection, renders the main camera into a render-scale target, then upscales to the back buffer (native call, or a scaled blit when the native DLL is missing). **Compiles against the stubs; never run in a real game.** |
| `src/NativeBridge.cs` | P/Invoke + `IssuePluginEventAndData` hand-off. Same compile-only status. |
| `native/helixsr_unity.h` | Contract for the native plugin. |
| `native/helixsr_unity.cpp` | D3D11 diagnostic backend (phase 3a): logs the real formats/sizes of color, depth and motion textures to `helixsr_unity.log` and upscales color into the output with a bilinear pass, saving and restoring the D3D11 state it touches. **Cross-compiles with mingw, never run.** Phase 3b: call NGX D3D11 in OptiScaler's `nvngx.dll` (`Dx11Upscaler=fsr31_12`) instead of the bilinear pass. |
| `stubs/UnityStubs.cs` | Minimal UnityEngine/BepInEx stand-ins, only for the compile check. |

Checks (from this folder):

```
mcs -out:mt.exe src/HelixMath.cs tests/MathTest.cs && mono mt.exe          # math, expects ALL PASS
mcs -target:library -out:bridge.dll src/*.cs stubs/UnityStubs.cs           # compile check only
x86_64-w64-mingw32-g++ -std=c++17 -O2 -Wall -Wextra -shared -static-libgcc -static-libstdc++ \
  -o helixsr_unity.dll native/helixsr_unity.cpp                              # needs g++-mingw-w64-x86-64
```

## Install for a test (Windows)

1. Unpack BepInEx 5 (x64, [releases](https://github.com/BepInEx/BepInEx/releases), `BepInEx_win_x64_5.4.x.zip`) into the
   game folder (next to the exe), start the game once and quit so `BepInEx\config` and `LogOutput.log` exist.
2. Run `build-plugin.bat "<game folder>"`. It builds `BepInEx\plugins\HelixSRBridge.dll` with the .NET Framework `csc.exe`
   that ships with Windows and copies `prebuilt\helixsr_unity.dll` (built from `native/` with mingw-w64) into the game folder.
3. Start the game. Logs: `BepInEx\LogOutput.log`, `helixsr_unity.log` (game folder). Settings: `BepInEx\config\com.helixsr.unitybridge.cfg`.
4. Undo: delete `winhttp.dll`, `doorstop_config.ini`, `BepInEx\`, `helixsr_unity.dll` and `helixsr_unity.log`.

The manager does not install any of this yet.

## Testing on the Art of Rally PC

That PC has an NVIDIA RTX 5070, not an AMD GPU, so it cannot show HelixSR itself. It can validate the bridge's own half:
render-scale target, jitter, depth and motion vectors, UI left at full resolution, and (once the native side calls real
DLSS through NGX) that the inputs are correct. HelixSR on AMD is a second step on an AMD machine.
