// helixsr_unity.dll, D3D11 diagnostic backend (phase 3a).
//
// Runs on Unity's render thread via CommandBuffer.IssuePluginEventAndData. It does NOT call DLSS or HelixSR yet: it
//  1. logs the real formats and sizes of the color, depth and motion-vector textures the bridge hands over, and
//  2. upscales color into the output texture with a bilinear fullscreen pass (the same result as the managed blit, but
//     through the native path), so the render-thread plumbing, texture pointers and D3D11 state handling can be
//     checked on any GPU.
// Phase 3b replaces step 2 with NVSDK_NGX_D3D11_* calls in OptiScaler's nvngx.dll (which runs HelixSR on an AMD GPU).
//
// No Unity headers are needed: the callback signature is void (UNITY_INTERFACE_API*)(int, void*) with
// UNITY_INTERFACE_API = __stdcall, and the D3D11 device is taken from the textures themselves.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <d3dcommon.h>
#include <stdio.h>
#include <stdarg.h>
#include <math.h>
#include "helixsr_unity.h"

namespace
{
    template <class T> struct Ref
    {
        T* p = nullptr;
        ~Ref() { if (p) p->Release(); }
        T** put() { if (p) { p->Release(); p = nullptr; } return &p; }
        T* operator->() const { return p; }
        explicit operator bool() const { return p != nullptr; }
    };

    FILE* g_log = nullptr;
    void Log(const char* fmt, ...)
    {
        if (!g_log) g_log = fopen("helixsr_unity.log", "a");
        if (!g_log) return;
        va_list a; va_start(a, fmt); vfprintf(g_log, fmt, a); va_end(a);
        fputc('\n', g_log); fflush(g_log);
    }

    const char* kShader =
        "struct VSOut { float4 pos : SV_Position; float2 uv : TEXCOORD0; };\n"
        "VSOut VSMain(uint id : SV_VertexID) {\n"
        "  VSOut o; float2 uv = float2((id << 1) & 2, id & 2);\n"
        "  o.pos = float4(uv * float2(2, -2) + float2(-1, 1), 0, 1); o.uv = uv; return o; }\n"
        "Texture2D<float4> src : register(t0); SamplerState smp : register(s0);\n"
        "float4 PSMain(VSOut i) : SV_Target { return src.Sample(smp, i.uv); }\n";

    struct Pipeline
    {
        ID3D11Device* device = nullptr; // not owned, only compared
        Ref<ID3D11VertexShader> vs;
        Ref<ID3D11PixelShader> ps;
        Ref<ID3D11SamplerState> sampler;
        Ref<ID3D11RasterizerState> raster;
        Ref<ID3D11BlendState> blend;
        Ref<ID3D11DepthStencilState> depth;
    } g_pipe;

    // Typeless formats (Unity creates its render textures typeless) need a concrete view format.
    DXGI_FORMAT ViewFormat(DXGI_FORMAT f)
    {
        switch (f)
        {
        case DXGI_FORMAT_R8G8B8A8_TYPELESS: return DXGI_FORMAT_R8G8B8A8_UNORM;
        case DXGI_FORMAT_B8G8R8A8_TYPELESS: return DXGI_FORMAT_B8G8R8A8_UNORM;
        case DXGI_FORMAT_R16G16B16A16_TYPELESS: return DXGI_FORMAT_R16G16B16A16_FLOAT;
        case DXGI_FORMAT_R10G10B10A2_TYPELESS: return DXGI_FORMAT_R10G10B10A2_UNORM;
        default: return f;
        }
    }

