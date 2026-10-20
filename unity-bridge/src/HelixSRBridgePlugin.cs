// HelixSR Unity bridge, phase 2 prototype: Mono + Built-in render pipeline (BepInEx 5).
// NOT COMPILED OR RUN YET: needs BepInEx.Core and UnityEngine reference assemblies and a real game on AMD hardware.
// The math is in HelixMath.cs (unit tested). See docs/unity-support.md.
using System;
using BepInEx;
using BepInEx.Configuration;
using UnityEngine;
using UnityEngine.Rendering;

namespace HelixSR.UnityBridge
{
    [BepInPlugin("com.helixsr.unitybridge", "HelixSR Unity Bridge", "0.1.0")]
    public class HelixSRBridgePlugin : BaseUnityPlugin
    {
        private ConfigEntry<HelixMath.Quality> _quality;
        private ConfigEntry<bool> _enabled;
        private int _frame;

        private void Awake()
        {
            _enabled = Config.Bind("General", "Enabled", true, "Turn the bridge off without uninstalling it.");
            _quality = Config.Bind("General", "Quality", HelixMath.Quality.Quality, "DLSS quality mode HelixSR is driven with.");
            Camera.onPreCull += OnPreCull;
            Camera.onPostRender += OnPostRender;
            Logger.LogInfo("HelixSR Unity bridge loaded");
        }

        private void OnDestroy()
        {
            Camera.onPreCull -= OnPreCull;
            Camera.onPostRender -= OnPostRender;
        }

        // Only the main game camera is upscaled; UI/overlay cameras are left alone.
        private static bool IsTarget(Camera cam)
        {
            return cam != null && cam == Camera.main && cam.cameraType == CameraType.Game && cam.targetTexture == null;
        }

        private void OnPreCull(Camera cam)
        {
            if (!_enabled.Value || !IsTarget(cam)) return;

            int dispW = Screen.width, dispH = Screen.height, rw, rh;
            HelixMath.RenderSize(_quality.Value, dispW, dispH, out rw, out rh);

            // Depth and motion vectors are what HelixSR (DLSS) needs besides color.
            cam.depthTextureMode |= DepthTextureMode.Depth | DepthTextureMode.MotionVectors;

            // Sub-pixel jitter on the projection; the unjittered matrix stays available for motion vectors.
            float jx, jy, nx, ny;
            HelixMath.Jitter(_frame++, HelixMath.PhaseCount(rw, dispW), out jx, out jy);
            HelixMath.JitterNdc(jx, jy, rw, rh, out nx, out ny);
            cam.ResetProjectionMatrix();
            cam.nonJitteredProjectionMatrix = cam.projectionMatrix;
            Matrix4x4 p = cam.projectionMatrix;
            p.m02 += nx;
            p.m12 += ny;
            cam.projectionMatrix = p;
            cam.useJitteredProjectionMatrixForTransparentRendering = true;

            Shader.SetGlobalFloat("_HelixSRMipBias", HelixMath.MipBias(rw, dispW));
        }

        private void OnPostRender(Camera cam)
        {
            if (!_enabled.Value || !IsTarget(cam)) return;
            // TODO(phase 2): render the camera into a render-scale target (RenderTexture of rw x rh), then issue
            // CommandBuffer.IssuePluginEventAndData(helixsr_unity, color, depth, motion, jitter) so the native side
            // upscales into the display-resolution target. Native side (helixsr_unity.dll) does not exist yet.
        }
    }
}
