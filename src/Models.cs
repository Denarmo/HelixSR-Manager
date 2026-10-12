using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

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
        public string FoundFfxFgPath { get; set; }
        public string FoundXeFgPath { get; set; }
        public string FoundXeLlPath { get; set; }
        public bool HasDlssG { get; set; }
        public string FgMode { get; set; } // "auto", "dlssg_xefg", "dlssg_fsrfg", "dlssg_nukems", "optifg_fsrfg"
        public string Route { get; set; } // "optiscaler", "direct" or "dlss" (experimental HelixSR DLSS loader)
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
                if (Route == "dlss") return "DLSS Loader (Experimental)";
                if (Route == "optiscaler")
                {
                    string baseStr = string.Format("OptiScaler ({0})", string.IsNullOrEmpty(OptiDllName) ? "dxgi.dll" : OptiDllName);
                    if (!string.IsNullOrEmpty(FgMode) && FgMode != "auto")
                    {
                        if (FgMode == "dlssg_xefg") baseStr += " + XeFG";
                        else if (FgMode == "dlssg_fsrfg") baseStr += " + FSR-FG";
                        else if (FgMode == "dlssg_nukems") baseStr += " + NukemFG";
                        else if (FgMode == "optifg_fsrfg") baseStr += " + OptiFG";
                    }
                    return baseStr;
                }
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
            Version = Engine.CoreVersion;
            Route = "optiscaler";
            OptiDllName = "dxgi.dll";
            UseFakeNvapi = true;
            FgMode = "auto";
        }
    }

    public class CoreStatus
    {
        public string Version { get; set; }
        public string CoreDir { get; set; }
        public bool CoreExists { get; set; }
        public bool WeightsBuilt { get; set; }
        public bool NetworkEmbedded { get; set; } // HelixSR 1.8+: network appended to amd_fidelityfx_dx12.dll
        public long WeightsSize { get; set; }
        public long KernelsSize { get; set; }
        public long DllSize { get; set; }
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

    public class HandheldEnvironmentInfo
    {
        public bool IsHandheldDetected { get; set; }
        public bool IsControllerDetected { get; set; }
        public bool IsXboxMode { get; set; }
        public bool IsSteamOS { get; set; }
        public bool IsBazzite { get; set; }
        public bool IsHandheldHardware { get; set; }
        public string DetectionReason { get; set; }
        public string DetectedDevice { get; set; }

        public HandheldEnvironmentInfo()
        {
            DetectionReason = string.Empty;
            DetectedDevice = string.Empty;
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct XINPUT_GAMEPAD
    {
        public ushort wButtons;
        public byte bLeftTrigger;
        public byte bRightTrigger;
        public short sThumbLX;
        public short sThumbLY;
        public short sThumbRX;
        public short sThumbRY;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct XINPUT_STATE
    {
        public uint dwPacketNumber;
        public XINPUT_GAMEPAD Gamepad;
    }

    public static class XInputButtons
    {
        public const ushort DPAD_UP = 0x0001;
        public const ushort DPAD_DOWN = 0x0002;
        public const ushort DPAD_LEFT = 0x0004;
        public const ushort DPAD_RIGHT = 0x0008;
        public const ushort START = 0x0010;
        public const ushort BACK = 0x0020;
        public const ushort LEFT_THUMB = 0x0040;
        public const ushort RIGHT_THUMB = 0x0080;
        public const ushort LEFT_SHOULDER = 0x0100;
        public const ushort RIGHT_SHOULDER = 0x0200;
        public const ushort A = 0x1000;
        public const ushort B = 0x2000;
        public const ushort X = 0x4000;
        public const ushort Y = 0x8000;
    }

    public static class XInputNative
    {
        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
        private static extern IntPtr LoadLibrary(string lpFileName);

        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
        private static extern IntPtr GetProcAddress(IntPtr hModule, string lpProcName);

        [UnmanagedFunctionPointer(CallingConvention.StdCall)]
        public delegate int XInputGetStateDelegate(int dwUserIndex, ref XINPUT_STATE pState);

        private static XInputGetStateDelegate _getState;
        private static bool _initialized = false;
        private static bool _available = false;

        public static bool IsAvailable
        {
            get
            {
                EnsureInitialized();
                return _available;
            }
        }

        private static void EnsureInitialized()
        {
            if (_initialized) return;
            _initialized = true;
            string[] dlls = new string[] { "xinput1_4.dll", "xinput9_1_0.dll", "xinput1_3.dll" };
            foreach (var dll in dlls)
            {
                try
                {
                    IntPtr hMod = LoadLibrary(dll);
                    if (hMod != IntPtr.Zero)
                    {
                        IntPtr proc = GetProcAddress(hMod, "XInputGetState");
                        if (proc != IntPtr.Zero)
                        {
                            _getState = (XInputGetStateDelegate)Marshal.GetDelegateForFunctionPointer(proc, typeof(XInputGetStateDelegate));
                            _available = true;
                            break;
                        }
                    }
                }
                catch { }
            }
        }

        public static int GetState(int userIndex, ref XINPUT_STATE state)
        {
            EnsureInitialized();
            if (_getState != null)
            {
                try
                {
                    return _getState(userIndex, ref state);
                }
                catch { }
            }
            return 1167; // ERROR_DEVICE_NOT_CONNECTED
        }

        public static bool IsAnyControllerConnected()
        {
            EnsureInitialized();
            if (!_available || _getState == null) return false;
            for (int i = 0; i < 4; i++)
            {
                XINPUT_STATE s = new XINPUT_STATE();
                if (GetState(i, ref s) == 0) return true;
            }
            return false;
        }
    }
}