    bool BuildPipeline(ID3D11Device* dev)
    {
        if (g_pipe.device == dev && g_pipe.ps) return true;
        g_pipe = Pipeline();
        g_pipe.device = dev;

        typedef HRESULT(WINAPI * PFN_Compile)(LPCVOID, SIZE_T, LPCSTR, const void*, void*, LPCSTR, LPCSTR, UINT, UINT, ID3DBlob**, ID3DBlob**);
        HMODULE comp = LoadLibraryA("d3dcompiler_47.dll");
        PFN_Compile compile = comp ? reinterpret_cast<PFN_Compile>(reinterpret_cast<void*>(GetProcAddress(comp, "D3DCompile"))) : nullptr;
        if (!compile) { Log("d3dcompiler_47.dll not available"); return false; }

        Ref<ID3DBlob> vsb, psb, err;
        if (FAILED(compile(kShader, strlen(kShader), "helixsr", nullptr, nullptr, "VSMain", "vs_4_0", 0, 0, vsb.put(), err.put())) ||
            FAILED(compile(kShader, strlen(kShader), "helixsr", nullptr, nullptr, "PSMain", "ps_4_0", 0, 0, psb.put(), err.put())))
        {
            Log("shader compile failed: %s", err ? (const char*)err->GetBufferPointer() : "?");
            return false;
        }
        if (FAILED(dev->CreateVertexShader(vsb->GetBufferPointer(), vsb->GetBufferSize(), nullptr, g_pipe.vs.put())) ||
            FAILED(dev->CreatePixelShader(psb->GetBufferPointer(), psb->GetBufferSize(), nullptr, g_pipe.ps.put())))
            return false;

        D3D11_SAMPLER_DESC sd = {};
        sd.Filter = D3D11_FILTER_MIN_MAG_LINEAR_MIP_POINT;
        sd.AddressU = sd.AddressV = sd.AddressW = D3D11_TEXTURE_ADDRESS_CLAMP;
        sd.MaxLOD = D3D11_FLOAT32_MAX;
        D3D11_RASTERIZER_DESC rd = {};
        rd.FillMode = D3D11_FILL_SOLID; rd.CullMode = D3D11_CULL_NONE; rd.DepthClipEnable = TRUE;
        D3D11_BLEND_DESC bd = {};
        bd.RenderTarget[0].RenderTargetWriteMask = D3D11_COLOR_WRITE_ENABLE_ALL;
        D3D11_DEPTH_STENCIL_DESC dd = {}; // depth and stencil off
        return SUCCEEDED(dev->CreateSamplerState(&sd, g_pipe.sampler.put())) &&
               SUCCEEDED(dev->CreateRasterizerState(&rd, g_pipe.raster.put())) &&
               SUCCEEDED(dev->CreateBlendState(&bd, g_pipe.blend.put())) &&
               SUCCEEDED(dev->CreateDepthStencilState(&dd, g_pipe.depth.put()));
    }

    void LogTexture(const char* what, void* ptr)
    {
        if (!ptr) { Log("  %s: null", what); return; }
        D3D11_TEXTURE2D_DESC d;
        ((ID3D11Texture2D*)ptr)->GetDesc(&d);
        Log("  %s: %ux%u format=%u bind=0x%x samples=%u mips=%u", what, d.Width, d.Height, (unsigned)d.Format, d.BindFlags, d.SampleDesc.Count, d.MipLevels);
    }

    int g_lastRenderW = 0, g_lastRenderH = 0, g_lastOutW = 0, g_lastOutH = 0, g_frames = 0;

    float HalfToFloat(uint16_t h)
    {
        uint32_t sign = (h >> 15) & 1, exp = (h >> 10) & 0x1f, man = h & 0x3ff;
        float v;
        if (exp == 0) v = (float)man * (1.0f / (1 << 24));           // zero and subnormals
        else if (exp == 31) v = 65504.0f;                            // inf/nan, clamp
        else v = (1.0f + man / 1024.0f) * (float)(1 << (exp > 15 ? exp - 15 : 0)) / (float)(1 << (exp < 15 ? 15 - exp : 0));
        return sign ? -v : v;
    }

