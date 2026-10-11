using System;
using System.Reflection;
using HelixSRSwapper;

class Program
{
    static int Main()
    {
        int passed = 0;
        int failed = 0;

        try {
            var t = new HelixSRTests.EngineTests();

            void RunTest(Action act, string name) {
                try {
                    act();
                    passed++;
                    Console.WriteLine($"PASS: {name}");
                } catch (Exception e) {
                    failed++;
                    Console.WriteLine($"FAIL: {name}");
                    Console.WriteLine(e);
                }
            }

            RunTest(t.NormalizePath_NullOrEmpty_ReturnsEmpty, "NormalizePath_NullOrEmpty_ReturnsEmpty");
            RunTest(t.NormalizePath_ValidPaths_Normalized, "NormalizePath_ValidPaths_Normalized");
            RunTest(t.NormalizePath_EdgeCases_Normalized, "NormalizePath_EdgeCases_Normalized");
            RunTest(t.NormalizePath_MultipleConsecutiveSlashes_Normalized, "NormalizePath_MultipleConsecutiveSlashes_Normalized");
            RunTest(t.NormalizePath_RelativePaths_Resolved, "NormalizePath_RelativePaths_Resolved");
            RunTest(t.NormalizePath_InvalidPath_ReturnsCleanedPath, "NormalizePath_InvalidPath_ReturnsCleanedPath");
        }
        catch (Exception ex)
        {
            Console.WriteLine("Tests failed to run: " + ex);
            return 1;
        }

        Console.WriteLine($"\nResults: {passed} passed, {failed} failed");
        return failed == 0 ? 0 : 1;
    }
}
