using System;

namespace HelixSRSwapper
{
    public interface IEnvironmentSettings
    {
        PlatformID OSPlatform { get; }
        bool HasWineRegistryKey { get; }
        bool DirectoryExists(string path);
    }
}
