// Contract between the managed bridge (HelixSRBridgePlugin) and the native plugin helixsr_unity.dll.
// The native side is NOT implemented yet; the managed side falls back to a plain scaled blit when the DLL is missing
// or reports not ready, so the render-scale pipeline can be tested on any GPU first.
#pragma once
#include <stdint.h>

#ifdef _WIN32
#define HELIXSR_API extern "C" __declspec(dllexport)
#else
#define HELIXSR_API extern "C"
#endif

// Filled by the managed side and passed through CommandBuffer.IssuePluginEventAndData, so it is read on the render thread.
// Textures are native pointers (RenderTexture.GetNativeTexturePtr): ID3D11Texture2D* on D3D11.
struct HelixSREvaluateParams
{
    void*   color;        // render-resolution scene color, before UI
    void*   depth;        // render-resolution depth (_CameraDepthTexture)
    void*   motion;       // render-resolution motion vectors (_CameraMotionVectorsTexture), UV units
    void*   output;       // display-resolution target
    float   jitterX;      // sub-pixel jitter applied this frame, render pixels
    float   jitterY;
    float   mvScaleX;     // factor that converts motion vectors to render pixels
    float   mvScaleY;
    int32_t renderWidth;
    int32_t renderHeight;
    int32_t outputWidth;
    int32_t outputHeight;
    int32_t reset;        // 1 on the first frame and after camera cuts
};

// 1 when the native side can evaluate (DLSS/HelixSR reachable), 0 when the managed fallback blit should run.
HELIXSR_API int32_t HelixSR_IsReady();

// Render event callback for GL.IssuePluginEvent / CommandBuffer.IssuePluginEventAndData; data = HelixSREvaluateParams*.
// Phase 3: call NVSDK_NGX_D3D11_* in nvngx.dll (OptiScaler's `Dx11Upscaler=fsr31_12` then runs HelixSR on a D3D12 device).
HELIXSR_API void* HelixSR_GetEvaluateFunc();