    // Reads the motion-vector texture back (slow, diagnostic only) and logs how much of it is non-zero. A camera-only
    // scene still has non-zero vectors everywhere while the camera moves; objects that move on their own show up as
    // a small non-zero region when the camera is still.
    void LogMotionStats(ID3D11Device* dev, ID3D11DeviceContext* ctx, ID3D11Texture2D* motion, const HelixSREvaluateParams* p)
    {
        D3D11_TEXTURE2D_DESC d;
        motion->GetDesc(&d);
        if (d.SampleDesc.Count != 1 || (d.Format != DXGI_FORMAT_R16G16_TYPELESS && d.Format != DXGI_FORMAT_R16G16_FLOAT))
        {
            Log("  motion stats skipped: format %u samples %u", (unsigned)d.Format, d.SampleDesc.Count);
            return;
        }
        d.Usage = D3D11_USAGE_STAGING; d.BindFlags = 0; d.MiscFlags = 0; d.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        Ref<ID3D11Texture2D> stg;
        if (FAILED(dev->CreateTexture2D(&d, nullptr, stg.put()))) { Log("  motion stats: staging texture failed"); return; }
        ctx->CopyResource(stg.p, motion);
        D3D11_MAPPED_SUBRESOURCE m;
        if (FAILED(ctx->Map(stg.p, 0, D3D11_MAP_READ, 0, &m))) { Log("  motion stats: map failed"); return; }
        double sum = 0; float maxMag = 0; unsigned long long nonzero = 0, total = (unsigned long long)d.Width * d.Height;
        for (UINT y = 0; y < d.Height; ++y)
        {
            const uint16_t* row = (const uint16_t*)((const uint8_t*)m.pData + (size_t)y * m.RowPitch);
            for (UINT x = 0; x < d.Width; ++x)
            {
                float mx = HalfToFloat(row[x * 2]) * p->mvScaleX, my = HalfToFloat(row[x * 2 + 1]) * p->mvScaleY;
                float mag = sqrtf(mx * mx + my * my);
                if (mag > 0.01f) { ++nonzero; sum += mag; if (mag > maxMag) maxMag = mag; }
            }
        }
        ctx->Unmap(stg.p, 0);
        Log("  motion stats: %.2f%% of texels move, mean %.2f px, max %.2f px (render pixels)",
            100.0 * nonzero / (double)total, nonzero ? sum / nonzero : 0.0, maxMag);
    }

