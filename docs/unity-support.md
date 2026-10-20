# Unity support plan

Goal: HelixSR (DLSS Model E on AMD) in Unity games that have no DLSS, FSR or XeSS, installed by HelixSR Manager in one click like every other route.

## Why Unity games need more than OptiScaler

HelixSR needs the game's low-resolution color, depth, per-pixel motion vectors and the sub-pixel camera jitter every frame. OptiScaler and the DLSS loader only intercept a game that already hands those to an upscaler. A Unity game without one never produces them in a usable form, so the manager has to put something inside the game that does: a **HelixSR Unity bridge**.

## Architecture

```
Game (Unity player)
 └─ BepInEx (winhttp.dll doorstop)            mod loader, deployed by the manager
     └─ HelixSR.UnityBridge.dll  (C#)          per-frame logic inside Unity
         │  lowers render resolution, jitters the camera, requests depth + motion vectors,
         │  hands native texture pointers to the render thread (CommandBuffer.IssuePluginEventAndData)
         └─ helixsr_unity.dll  (C++)            render-thread side
             ├─ D3D12 game: FFX API (FSR 3.1 upscale) straight into HelixSR's amd_fidelityfx_dx12.dll
             └─ D3D11 game: NVNGX D3D11 DLSS calls into OptiScaler (nvngx.dll),
                            OptiScaler `Dx11Upscaler=fsr31_12` runs HelixSR on its D3D11on12 device
```

Why two native paths: HelixSR is a D3D12 FSR 3.1 backend only. On D3D12 the bridge can call it directly with no OptiScaler. On D3D11 (the Unity default, and Dreamlight Valley's API) OptiScaler already solves the D3D11-to-D3D12 interop, so the bridge speaks DLSS to it rather than reimplementing that.

### Managed bridge, per render pipeline

| Pipeline | Inputs | Where the upscale runs |
|---|---|---|
| Built-in | `Camera.depthTextureMode \|= Depth \| MotionVectors`; jitter via `camera.nonJitteredProjectionMatrix` + jittered `projectionMatrix` (as Unity's PostProcessing TAA does) | Camera renders into a low-res target, CommandBuffer upscales into the full-res target before post FX. Reference: ndepoel/FSR3Unity (MIT). |
| URP | URP motion-vector pass (enabled when TAA/STP or a feature requests motion vectors); jitter through the camera's projection | A `ScriptableRendererFeature` injected at runtime; render scale via the pipeline asset's `renderScale`. |
| HDRP | HDRP has DLSS built in (`HDAdditionalCameraData.allowDeepLearningSuperSampling` + dynamic resolution) when the build ships NVIDIA's Unity plugin | Turn on the game's own hidden DLSS; OptiScaler then reaches HelixSR as for any DLSS game. Fall back to the URP-style feature otherwise. |

Jitter: Halton(2,3) with `8 × scale²` phases, matching what HelixSR expects from DLSS. Mip bias lowered by `log2(render/display)`.

### Scripting backends

- **Mono** (`<exe>_Data\Managed`): BepInEx 5, plain Harmony patches.
- **IL2CPP** (`GameAssembly.dll`): BepInEx 6 (IL2CPP builds, Il2CppInterop). Injecting a `ScriptableRendererFeature` needs class injection; that's the hardest part of the project and the reason Mono + Built-in comes first.

One C# source tree, two build targets.

## Manager work

1. **Detection (done in this PR):** `DetectUnity` / `detect_unity` fill engine version, backend, pipeline, whether the build ships the D3D12 player (`D3D12\D3D12Core.dll`) and whether BepInEx is already present. Unity badge and filter pill.
2. **Unity bridge route:** a fourth route next to OptiScaler / Direct / DLSS loader, offered for Unity games with no upscaler inputs.
   - Download pinned BepInEx 5 or 6 by backend, SHA-256 checked like the other downloads.
   - Copy the bridge (managed + native) and a `HelixSR` folder with the core DLL.
   - D3D11 games: also deploy OptiScaler as `nvngx.dll` target with `Dx11Upscaler=fsr31_12`.
   - Optional `-force-d3d12` when `UnityHasD3D12` is set (shown as the launch option, like the Proton overrides).
   - Track every file in `helixsr-install.json`; uninstall removes BepInEx only if the manager installed it.
   - Linux: `WINEDLLOVERRIDES="winhttp=n,b"` for the doorstop (plus `dxgi`/`nvngx` when OptiScaler is used).
3. **Per-game profiles** for games that need tweaks (which camera to upscale, UI camera to leave alone), starting with Disney Dreamlight Valley.

## First test game: Art of Rally

Chosen by the project owner. What is known (not yet checked on an installed copy):

- Unity **2019.4.38** (from a third-party game profile; the manager's detector reads this from `globalgamemanagers`), D3D11 (inferred, same source). Unity 2019 has no shippable D3D12 player, so the **D3D11 path through OptiScaler is required**; the direct D3D12 path from phase 2 cannot be used here.
- Likely Mono + Built-in pipeline (typical for a 2019 Unity game), which is what the plugin skeleton targets. First thing to do on a real install: run the manager's Unity detection on the game folder and confirm backend and pipeline.
- Unity 2019 Built-in has no native motion-vector texture for all cameras; `Camera.depthTextureMode |= MotionVectors` works for opaque geometry only, so expect ghosting on vehicles' particle/transparent effects until the plugin adds a custom motion pass.
- Singleplayer racing game, so the anti-cheat concern from the plan does not apply.

Revised order: render-scale target and DLSS-call hand-off to OptiScaler (`Dx11Upscaler=fsr31_12`) first, then the manager route.

## Phases

1. Detection in the manager (this PR).
2. Bridge prototype: Mono + Built-in + D3D12, one test game, FFX straight into HelixSR. Proves the jitter/motion-vector/upscale loop.
3. D3D11 path through OptiScaler.
4. URP, then IL2CPP (BepInEx 6). Disney Dreamlight Valley (Unity 6, IL2CPP, URP, D3D11) lands here.
5. HDRP built-in DLSS toggle.
6. Bridge route in the manager UI on both editions.

## Risks

- Every phase after 1 needs testing on real AMD hardware in real games; nothing can be checked in CI.
- Games with online features or anti-cheat: BepInEx can be flagged. Show the same single-player warning as the DLSS loader route. Dreamlight Valley is live-service with multiplayer.
- UI drawn by the same camera gets upscaled too; profiles need to pick the right camera.
- Games that use their own TAA keep it on top of HelixSR unless the bridge disables it.
