using System;
using System.Runtime.InteropServices;
using UnityEngine;

namespace HelixSR.UnityBridge
{
    /// <summary>Mirrors HelixSREvaluateParams in native/helixsr_unity.h (same field order; both sides pad the 68 bytes to 72 on x64).</summary>
    [StructLayout(LayoutKind.Sequential)]
    public struct EvaluateParams
    {
        public IntPtr color, depth, motion, output;
        public float jitterX, jitterY, mvScaleX, mvScaleY;
        public int renderWidth, renderHeight, outputWidth, outputHeight;
        public int reset;
    }

    /// <summary>P/Invoke wrapper; every failure just means "use the managed fallback".</summary>
    public static class NativeBridge
    {
        private const string Dll = "helixsr_unity";

        [DllImport(Dll)] private static extern int HelixSR_IsReady();
        [DllImport(Dll)] private static extern IntPtr HelixSR_GetEvaluateFunc();

        private static bool _probed;
        private static bool _ready;
        private static IntPtr _evaluate;

        public static bool IsReady
        {
            get
            {
                if (!_probed)
                {
                    _probed = true;
                    try
                    {
                        _ready = HelixSR_IsReady() != 0;
                        if (_ready) _evaluate = HelixSR_GetEvaluateFunc();
                        _ready = _ready && _evaluate != IntPtr.Zero;
                    }
                    catch (DllNotFoundException) { _ready = false; }
                    catch (EntryPointNotFoundException) { _ready = false; }
                }
                return _ready;
            }
        }

        // A few unmanaged slots, because the render thread reads them one or two frames after they are written.
        private const int Slots = 4;
        private static readonly IntPtr[] _slots = new IntPtr[Slots];
        private static int _next;

        /// <summary>Queues the native evaluate call on the render thread.</summary>
        public static void Queue(UnityEngine.Rendering.CommandBuffer cmd, ref EvaluateParams p)
        {
            int i = _next++ % Slots;
            if (_slots[i] == IntPtr.Zero) _slots[i] = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(EvaluateParams)));
            Marshal.StructureToPtr(p, _slots[i], false);
            cmd.IssuePluginEventAndData(_evaluate, 0, _slots[i]);
        }
    }
}
