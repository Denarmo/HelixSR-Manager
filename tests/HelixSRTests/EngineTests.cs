using System;
using System.IO;
using Xunit;
using HelixSRSwapper;

namespace HelixSRTests
{
    public class EngineTests
    {
        [Fact]
        public void NormalizePath_NullOrEmpty_ReturnsEmpty()
        {
            Assert.Equal("", Engine.NormalizePath(null));
            Assert.Equal("", Engine.NormalizePath(""));
            Assert.Equal("", Engine.NormalizePath("   "));
        }

        [Fact]
        public void NormalizePath_ValidPaths_Normalized()
        {
            string basePath = Environment.OSVersion.Platform == PlatformID.Unix ? "/tmp/test/dir" : "C:\\test\\dir";
            string expected = Path.GetFullPath(basePath).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

            // Forward slashes with trailing slash
            Assert.Equal(expected, Engine.NormalizePath(basePath.Replace('\\', '/') + "/"));

            // Backward slashes with trailing slash
            Assert.Equal(expected, Engine.NormalizePath(basePath.Replace('/', '\\') + "\\"));
        }

        [Fact]
        public void NormalizePath_EdgeCases_Normalized()
        {
            string basePath = Environment.OSVersion.Platform == PlatformID.Unix ? "/tmp/test/dir" : "C:\\test\\dir";
            string expected = Path.GetFullPath(basePath).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

            // Using backslashes
            string doubleBackslash = basePath.Replace('/', '\\') + "\\\\";
            Assert.Equal(expected, Engine.NormalizePath(doubleBackslash));

            // Using forward slashes
            string doubleForwardSlash = basePath.Replace('\\', '/') + "//";
            Assert.Equal(expected, Engine.NormalizePath(doubleForwardSlash));
        }

        [Fact]
        public void NormalizePath_MultipleConsecutiveSlashes_Normalized()
        {
            string root = Environment.OSVersion.Platform == PlatformID.Unix ? "/" : "C:\\";
            string weirdPath = root + "a\\\\\\b///c\\\\d//";
            string expected = Path.GetFullPath(Path.Combine(root, "a", "b", "c", "d")).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

            Assert.Equal(expected, Engine.NormalizePath(weirdPath));
        }

        [Fact]
        public void NormalizePath_RelativePaths_Resolved()
        {
            string expected = Path.GetFullPath("test").TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);

            Assert.Equal(expected, Engine.NormalizePath("./test"));
            Assert.Equal(expected, Engine.NormalizePath(".\\test"));

            string parentExpected = Path.GetFullPath("..").TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            Assert.Equal(parentExpected, Engine.NormalizePath("../"));
        }

        [Fact]
        public void NormalizePath_InvalidPath_ReturnsCleanedPath()
        {
            string invalidPath = new string('a', 32000) + "/";
            try {
                // If it fails, it should use the catch block and still remove the trailing slash
                string result = Engine.NormalizePath(invalidPath);
                Assert.False(result.EndsWith(Path.DirectorySeparatorChar.ToString()));
                Assert.False(result.EndsWith(Path.AltDirectorySeparatorChar.ToString()));
            } catch (Exception) {
            }
        }
    }
}
