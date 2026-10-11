using System;
using NUnit.Framework;
using HelixSRSwapper;

namespace Tests
{
    [TestFixture]
    public class EngineTests
    {
        private class MockEnvironmentSettings : IEnvironmentSettings
        {
            public PlatformID OSPlatform { get; set; } = PlatformID.Win32NT;
            public bool HasWineRegistryKey { get; set; } = false;

            public bool ZHomeExists { get; set; } = false;
            public bool HomeExists { get; set; } = false;

            public bool DirectoryExists(string path)
            {
                if (path == @"Z:\home") return ZHomeExists;
                if (path == "/home") return HomeExists;
                return false;
            }
        }

        [Test]
        public void IsRunningOnWineOrLinux_WhenPlatformIsUnix_ReturnsTrue()
        {
            var env = new MockEnvironmentSettings { OSPlatform = PlatformID.Unix };
            Assert.IsTrue(Engine.IsRunningOnWineOrLinux(env));
        }

        [Test]
        public void IsRunningOnWineOrLinux_WhenPlatformIsMacOSX_ReturnsTrue()
        {
            var env = new MockEnvironmentSettings { OSPlatform = PlatformID.MacOSX };
            Assert.IsTrue(Engine.IsRunningOnWineOrLinux(env));
        }

        [Test]
        public void IsRunningOnWineOrLinux_WhenWineRegistryKeyExists_ReturnsTrue()
        {
            var env = new MockEnvironmentSettings { OSPlatform = PlatformID.Win32NT, HasWineRegistryKey = true };
            Assert.IsTrue(Engine.IsRunningOnWineOrLinux(env));
        }

        [Test]
        public void IsRunningOnWineOrLinux_WhenZHomeExists_ReturnsTrue()
        {
            var env = new MockEnvironmentSettings { OSPlatform = PlatformID.Win32NT, HasWineRegistryKey = false, ZHomeExists = true };
            Assert.IsTrue(Engine.IsRunningOnWineOrLinux(env));
        }

        [Test]
        public void IsRunningOnWineOrLinux_WhenHomeExists_ReturnsTrue()
        {
            var env = new MockEnvironmentSettings { OSPlatform = PlatformID.Win32NT, HasWineRegistryKey = false, HomeExists = true };
            Assert.IsTrue(Engine.IsRunningOnWineOrLinux(env));
        }

        [Test]
        public void IsRunningOnWineOrLinux_WhenNoLinuxIndicators_ReturnsFalse()
        {
            var env = new MockEnvironmentSettings { OSPlatform = PlatformID.Win32NT, HasWineRegistryKey = false, ZHomeExists = false, HomeExists = false };
            Assert.IsFalse(Engine.IsRunningOnWineOrLinux(env));
        }
    }
}