    void Evaluate(const HelixSREvaluateParams* p)
    {
        if (!p || !p->color || !p->output) return;
        ID3D11Texture2D* color = (ID3D11Texture2D*)p->color;
        ID3D11Texture2D* output = (ID3D11Texture2D*)p->output;

        if (p->renderWidth != g_lastRenderW || p->renderHeight != g_lastRenderH || p->outputWidth != g_lastOutW || p->outputHeight != g_lastOutH)
        {
            g_lastRenderW = p->renderWidth; g_lastRenderH = p->renderHeight; g_lastOutW = p->outputWidth; g_lastOutH = p->outputHeight;
            Log("frame %d: render %dx%d -> output %dx%d jitter=(%.3f,%.3f) mv scale=(%.0f,%.0f) reset=%d",
                g_frames, p->renderWidth, p->renderHeight, p->outputWidth, p->outputHeight, p->jitterX, p->jitterY, p->mvScaleX, p->mvScaleY, p->reset);
            LogTexture("color", p->color); LogTexture("depth", p->depth); LogTexture("motion", p->motion); LogTexture("output", p->output);
        }
        // First 64 frames show the jitter sequence; after that one line every 300 frames.
        bool periodic = g_frames < 64 || g_frames % 300 == 0;
        if (periodic && g_frames > 0)
            Log("frame %d: jitter=(%.3f,%.3f) reset=%d", g_frames, p->jitterX, p->jitterY, p->reset);
        bool stats = p->motion && (g_frames == 60 || (g_frames > 0 && g_frames % 300 == 0));
        ++g_frames;

        Ref<ID3D11Device> dev;
        color->GetDevice(dev.put());
        if (!dev || !BuildPipeline(dev.p)) return;
        Ref<ID3D11DeviceContext> ctx;
        dev->GetImmediateContext(ctx.put());
        if (stats) { Log("motion vectors at frame %d:", g_frames - 1); LogMotionStats(dev.p, ctx.p, (ID3D11Texture2D*)p->motion, p); }

        D3D11_TEXTURE2D_DESC cd, od;
        color->GetDesc(&cd); output->GetDesc(&od);
        D3D11_SHADER_RESOURCE_VIEW_DESC sv = {};
        sv.Format = ViewFormat(cd.Format); sv.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D; sv.Texture2D.MipLevels = 1;
        D3D11_RENDER_TARGET_VIEW_DESC rv = {};
        rv.Format = ViewFormat(od.Format); rv.ViewDimension = D3D11_RTV_DIMENSION_TEXTURE2D;
        Ref<ID3D11ShaderResourceView> srv; Ref<ID3D11RenderTargetView> rtv;
        if (FAILED(dev->CreateShaderResourceView(color, &sv, srv.put())) || FAILED(dev->CreateRenderTargetView(output, &rv, rtv.put())))
        {
            Log("view creation failed (color fmt %u, output fmt %u)", (unsigned)cd.Format, (unsigned)od.Format);
            return;
        }

        // Save the state this pass touches; Unity does not expect a plugin to leave it changed.
        Ref<ID3D11RenderTargetView> oldRtv; Ref<ID3D11DepthStencilView> oldDsv;
        ctx->OMGetRenderTargets(1, oldRtv.put(), oldDsv.put());
        Ref<ID3D11BlendState> oldBlend; FLOAT oldFactor[4]; UINT oldMask;
        ctx->OMGetBlendState(oldBlend.put(), oldFactor, &oldMask);
        Ref<ID3D11DepthStencilState> oldDepth; UINT oldRef;
        ctx->OMGetDepthStencilState(oldDepth.put(), &oldRef);
        Ref<ID3D11RasterizerState> oldRaster; ctx->RSGetState(oldRaster.put());
        UINT nvp = 1; D3D11_VIEWPORT oldVp; ctx->RSGetViewports(&nvp, &oldVp);
        Ref<ID3D11VertexShader> oldVs; ctx->VSGetShader(oldVs.put(), nullptr, nullptr);
        Ref<ID3D11PixelShader> oldPs; ctx->PSGetShader(oldPs.put(), nullptr, nullptr);
        Ref<ID3D11ShaderResourceView> oldSrv; ctx->PSGetShaderResources(0, 1, oldSrv.put());
        Ref<ID3D11SamplerState> oldSmp; ctx->PSGetSamplers(0, 1, oldSmp.put());
        Ref<ID3D11InputLayout> oldLayout; ctx->IAGetInputLayout(oldLayout.put());
        D3D11_PRIMITIVE_TOPOLOGY oldTopo; ctx->IAGetPrimitiveTopology(&oldTopo);

        D3D11_VIEWPORT vp = { 0, 0, (FLOAT)od.Width, (FLOAT)od.Height, 0, 1 };
        ID3D11RenderTargetView* rtvs[1] = { rtv.p };
        ctx->OMSetRenderTargets(1, rtvs, nullptr);
        const FLOAT zero[4] = {};
        ctx->OMSetBlendState(g_pipe.blend.p, zero, 0xffffffff);
        ctx->OMSetDepthStencilState(g_pipe.depth.p, 0);
        ctx->RSSetState(g_pipe.raster.p);
        ctx->RSSetViewports(1, &vp);
        ctx->IASetInputLayout(nullptr);
        ctx->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        ctx->VSSetShader(g_pipe.vs.p, nullptr, 0);
        ctx->PSSetShader(g_pipe.ps.p, nullptr, 0);
        ID3D11ShaderResourceView* srvs[1] = { srv.p };
        ctx->PSSetShaderResources(0, 1, srvs);
        ID3D11SamplerState* smps[1] = { g_pipe.sampler.p };
        ctx->PSSetSamplers(0, 1, smps);
        ctx->Draw(3, 0);

        ID3D11ShaderResourceView* noSrv[1] = { nullptr };
        ctx->PSSetShaderResources(0, 1, noSrv); // never leave the color texture bound while Unity renders into it
        ID3D11RenderTargetView* oldRtvs[1] = { oldRtv.p };
        ctx->OMSetRenderTargets(1, oldRtvs, oldDsv.p);
        ctx->OMSetBlendState(oldBlend.p, oldFactor, oldMask);
        ctx->OMSetDepthStencilState(oldDepth.p, oldRef);
        ctx->RSSetState(oldRaster.p);
        ctx->RSSetViewports(1, &oldVp);
        ctx->VSSetShader(oldVs.p, nullptr, 0);
        ctx->PSSetShader(oldPs.p, nullptr, 0);
        ID3D11ShaderResourceView* oldSrvs[1] = { oldSrv.p };
        ctx->PSSetShaderResources(0, 1, oldSrvs);
        ID3D11SamplerState* oldSmps[1] = { oldSmp.p };
        ctx->PSSetSamplers(0, 1, oldSmps);
        ctx->IASetInputLayout(oldLayout.p);
        ctx->IASetPrimitiveTopology(oldTopo);
    }

    void __stdcall OnRenderEvent(int /*eventId*/, void* data)
    {
        // Never let a C++ exception unwind into Unity's render thread.
        try { Evaluate((const HelixSREvaluateParams*)data); }
        catch (...) { Log("exception in Evaluate, frame %d", g_frames); }
    }
}

HELIXSR_API int32_t HelixSR_IsReady() { return 1; }
HELIXSR_API const char* HelixSR_BackendName() { return "d3d11-diagnostic"; }
HELIXSR_API void* HelixSR_GetEvaluateFunc() { return (void*)&OnRenderEvent; }
