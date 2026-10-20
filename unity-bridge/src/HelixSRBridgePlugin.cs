// HelixSR Unity bridge, phase 2 prototype: Mono + Built-in render pipeline (BepInEx 5), D3D11 or D3D12.
// Tested only for compilation against the stubs in ../stubs; needs a real game run. Math is unit tested (HelixMath.cs).
// Flow per frame: jitter the projection, render the main camera into a render-scale target, then upscale to the screen.
// The upscale is native (NativeBridge) when helixsr_unity.dll is ready, else a plain scaled blit so the whole
// render-scale pipeline can be checked on any GPU before the native side exists. See docs/unity-support.md.
using BepInEx;
using BepInEx.Configuration;
using UnityEngine;
using UnityEngine.Rendering;

namespace HelixSR.UnityBridge
{
    [BepInPlugin("com.helixsr.unitybridge", "HelixSR Unity Bridge", "0.2.0")]
    public class HelixSRBridgePlugin : BaseUnityPlugin
    {
        private ConfigEntry<HelixMath.Quality> _quality;
        private ConfigEntry<bool> _enabled, _jitter;
        private int _frame;
        private int _lastRenderW, _lastRenderH;
        private RenderTexture _color, _output;
        private CommandBuffer _cmd;
        private Camera _active;
        private float _jx, _jy;

        private void Awake()
        {
            _enabled = Config.Bind("General", "Enabled", true, "Turn the bridge off without uninstalling it.");
            _jitter = Config.Bind("Debug", "Jitter", true, "Sub-pixel camera jitter. Turn off to tell jitter shimmer (expected until a temporal upscaler resolves it) from other causes.");
            _quality = Config.Bind("General", "Quality", HelixMath.Quality.Quality, "DLSS quality mode HelixSR is driven with.");
            _cmd = new CommandBuffer { name = "HelixSR upscale" };
            Camera.onPreCull += HandlePreCull;
            Camera.onPostRender += HandlePostRender;
            Logger.LogInfo("HelixSR Unity bridge loaded; native upscaler " + (NativeBridge.IsReady ? "ready" : "not available, using scaled blit")
                + "; quality=" + _quality.Value + " jitter=" + _jitter.Value);
        }

        private void OnDestroy()
        {
            Camera.onPreCull -= HandlePreCull;
            Camera.onPostRender -= HandlePostRender;
            if (_color != null) _color.Release();
            if (_output != null) _output.Release();
            if (_cmd != null) _cmd.Release();
        }

        // Only the main game camera is upscaled; UI/overlay cameras are left alone.
        private static bool IsTarget(Camera cam)
        {
            return cam != null && cam == Camera.main && cam.cameraType == CameraType.Game && cam.targetTexture == null;
        }

        private void EnsureTarget(int w, int h)
        {
            if (_color != null && _color.width == w && _color.height == h) return;
            if (_color != null) _color.Release();
            _color = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32) { name = "HelixSR color", filterMode = FilterMode.Bilinear };
            _color.Create();
        }

        // Display-resolution target the native side writes into; it is then copied to the back buffer.
        private void EnsureOutput(int w, int h)
        {
            if (_output != null && _output.width == w && _output.height == h) return;
            if (_output != null) _output.Release();
            _output = new RenderTexture(w, h, 0, RenderTextureFormat.ARGB32) { name = "HelixSR output", filterMode = FilterMode.Bilinear };
            _output.Create();
        }

        // Not named OnPreCull/OnPostRender: Unity treats those names on a MonoBehaviour as parameterless messages and
        // logs "The message may not have any parameters" every frame (seen in Art of Rally's Player.log).
        private void HandlePreCull(Camera cam)
        {
            if (!_enabled.Value || !IsTarget(cam)) return;

            int dispW = Screen.width, dispH = Screen.height, rw, rh;
            HelixMath.RenderSize(_quality.Value, dispW, dispH, out rw, out rh);

            // Depth and motion vectors are what HelixSR (DLSS) needs besides color.
            cam.depthTextureMode |= DepthTextureMode.Depth | DepthTextureMode.MotionVectors;

            // Sub-pixel jitter on the projection; the unjittered matrix stays available for motion vectors.
            float nx, ny;
            HelixMath.Jitter(_frame++, HelixMath.PhaseCount(rw, dispW), out _jx, out _jy);
            if (!_jitter.Value) { _jx = 0f; _jy = 0f; }
            HelixMath.JitterNdc(_jx, _jy, rw, rh, out nx, out ny);
            cam.ResetProjectionMatrix();
            cam.nonJitteredProjectionMatrix = cam.projectionMatrix;
            Matrix4x4 p = cam.projectionMatrix;
            p.m02 += nx;
            p.m12 += ny;
            cam.projectionMatrix = p;
            cam.useJitteredProjectionMatrixForTransparentRendering = true;
            Shader.SetGlobalFloat("_HelixSRMipBias", HelixMath.MipBias(rw, dispW));

            // Render the scene at the lower resolution; the UI (overlay canvases) still draws at full resolution afterwards.
            EnsureTarget(rw, rh);
            cam.targetTexture = _color;
            _active = cam;
            if (rw != _lastRenderW || rh != _lastRenderH) { _lastRenderW = rw; _lastRenderH = rh; _frame = 0; }
        }

        private void HandlePostRender(Camera cam)
        {
            if (cam == null || cam != _active) return;
            _active = null;
            cam.targetTexture = null;
            cam.ResetProjectionMatrix();

            if (NativeBridge.IsReady)
            {
                var depth = Shader.GetGlobalTexture("_CameraDepthTexture");
                var motion = Shader.GetGlobalTexture("_CameraMotionVectorsTexture");
                if (depth != null && motion != null)
                {
                    EnsureOutput(Screen.width, Screen.height);
                    var p = new EvaluateParams
                    {
                        color = _color.GetNativeTexturePtr(),
                        depth = depth.GetNativeTexturePtr(),
                        motion = motion.GetNativeTexturePtr(),
                        output = _output.GetNativeTexturePtr(),
                        jitterX = _jx, jitterY = _jy,
                        mvScaleX = _color.width, mvScaleY = _color.height,
                        renderWidth = _color.width, renderHeight = _color.height,
                        outputWidth = Screen.width, outputHeight = Screen.height,
                        reset = _frame <= 1 ? 1 : 0,
                    };
                    _cmd.Clear();
                    NativeBridge.Queue(_cmd, ref p);
                    Graphics.ExecuteCommandBuffer(_cmd);
                    Graphics.Blit(_output, (RenderTexture)null);
                    return;
                }
            }

            // Fallback: plain scaled blit to the back buffer.
            Graphics.Blit(_color, (RenderTexture)null);
        }
    }
}
