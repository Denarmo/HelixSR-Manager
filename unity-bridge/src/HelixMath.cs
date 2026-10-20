using System;

namespace HelixSR.UnityBridge
{
    /// <summary>
    /// Engine-independent math for the Unity bridge (no UnityEngine references, so it is unit-testable outside Unity).
    /// Matches what HelixSR expects from a DLSS caller: DLSS quality ratios, 8 * scale^2 Halton jitter phases.
    /// </summary>
    public static class HelixMath
    {
        public enum Quality { DLAA, Quality, Balanced, Performance, UltraPerformance }

        /// <summary>Render size / display size per DLSS quality mode.</summary>
        public static float RenderRatio(Quality q)
        {
            switch (q)
            {
                case Quality.DLAA: return 1.0f;
                case Quality.Quality: return 1.0f / 1.5f;
                case Quality.Balanced: return 0.58f;
                case Quality.Performance: return 0.5f;
                default: return 1.0f / 3.0f;
            }
        }

        public static void RenderSize(Quality q, int displayW, int displayH, out int w, out int h)
        {
            float r = RenderRatio(q);
            w = Math.Max(1, (int)Math.Round(displayW * r));
            h = Math.Max(1, (int)Math.Round(displayH * r));
        }

        /// <summary>DLSS jitter sequence length: 8 * (display / render)^2.</summary>
        public static int PhaseCount(int renderW, int displayW)
        {
            double scale = (double)displayW / renderW;
            return Math.Max(8, (int)Math.Ceiling(8.0 * scale * scale));
        }

        /// <summary>Halton low-discrepancy sequence value for index (1-based) and base.</summary>
        public static float Halton(int index, int radix)
        {
            float result = 0f, f = 1f;
            int i = index;
            while (i > 0)
            {
                f /= radix;
                result += f * (i % radix);
                i /= radix;
            }
            return result;
        }

        /// <summary>Sub-pixel jitter in render-target pixels, each axis in [-0.5, 0.5).</summary>
        public static void Jitter(int frame, int phaseCount, out float jx, out float jy)
        {
            int i = (frame % phaseCount) + 1;
            jx = Halton(i, 2) - 0.5f;
            jy = Halton(i, 3) - 0.5f;
        }

        /// <summary>Jitter converted to the offset added to the projection matrix (NDC units, 2 per full width).</summary>
        public static void JitterNdc(float jx, float jy, int renderW, int renderH, out float nx, out float ny)
        {
            nx = 2f * jx / renderW;
            ny = 2f * jy / renderH;
        }

        /// <summary>Texture mip bias so textures keep display-resolution detail: log2(render / display) - 1.</summary>
        public static float MipBias(int renderW, int displayW)
        {
            return (float)(Math.Log((double)renderW / displayW, 2.0) - 1.0);
        }
    }
}
