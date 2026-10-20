# HelixSR Unity bridge (prototype)

Game-side half of Unity support, see [../docs/unity-support.md](../docs/unity-support.md). First test game: Art of Rally
(Unity 2019.4.38, Mono, Built-in pipeline, Direct3D 11, confirmed on an installed copy).

| File | State |
|---|---|
| `src/HelixMath.cs` | DLSS render sizes, jitter phases, Halton jitter, mip bias. Unit tested. |
| `src/HelixSRBridgePlugin.cs` | BepInEx 5 plugin, Mono + Built-in: jitters the projection, renders the main camera into a render-scale target, then upscales to the back buffer (native call, or a scaled blit when the native DLL is missing). **Compiles against the stubs; never run in a real game.** |
| `src/NativeBridge.cs` | P/Invoke + `IssuePluginEventAndData` hand-off. Same compile-only status. |
| `native/helixsr_unity.h` | Contract for the native plugin. **Not implemented.** Phase 3: call NGX D3D11 in OptiScaler's `nvngx.dll` (`Dx11Upscaler=fsr31_12`). |
| `stubs/UnityStubs.cs` | Minimal UnityEngine/BepInEx stand-ins, only for the compile check. |

Checks (from this folder):

```
mcs -out:mt.exe src/HelixMath.cs tests/MathTest.cs && mono mt.exe          # math, expects ALL PASS
mcs -target:library -out:bridge.dll src/*.cs stubs/UnityStubs.cs           # compile check only
```

## Testing on the Art of Rally PC

That PC has an NVIDIA RTX 5070, not an AMD GPU, so it cannot show HelixSR itself. It can validate the bridge's own half:
render-scale target, jitter, depth and motion vectors, UI left at full resolution, and (once the native side calls real
DLSS through NGX) that the inputs are correct. HelixSR on AMD is a second step on an AMD machine.
