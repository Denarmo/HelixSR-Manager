using System;
using HelixSR.UnityBridge;

class MathTest
{
    static int fails;
    static void Check(bool ok, string what) { if (!ok) { fails++; Console.WriteLine("FAIL: " + what); } }
    static bool Near(float a, float b) { return Math.Abs(a - b) < 1e-4f; }

    static int Main()
    {
        int w, h;
        HelixMath.RenderSize(HelixMath.Quality.Quality, 1920, 1080, out w, out h);
        Check(w == 1280 && h == 720, "Quality 1080p -> 1280x720");
        HelixMath.RenderSize(HelixMath.Quality.UltraPerformance, 3840, 2160, out w, out h);
        Check(w == 1280 && h == 720, "UltraPerf 4K -> 1280x720");
        HelixMath.RenderSize(HelixMath.Quality.Performance, 2560, 1440, out w, out h);
        Check(w == 1280 && h == 720, "Performance 1440p -> 1280x720");

        Check(HelixMath.PhaseCount(1280, 1920) == 18, "Quality phase count = 8 * 2.25 = 18");
        Check(HelixMath.PhaseCount(960, 1920) == 32, "Performance phase count = 32");
        Check(HelixMath.PhaseCount(1920, 1920) == 8, "DLAA phase count = 8");

        Check(Near(HelixMath.Halton(1, 2), 0.5f) && Near(HelixMath.Halton(2, 2), 0.25f) && Near(HelixMath.Halton(3, 2), 0.75f), "Halton base 2");
        Check(Near(HelixMath.Halton(1, 3), 1f / 3f) && Near(HelixMath.Halton(2, 3), 2f / 3f), "Halton base 3");

        for (int frame = 0; frame < 200; frame++)
        {
            float jx, jy;
            HelixMath.Jitter(frame, 18, out jx, out jy);
            Check(jx >= -0.5f && jx < 0.5f && jy >= -0.5f && jy < 0.5f, "jitter within pixel, frame " + frame);
        }
        float a, b, c, d;
        HelixMath.Jitter(0, 18, out a, out b);
        HelixMath.Jitter(18, 18, out c, out d);
        Check(Near(a, c) && Near(b, d), "sequence repeats every phaseCount frames");

        float nx, ny;
        HelixMath.JitterNdc(0.5f, -0.25f, 1280, 720, out nx, out ny);
        Check(Near(nx, 1f / 1280f) && Near(ny, -0.5f / 720f), "NDC jitter");

        Check(Near(HelixMath.MipBias(1280, 1920), (float)(Math.Log(1280.0 / 1920.0, 2) - 1)), "mip bias");

        Console.WriteLine(fails == 0 ? "ALL PASS" : fails + " FAILED");
        return fails == 0 ? 0 : 1;
    }
}
