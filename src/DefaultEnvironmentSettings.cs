using System;
using System.IO;
using Microsoft.Win32;

namespace HelixSRSwapper
{
    public class DefaultEnvironmentSettings : IEnvironmentSettings
    {
        public PlatformID OSPlatform => Environment.OSVersion.Platform;

        public bool HasWineRegistryKey
        {
            get
            {
                try
                {
                    using (var k = Registry.CurrentUser.OpenSubKey(@"Software\Wine"))
                    {
                        return k != null;
                    }
                }
                catch { }
                return false;
            }
        }

        public bool DirectoryExists(string path)
        {
            return Directory.Exists(path);
        }
    }
}
