# HelixSR Unity bridge (prototype)

Game-side half of Unity support, see [../docs/unity-support.md](../docs/unity-support.md).

| File | State |
|---|---|
| `src/HelixMath.cs` | DLSS render sizes, jitter phases, Halton jitter, mip bias. Unit tested: `mcs -out:mt.exe src/HelixMath.cs tests/MathTest.cs && mono mt.exe` |
| `src/HelixSRBridgePlugin.cs` | BepInEx 5 plugin for Mono + Built-in pipeline: depth + motion vectors, projection jitter. **Not compiled or run yet**; the render-scale target and the native hand-off are TODOs. |
| native `helixsr_unity.dll` | Not started. D3D12: FFX API into HelixSR. D3D11: DLSS calls into OptiScaler. |

Everything past the math needs a real Unity game on AMD hardware to verify.
