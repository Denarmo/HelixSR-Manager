using System;
using System.Collections.Generic;

namespace HelixSRSwapper
{
    public class GameInfo
    {
        public string Id { get; set; }
        public string Name { get; set; }
        public string Folder { get; set; }
        public string ExeFolder { get; set; }
        public string ExeName { get; set; }
        public string Launcher { get; set; }
        public string AppId { get; set; }
        public string LocalCoverPath { get; set; }
        public string RemoteCoverUrl { get; set; }
        public string LocalHeroPath { get; set; }
        public string RemoteHeroUrl { get; set; }
        public List<string> Inputs { get; set; }
        public List<string> FsrTargets { get; set; }
        public string FoundNvngxDlssPath { get; set; }
        public string Route { get; set; } // "optiscaler" or "direct"
        public string OptiDllName { get; set; } // "dxgi.dll", "winmm.dll", "version.dll", "dbghelp.dll", "d3d12.dll", "wininet.dll", "winhttp.dll", "OptiScaler.asi"
        public bool UseFakeNvapi { get; set; }
        public bool InstallReFramework { get; set; }
        public bool Installed { get; set; }
        public string Version { get; set; }
        public string RouteDisplay
        {
            get
            {
                if (Route == "direct") return "Direct FSR 3.1";
                if (Route == "optiscaler") return string.Format("OptiScaler ({0})", string.IsNullOrEmpty(OptiDllName) ? "dxgi.dll" : OptiDllName);
                return "Auto";
            }
        }
        public string StatusDisplay
        {
            get
            {
                return Installed ? string.Format("Active ({0})", Version) : "Not Installed";
            }
        }
        public bool HasBackups { get; set; }
        public bool HasLogs { get; set; }
        public bool HasMyFsr { get; set; }
        public bool IsReEngine { get; set; }

        public GameInfo()
        {
            Inputs = new List<string>();
            FsrTargets = new List<string>();
            Launcher = "Custom";
            Version = "1.7.0";
            OptiDllName = "dxgi.dll";
            UseFakeNvapi = true;
        }
    }

    public class CoreStatus
    {
        public string Version { get; set; }
        public string CoreDir { get; set; }
        public bool CoreExists { get; set; }
        public bool WeightsBuilt { get; set; }
        public long WeightsSize { get; set; }
        public long KernelsSize { get; set; }
        public bool HasPython { get; set; }
        public bool HasDxc { get; set; }
        public string PythonPath { get; set; }
        public string DxcPath { get; set; }
    }

    public class GpuInfo
    {
        public string Name { get; set; }
        public long RamMB { get; set; }
        public string Driver { get; set; }
    }
}
