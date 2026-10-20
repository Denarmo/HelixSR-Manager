using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Diagnostics;
using Microsoft.Win32;
using System.Web.Script.Serialization;

namespace HelixSRSwapper
{
    public class Engine
    {
        /// <summary>HelixSR Manager release version (shown in the sidebar logo and window title).</summary>
        public const string AppVersion = "1.1.1";
        /// <summary>Bundled upstream HelixSR core version (helixsr_core/HelixSR-x.y.z).</summary>
        public const string CoreVersion = "1.8.1";

        public const string EmbeddedCoreResourceName = "HelixSR.Core.zip";
        private static readonly object CoreExtractLock = new object();
        private static string _resolvedCoreDir = null;

        public static string CoreDir
        {
            get
            {
                if (_resolvedCoreDir != null && Directory.Exists(_resolvedCoreDir))
                    return _resolvedCoreDir;

                lock (CoreExtractLock)
                {
                    if (_resolvedCoreDir != null && Directory.Exists(_resolvedCoreDir))
                        return _resolvedCoreDir;

                    string coreFolder = "HelixSR-" + CoreVersion;

                    // 1. Check local directory adjacent to the assembly
                    try
                    {
                        string asmDir = Path.GetDirectoryName(typeof(Engine).Assembly.Location);
                        if (!string.IsNullOrEmpty(asmDir))
                        {
                            string p1 = Path.Combine(asmDir, "helixsr_core", coreFolder);
                            if (Directory.Exists(p1) && File.Exists(Path.Combine(p1, DllFsr)))
                            {
                                _resolvedCoreDir = Path.GetFullPath(p1);
                                return _resolvedCoreDir;
                            }
                        }
                    }
                    catch { }

                    // 2. Check local directory in BaseDirectory
                    try
                    {
                        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
                        if (!string.IsNullOrEmpty(baseDir))
                        {
                            string p2 = Path.Combine(baseDir, "helixsr_core", coreFolder);
                            if (Directory.Exists(p2) && File.Exists(Path.Combine(p2, DllFsr)))
                            {
                                _resolvedCoreDir = Path.GetFullPath(p2);
                                return _resolvedCoreDir;
                            }
                        }
                    }
                    catch { }

                    // 3. Fall back to LocalAppData/HelixSR/core/HelixSR-1.8.1
                    string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                    string appDataCore = Path.Combine(localApp, "HelixSR", "core", coreFolder);

                    EnsureCoreExtracted(appDataCore);

                    _resolvedCoreDir = Path.GetFullPath(appDataCore);
                    return _resolvedCoreDir;
                }
            }
        }

        public static void EnsureCoreReady()
        {
            try
            {
                string ignored = CoreDir;
            }
            catch { }
        }

        private static bool IsCoreDirectoryComplete(string dir)
        {
            if (string.IsNullOrEmpty(dir) || !Directory.Exists(dir)) return false;
            string marker = Path.Combine(dir, ".extracted_" + CoreVersion + "_r2");
            if (!File.Exists(marker)) return false;
            if (!File.Exists(Path.Combine(dir, DllFsr))) return false;
            if (!File.Exists(Path.Combine(dir, "optiscaler", "OptiScaler.dll"))) return false;
            if (!File.Exists(Path.Combine(dir, "setup", "helixsr_setup.py"))) return false;
            if (!File.Exists(Path.Combine(dir, "helixsr-setup.ps1"))) return false;
            return true;
        }

        public static void EnsureCoreExtracted(string targetDir)
        {
            if (IsCoreDirectoryComplete(targetDir)) return;

            var asm = typeof(Engine).Assembly;
            using (var stream = asm.GetManifestResourceStream(EmbeddedCoreResourceName))
            {
                if (stream == null)
                {
                    if (!Directory.Exists(targetDir)) Directory.CreateDirectory(targetDir);
                    return;
                }

                if (!Directory.Exists(targetDir)) Directory.CreateDirectory(targetDir);

                using (var archive = new ZipArchive(stream, ZipArchiveMode.Read))
                {
                    foreach (var entry in archive.Entries)
                    {
                        if (string.IsNullOrEmpty(entry.Name) && (entry.FullName.EndsWith("/") || entry.FullName.EndsWith("\\")))
                        {
                            string dirPath = Path.Combine(targetDir, entry.FullName.Replace('/', Path.DirectorySeparatorChar));
                            if (!Directory.Exists(dirPath)) Directory.CreateDirectory(dirPath);
                            continue;
                        }

                        string destPath = Path.Combine(targetDir, entry.FullName.Replace('/', Path.DirectorySeparatorChar));
                        string destDir = Path.GetDirectoryName(destPath);
                        if (!string.IsNullOrEmpty(destDir) && !Directory.Exists(destDir))
                        {
                            Directory.CreateDirectory(destDir);
                        }

                        if (destPath.EndsWith(DllFsr, StringComparison.OrdinalIgnoreCase) && File.Exists(destPath) && HasEmbeddedNetwork(destPath))
                        {
                            // If user already compiled the network into amd_fidelityfx_dx12.dll, preserve it!
                            continue;
                        }

                        entry.ExtractToFile(destPath, true);
                    }
                }

                try
                {
                    string marker = Path.Combine(targetDir, ".extracted_" + CoreVersion + "_r2");
                    File.WriteAllText(marker, string.Format("HelixSR Core {0} extracted at {1} UTC", CoreVersion, DateTime.UtcNow.ToString("o")));
                }
                catch { }
            }
        }
        private const string DllFsr = "amd_fidelityfx_dx12.dll";
        private const string DllSr = "amd_fidelityfx_upscaler_dx12.dll";
        private static readonly string[] DllFiles = new string[] { DllSr, DllFsr };
        private const string OwnDll = "helixsr.dll";
        private const string OwnSrDll = "helixsr_upscaler.dll";
        private static readonly string[] NetworkFiles = new string[] { "helixsr_weights.bin", "helixsr_kernels.pak" };
        private const string HelixSrFolder = "HelixSR";
        private const string MarkerFile = "helixsr-install.json";
        private const string BackupFolder = "backup";
        private static readonly string[] OptiNames = new string[] { "dxgi.dll", "winmm.dll", "version.dll", "dbghelp.dll", "d3d12.dll", "wininet.dll", "winhttp.dll", "OptiScaler.asi" };
        private static readonly string[] OptiExtra = new string[] { "fakenvapi.dll", "fakenvapi.ini", "nvapi64.dll" };
        private const string AmdFsrFile = "amd_fidelityfx_upscaler_dx12.amd.dll";
        private const string AmdFgFile = "amd_fidelityfx_framegeneration_dx12.dll"; // bundled in core/amd-fsr since HelixSR 1.8.0
        private const string MyFsrFolder = "my-fsr";
        // Experimental route (HelixSR 1.8.1): HelixSR DLSS loader (dxgi.dll) + HelixSR as nvngx.dll next to the game's .exe
        private const string LoaderFolder = "dlss-loader";
        private const string LoaderDll = "dxgi.dll";
        private const string NvngxCoreDll = "nvngx.dll";
        // HelixSR 1.8.0+ setup appends the network to amd_fidelityfx_dx12.dll ("one-file DLL"); the last 32 bytes are
        // "HXSRNET1" + uint64 weights size + uint64 kernels size + uint64 reserved.
        private static readonly byte[] EmbedMagic = Encoding.ASCII.GetBytes("HXSRNET1");

        private const string MyFsrReadme = "Put an FSR upscaler DLL into this folder (for example FSR 4: amd_fidelityfx_upscaler_dx12.dll, any\r\nfile name) and start the game again. Only for this game.\r\n\r\nIn the game press Insert (OptiScaler's menu), then Upscaling tab > Upscalers > FFX Upscaler, and pick it there:\r\nit is listed by its version, for example \"FSR 4.1.1\". HelixSR stays the default (\"FSR HelixSR (3.1.5)\").\r\nFSR 4 is listed only if the DLL supports your GPU.\r\n\r\nTo go back: delete the DLL from this folder.\r\n";

        private static readonly Regex SkipExe = new Regex(@"unins|setup|redist|crash|launcher|vc_?redist|dxsetup|easyanticheat|beservice|dotnet|helper|report|prereq|install|7z|ue4prereq|cefprocess|webhelper", RegexOptions.IgnoreCase);

        private static readonly JavaScriptSerializer Json = new JavaScriptSerializer();

        public static bool IsRunningOnWineOrLinux()
        {
            if (Environment.OSVersion.Platform == PlatformID.Unix || Environment.OSVersion.Platform == PlatformID.MacOSX)
                return true;
            try
            {
                using (var k = Registry.CurrentUser.OpenSubKey(@"Software\Wine"))
                {
                    if (k != null) return true;
                }
            }
            catch { }
            return Directory.Exists(@"Z:\home") || Directory.Exists("/home");
        }

        /// <summary>
        /// Detects if a controller is connected or handheld mode requested, switching to Handheld Mode.
        /// </summary>
        public static HandheldEnvironmentInfo DetectHandheldEnvironment()
        {
            var info = new HandheldEnvironmentInfo();

            // 1. Explicit command line flags (--handheld, -handheld) or environment overrides
            try
            {
                string[] args = Environment.GetCommandLineArgs();
                if (args != null)
                {
                    foreach (var a in args)
                    {
                        if (string.Equals(a, "--handheld", StringComparison.OrdinalIgnoreCase) ||
                            string.Equals(a, "-handheld", StringComparison.OrdinalIgnoreCase))
                        {
                            info.IsHandheldDetected = true;
                            info.DetectionReason = "Command line parameter --handheld";
                            info.DetectedDevice = "Handheld Override";
                            return info;
                        }
                    }
                }
            }
            catch { }

            // 2. Controller detection (XInput)
            try
            {
                if (XInputNative.IsAnyControllerConnected())
                {
                    info.IsHandheldDetected = true;
                    info.IsControllerDetected = true;
                    info.DetectionReason = "Gamepad controller detected";
                    info.DetectedDevice = "Controller";
                    return info;
                }
            }
            catch { }

            return info;
        }

        /// <summary>
        /// Reads the trailer the HelixSR 1.8+ setup appends to amd_fidelityfx_dx12.dll. True when the DLL carries the network.
        /// </summary>
        public static bool TryReadEmbeddedNetwork(string dllPath, out long weightsSize, out long kernelsSize)
        {
            weightsSize = 0;
            kernelsSize = 0;
            try
            {
                if (string.IsNullOrEmpty(dllPath) || !File.Exists(dllPath)) return false;
                using (var fs = new FileStream(dllPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    if (fs.Length <= 32) return false;
                    fs.Seek(-32, SeekOrigin.End);
                    var tail = new byte[32];
                    int read = 0;
                    while (read < tail.Length)
                    {
                        int n = fs.Read(tail, read, tail.Length - read);
                        if (n <= 0) return false;
                        read += n;
                    }
                    for (int i = 0; i < EmbedMagic.Length; i++)
                    {
                        if (tail[i] != EmbedMagic[i]) return false;
                    }
                    weightsSize = BitConverter.ToInt64(tail, 8);
                    kernelsSize = BitConverter.ToInt64(tail, 16);
                    return true;
                }
            }
            catch
            {
                return false;
            }
        }

        public static bool HasEmbeddedNetwork(string dllPath)
        {
            long w, k;
            return TryReadEmbeddedNetwork(dllPath, out w, out k);
        }

        private static bool CoreHasSeparateNetworkFiles()
        {
            foreach (var n in NetworkFiles)
            {
                string p = Path.Combine(CoreDir, n);
                if (!File.Exists(p) || new FileInfo(p).Length == 0) return false;
            }
            return true;
        }

        /// <summary>
        /// Mirrors upstream copy_network(): the separate network files are only deployed when the core DLL does not carry
        /// the network (pre-1.8 builds); otherwise stale copies are removed (the DLL reads its own embedded copy first).
        /// </summary>
        private static void SyncNetworkFiles(string destDir)
        {
            if (string.IsNullOrEmpty(destDir) || !Directory.Exists(destDir)) return;
            bool embedded = HasEmbeddedNetwork(Path.Combine(CoreDir, DllFsr));
            foreach (var n in NetworkFiles)
            {
                string src = Path.Combine(CoreDir, n);
                string dst = Path.Combine(destDir, n);
                if (!embedded && File.Exists(src))
                {
                    File.Copy(src, dst, true);
                }
                else if (embedded && File.Exists(dst))
                {
                    try { File.Delete(dst); } catch { }
                }
            }
        }

        private static bool FileContainsAscii(string path, int maxBytes, Regex pattern)
        {
            try
            {
                if (!File.Exists(path)) return false;
                using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                {
                    int len = (int)Math.Min(fs.Length, maxBytes);
                    var buf = new byte[len];
                    int read = 0;
                    while (read < len)
                    {
                        int n = fs.Read(buf, read, len - read);
                        if (n <= 0) break;
                        read += n;
                    }
                    // Latin-1 maps every byte 1:1 to a char, so ASCII markers inside binaries survive the conversion
                    string text = Encoding.GetEncoding(28591).GetString(buf, 0, read);
                    return pattern.IsMatch(text);
                }
            }
            catch
            {
                return false;
            }
        }

        private static readonly Regex HelixSrVersionMarker = new Regex(@"HelixSR \d+\.\d+\.\d+");
        private static readonly Regex DlssLoaderMarker = new Regex(@"HelixSR DLSS loader");

        /// <summary>True when the file is a HelixSR DLL (same check as upstream helixsr_install.is_helixsr).</summary>
        private static bool IsHelixSrBinary(string path)
        {
            return FileContainsAscii(path, 4 << 20, HelixSrVersionMarker);
        }

        /// <summary>True when the file is HelixSR's DLSS loader (same check as upstream helixsr_install.is_loader).</summary>
        private static bool IsDlssLoaderBinary(string path)
        {
            return FileContainsAscii(path, 1 << 20, DlssLoaderMarker);
        }

        public static bool IsDlssLoaderAvailable()
        {
            return File.Exists(Path.Combine(CoreDir, LoaderFolder, LoaderDll));
        }

        /// <summary>Rewrites the "helixsr" version of an install record after the deployed DLL was refreshed.</summary>
        private static void UpdateMarkerVersion(string markerPath)
        {
            if (!File.Exists(markerPath)) return;
            try
            {
                var data = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(markerPath));
                if (data == null) return;
                data["helixsr"] = CoreVersion;
                File.WriteAllText(markerPath, Json.Serialize(data));
            }
            catch { }
        }

        public static string NormalizePath(string path)
        {
            if (string.IsNullOrEmpty(path)) return "";
            try
            {
                string cleaned = path.Replace('/', Path.DirectorySeparatorChar).Replace('\\', Path.DirectorySeparatorChar);
                return Path.GetFullPath(cleaned).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            }
            catch
            {
                return path.Replace('/', Path.DirectorySeparatorChar).Replace('\\', Path.DirectorySeparatorChar)
                    .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            }
        }

        private static void AddUniqueDir(List<string> list, HashSet<string> seen, string candidate)
        {
            if (string.IsNullOrEmpty(candidate)) return;
            string norm = NormalizePath(candidate);
            if (!string.IsNullOrEmpty(norm) && Directory.Exists(norm) && seen.Add(norm))
            {
                list.Add(norm);
            }
        }

        public static List<string> GetSteamRoots()
        {
            var roots = new List<string>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            try
            {
                using (var k = Registry.CurrentUser.OpenSubKey(@"Software\Valve\Steam"))
                {
                    if (k != null)
                    {
                        var p = k.GetValue("SteamPath") as string;
                        AddUniqueDir(roots, seen, p);
                    }
                }
            }
            catch { }

            AddUniqueDir(roots, seen, @"C:\Program Files (x86)\Steam");

            // Linux / SteamOS & Wine Z:\home discovery
            string home = Environment.GetEnvironmentVariable("HOME");
            var candidateHomes = new List<string>();
            if (!string.IsNullOrEmpty(home)) candidateHomes.Add(home);
            if (Directory.Exists("/home"))
            {
                try { candidateHomes.AddRange(Directory.GetDirectories("/home")); } catch { }
            }
            if (Directory.Exists(@"Z:\home"))
            {
                try { candidateHomes.AddRange(Directory.GetDirectories(@"Z:\home")); } catch { }
            }

            string[] relSteamPaths = new string[]
            {
                Path.Combine(".local", "share", "Steam"),
                Path.Combine(".steam", "steam"),
                Path.Combine(".steam", "root"),
                Path.Combine(".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")
            };

            foreach (var h in candidateHomes)
            {
                foreach (var rel in relSteamPaths)
                {
                    AddUniqueDir(roots, seen, Path.Combine(h, rel));
                }
            }

            // SteamOS SD Card / External media mounts (/run/media/mmcblk0p1 or /run/media/deck/*)
            string[] mediaRoots = new string[] { "/run/media", @"Z:\run\media" };
            foreach (var mr in mediaRoots)
            {
                if (!Directory.Exists(mr)) continue;
                try
                {
                    foreach (var d1 in Directory.EnumerateDirectories(mr))
                    {
                        if (Directory.Exists(Path.Combine(d1, "steamapps"))) AddUniqueDir(roots, seen, d1);
                        try
                        {
                            foreach (var d2 in Directory.EnumerateDirectories(d1))
                            {
                                if (Directory.Exists(Path.Combine(d2, "steamapps"))) AddUniqueDir(roots, seen, d2);
                            }
                        }
                        catch { }
                    }
                }
                catch { }
            }

            return roots;
        }

        public static List<string> GetSteamLibraries()
        {
            var libs = new List<string>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var root in GetSteamRoots())
            {
                AddUniqueDir(libs, seen, Path.Combine(root, "steamapps", "common"));

                string vdf = Path.Combine(root, "steamapps", "libraryfolders.vdf");
                if (File.Exists(vdf))
                {
                    try
                    {
                        string text = File.ReadAllText(vdf);
                        var matches = Regex.Matches(text, @"""path""\s+""([^""]+)""");
                        foreach (Match m in matches)
                        {
                            string p = m.Groups[1].Value.Replace(@"\\", @"\");
                            string common = Path.Combine(p, "steamapps", "common");
                            if (Directory.Exists(common))
                            {
                                AddUniqueDir(libs, seen, common);
                            }
                            else if (p.StartsWith("/") && Directory.Exists(@"Z:" + p.Replace('/', '\\')))
                            {
                                string wineCommon = Path.Combine(@"Z:" + p.Replace('/', '\\'), "steamapps", "common");
                                AddUniqueDir(libs, seen, wineCommon);
                            }
                        }
                    }
                    catch { }
                }
            }
            return libs;
        }

        public static Dictionary<string, ManifestInfo> GetSteamManifests()
        {
            var map = new Dictionary<string, ManifestInfo>(StringComparer.OrdinalIgnoreCase);
            foreach (var common in GetSteamLibraries())
            {
                string steamapps = Path.GetDirectoryName(common);
                if (!Directory.Exists(steamapps)) continue;

                try
                {
                    foreach (var file in Directory.GetFiles(steamapps, "appmanifest_*.acf"))
                    {
                        try
                        {
                            string content = File.ReadAllText(file);
                            var mAppId = Regex.Match(content, @"""appid""\s+""(\d+)""");
                            var mName = Regex.Match(content, @"""name""\s+""([^""]+)""");
                            var mInstallDir = Regex.Match(content, @"""installdir""\s+""([^""]+)""");

                            if (mAppId.Success && mName.Success && mInstallDir.Success)
                            {
                                string appid = mAppId.Groups[1].Value;
                                string name = mName.Groups[1].Value;
                                string dir = mInstallDir.Groups[1].Value;
                                map[dir] = new ManifestInfo { AppId = appid, Name = name, InstallDir = dir, LibraryRoot = Path.GetDirectoryName(steamapps) };
                            }
                        }
                        catch { }
                    }
                }
                catch { }
            }
            return map;
        }

        public class ManifestInfo
        {
            public string AppId { get; set; }
            public string Name { get; set; }
            public string InstallDir { get; set; }
            public string LibraryRoot { get; set; }
        }

        public static GameInfo ScanGame(string gameFolder, string fallbackName, Dictionary<string, ManifestInfo> manifests)
        {
            gameFolder = NormalizePath(gameFolder);
            string folderName = Path.GetFileName(gameFolder);
            ManifestInfo manifest = null;
            if (manifests != null && manifests.ContainsKey(folderName))
            {
                manifest = manifests[folderName];
            }

            var game = new GameInfo
            {
                Id = Convert.ToBase64String(Encoding.UTF8.GetBytes(gameFolder)).Replace("=", ""),
                Name = manifest != null ? manifest.Name : (fallbackName ?? folderName),
                Folder = gameFolder,
                AppId = manifest != null ? manifest.AppId : null,
                Launcher = manifest != null ? "Steam" : "Custom"
            };

            // Locate Cover Art
            LocateCoverArt(game);

            // Walk Game Directory up to depth 6
            ProcessGameDirectory(game, gameFolder);

            // Check if OptiScaler (or experimental DLSS loader) route is currently installed
            bool optiInstalled = false;
            bool dlssInstalled = false;
            CheckOptiScalerRoute(game, out optiInstalled, out dlssInstalled);

            // Check if Direct FSR 3.1 replacement route is currently installed
            bool directInstalled = CheckDirectRoute(game);

            if (dlssInstalled)
            {
                game.Route = "dlss";
                game.Installed = true;
            }
            else if (optiInstalled)
            {
                game.Route = "optiscaler";
                game.Installed = true;
            }
            else if (directInstalled)
            {
                game.Route = "direct";
                game.Installed = true;
            }
            else
            {
                // Default option is OptiScaler (dxgi.dll) instead of direct FSR replacement
                game.Route = "optiscaler";
                game.OptiDllName = "dxgi.dll";
            }

            return game;
        }

        private static void LocateCoverArt(GameInfo game)
        {
            if (!string.IsNullOrEmpty(game.AppId))
            {
                string foundCover = null;
                string foundHero = null;

                // Check local appcache in all discovered Steam roots
                foreach (var sRoot in GetSteamRoots())
                {
                    string candidateCover = Path.Combine(sRoot, "appcache", "librarycache", game.AppId, "library_600x900.jpg");
                    if (File.Exists(candidateCover)) { foundCover = candidateCover; }
                    else
                    {
                        string flatCover = Path.Combine(sRoot, "appcache", "librarycache", string.Format("{0}_library_600x900.jpg", game.AppId));
                        if (File.Exists(flatCover)) foundCover = flatCover;
                    }

                    string candidateHero = Path.Combine(sRoot, "appcache", "librarycache", game.AppId, "library_hero.jpg");
                    if (File.Exists(candidateHero)) { foundHero = candidateHero; }
                    else
                    {
                        string flatHero = Path.Combine(sRoot, "appcache", "librarycache", string.Format("{0}_library_hero.jpg", game.AppId));
                        if (File.Exists(flatHero)) foundHero = flatHero;
                    }

                    if (foundCover != null && foundHero != null) break;
                }

                // Check HelixSR local cache
                string cacheDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HelixSR", "cache", "covers");
                string cachedCover = Path.Combine(cacheDir, string.Format("{0}_600x900.jpg", game.AppId));
                if (foundCover == null && File.Exists(cachedCover))
                {
                    foundCover = cachedCover;
                }

                string cachedHero = Path.Combine(cacheDir, string.Format("{0}_hero.jpg", game.AppId));
                if (foundHero == null && File.Exists(cachedHero))
                {
                    foundHero = cachedHero;
                }

                game.LocalCoverPath = foundCover;
                game.RemoteCoverUrl = string.Format("https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{0}/library_600x900.jpg", game.AppId);

                game.LocalHeroPath = foundHero;
                game.RemoteHeroUrl = string.Format("https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{0}/library_hero.jpg", game.AppId);
            }
        }

        private static void ProcessGameDirectory(GameInfo game, string gameFolder)
        {
            var detectedInputs = new HashSet<string>();
            var fsrTargets = new List<string>();
            string bestExeDir = null;
            long bestExeSize = -1;
            string bestExeName = null;

            ScanDirRecursive(gameFolder, 0, 6, detectedInputs, fsrTargets, ref bestExeDir, ref bestExeSize, ref bestExeName, ref game);

            if (bestExeDir == null && !string.IsNullOrEmpty(game.FoundNvngxDlssPath))
            {
                bestExeDir = Path.GetDirectoryName(game.FoundNvngxDlssPath);
            }

            if (bestExeDir != null && string.Equals(Path.GetFileName(bestExeDir), "_storage_", StringComparison.OrdinalIgnoreCase))
            {
                // In Capcom RE Engine / REFramework, _storage_ is an engine directory; game executable lives in parent
                bestExeDir = gameFolder;
            }

            game.ExeFolder = bestExeDir ?? gameFolder;
            game.ExeName = bestExeName;
            game.Inputs = new List<string>(detectedInputs);
            game.FsrTargets = fsrTargets;
            game.IsReEngine = DetectReEngine(gameFolder, game);
            game.IsInZoi = DetectInZoi(gameFolder, game);
            DetectUnity(game);
            game.InstallReFramework = game.IsReEngine || File.Exists(Path.Combine(game.ExeFolder ?? gameFolder, "reframework_revision.txt"));
        }

        private static void CheckOptiScalerRoute(GameInfo game, out bool optiInstalled, out bool dlssInstalled)
        {
            optiInstalled = false;
            dlssInstalled = false;
            if (!string.IsNullOrEmpty(game.ExeFolder))
            {
                string helixDir = Path.Combine(game.ExeFolder, HelixSrFolder);
                string marker = Path.Combine(helixDir, MarkerFile);
                if (File.Exists(marker))
                {
                    optiInstalled = true;
                    try
                    {
                        var data = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(marker));
                        if (data != null)
                        {
                            if (data.ContainsKey("helixsr")) game.Version = data["helixsr"].ToString();
                            if (data.ContainsKey("optiscaler")) game.OptiDllName = data["optiscaler"].ToString();
                            if (data.ContainsKey("fakenvapi") && data["fakenvapi"] is bool) game.UseFakeNvapi = (bool)data["fakenvapi"];
                            if (data.ContainsKey("fg_mode") && data["fg_mode"] != null) game.FgMode = data["fg_mode"].ToString();
                            if (data.ContainsKey("route") && data["route"] != null && data["route"].ToString() == "dlss")
                            {
                                dlssInstalled = true;
                                optiInstalled = false;
                            }
                        }
                    }
                    catch { }
                }

                string backupDir = Path.Combine(helixDir, BackupFolder);
                if (Directory.Exists(backupDir) && Directory.GetFiles(backupDir).Length > 0) game.HasBackups = true;
                if (File.Exists(Path.Combine(helixDir, "helixsr.log")) || File.Exists(Path.Combine(game.ExeFolder, "OptiScaler.log"))
                    || File.Exists(Path.Combine(game.ExeFolder, "helixsr.log")) || File.Exists(Path.Combine(game.ExeFolder, "helixsr_loader.log"))) game.HasLogs = true;
                if (Directory.Exists(Path.Combine(helixDir, MyFsrFolder))) game.HasMyFsr = true;
            }
        }

        private static bool CheckDirectRoute(GameInfo game)
        {
            bool directInstalled = false;
            foreach (var target in game.FsrTargets)
            {
                string orig = Path.ChangeExtension(target, ".original.dll");
                string marker = Path.Combine(Path.GetDirectoryName(target), MarkerFile);
                if (File.Exists(orig) || File.Exists(marker))
                {
                    directInstalled = true;
                    game.HasBackups = game.HasBackups || File.Exists(orig);
                    if (File.Exists(marker))
                    {
                        try
                        {
                            var data = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(marker));
                            if (data != null && data.ContainsKey("helixsr")) game.Version = data["helixsr"].ToString();
                        }
                        catch { }
                    }
                    if (File.Exists(Path.Combine(Path.GetDirectoryName(target), "helixsr.log"))) game.HasLogs = true;
                }
            }

            if (!directInstalled && !string.IsNullOrEmpty(game.ExeFolder))
            {
                string exeMarker = Path.Combine(game.ExeFolder, MarkerFile);
                if (File.Exists(exeMarker))
                {
                    directInstalled = true;
                    try
                    {
                        var data = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(exeMarker));
                        if (data != null && data.ContainsKey("helixsr")) game.Version = data["helixsr"].ToString();
                    }
                    catch { }
                }
            }
            return directInstalled;
        }

        private static void ScanDirRecursive(string dir, int depth, int maxDepth, HashSet<string> inputs, List<string> fsrTargets, ref string bestExeDir, ref long bestExeSize, ref string bestExeName, ref GameInfo game)
        {
            if (depth > maxDepth || !Directory.Exists(dir)) return;

            try
            {
                string[] files = Directory.GetFiles(dir);

                bool hasOptiMarker = false;
                foreach (var f in files)
                {
                    string fname = Path.GetFileName(f);
                    if (string.Equals(fname, "OptiScaler.ini", StringComparison.OrdinalIgnoreCase))
                    {
                        hasOptiMarker = true;
                        bestExeDir = dir;
                        bestExeSize = long.MaxValue / 2;
                    }
                }
                // A folder that already has a HelixSR install record (OptiScaler or DLSS loader route) wins, as upstream
                if (!hasOptiMarker && File.Exists(Path.Combine(dir, HelixSrFolder, MarkerFile)))
                {
                    hasOptiMarker = true;
                    bestExeDir = dir;
                    bestExeSize = long.MaxValue / 2;
                }

                foreach (var f in files)
                {
                    string fname = Path.GetFileName(f);
                    string lower = fname.ToLowerInvariant();

                    if (lower == "nvngx_dlss.dll")
                    {
                        inputs.Add("DLSS");
                        try
                        {
                            if (string.IsNullOrEmpty(game.FoundNvngxDlssPath))
                            {
                                game.FoundNvngxDlssPath = f;
                            }
                            else
                            {
                                // Prefer the larger DLSS DLL if multiple exist in the game directory (e.g. root game vs SP/MP subfolder)
                                var fiNew = new FileInfo(f);
                                var fiOld = new FileInfo(game.FoundNvngxDlssPath);
                                if (fiNew.Length > fiOld.Length)
                                {
                                    game.FoundNvngxDlssPath = f;
                                }
                            }
                        }
                        catch
                        {
                            if (string.IsNullOrEmpty(game.FoundNvngxDlssPath)) game.FoundNvngxDlssPath = f;
                        }
                    }
                    else if (lower == "nvngx_dlssg.dll" || lower == "sl.dlss_g.dll")
                    {
                        inputs.Add("DLSS-G");
                        game.HasDlssG = true;
                    }
                    else if (lower == "libxess.dll")
                    {
                        inputs.Add("XeSS");
                    }
                    else if (lower == "libxess_fg.dll")
                    {
                        game.FoundXeFgPath = f;
                    }
                    else if (lower == "libxell.dll")
                    {
                        game.FoundXeLlPath = f;
                    }
                    else if (lower == "amd_fidelityfx_framegeneration_dx12.dll")
                    {
                        game.FoundFfxFgPath = f;
                    }
                    else if (lower == "ffx_fsr2_api_x64.dll" || lower == "ffx_fsr2_api_dx12_x64.dll")
                    {
                        inputs.Add("FSR 2");
                    }
                    else if (lower == DllSr.ToLowerInvariant() || lower == DllFsr.ToLowerInvariant())
                    {
                        fsrTargets.Add(f);
                    }

                    if (lower.EndsWith(".exe") && !SkipExe.IsMatch(fname))
                    {
                        try
                        {
                            long sz = new FileInfo(f).Length;
                            if (lower.EndsWith("-win64-shipping.exe")) sz += 1000000000000L;
                            if (!hasOptiMarker && sz > bestExeSize)
                            {
                                bestExeSize = sz;
                                bestExeDir = dir;
                                bestExeName = fname;
                            }
                        }
                        catch { }
                    }
                }

                if (depth < maxDepth)
                {
                    foreach (var d in Directory.EnumerateDirectories(dir))
                    {
                        string dname = Path.GetFileName(d);
                        if (!string.Equals(dname, HelixSrFolder, StringComparison.OrdinalIgnoreCase))
                        {
                            ScanDirRecursive(d, depth + 1, maxDepth, inputs, fsrTargets, ref bestExeDir, ref bestExeSize, ref bestExeName, ref game);
                        }
                    }
                }
            }
            catch { }
        }

        public static List<GameInfo> ScanAllGames(List<string> customFolders)
        {
            var manifests = GetSteamManifests();
            var libs = GetSteamLibraries();
            var result = new List<GameInfo>();
            var scanned = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            foreach (var lib in libs)
            {
                string normLib = NormalizePath(lib);
                if (string.IsNullOrEmpty(normLib) || !Directory.Exists(normLib)) continue;
                try
                {
                    foreach (var dir in Directory.EnumerateDirectories(normLib))
                    {
                        string normDir = NormalizePath(dir);
                        if (string.IsNullOrEmpty(normDir) || !scanned.Add(normDir)) continue;

                        var g = ScanGame(normDir, Path.GetFileName(normDir), manifests);
                        if (!string.IsNullOrEmpty(g.ExeFolder))
                        {
                            scanned.Add(NormalizePath(g.ExeFolder));
                        }
                        if (!string.IsNullOrEmpty(g.Route))
                        {
                            result.Add(g);
                        }
                    }
                }
                catch { }
            }

            if (customFolders != null)
            {
                foreach (var folder in customFolders)
                {
                    string normFolder = NormalizePath(folder);
                    if (!string.IsNullOrEmpty(normFolder) && Directory.Exists(normFolder) && scanned.Add(normFolder))
                    {
                        var g = ScanGame(normFolder, Path.GetFileName(normFolder), manifests);
                        if (!string.IsNullOrEmpty(g.ExeFolder) && !string.Equals(NormalizePath(g.ExeFolder), normFolder, StringComparison.OrdinalIgnoreCase))
                        {
                            if (!scanned.Add(NormalizePath(g.ExeFolder)))
                            {
                                continue;
                            }
                        }
                        if (!string.IsNullOrEmpty(g.Route))
                        {
                            result.Add(g);
                        }
                    }
                }
            }

            result.Sort(delegate(GameInfo a, GameInfo b) { return string.Compare(a.Name, b.Name, StringComparison.OrdinalIgnoreCase); });
            return result;
        }

        public static CoreStatus GetCoreStatus()
        {
            bool coreExists = Directory.Exists(CoreDir);
            string dllPath = Path.Combine(CoreDir, DllFsr);
            string wPath = Path.Combine(CoreDir, "helixsr_weights.bin");
            string kPath = Path.Combine(CoreDir, "helixsr_kernels.pak");

            // HelixSR 1.8+: the setup embeds the network into the core DLL (one-file DLL)
            long embW, embK;
            bool embedded = TryReadEmbeddedNetwork(dllPath, out embW, out embK);
            // Older setups (<= 1.7) left two separate files next to the DLL
            bool separate = CoreHasSeparateNetworkFiles();

            string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string pyExe = Path.Combine(localApp, "HelixSR", "python", "python.exe");
            string dxcExe = Path.Combine(localApp, "HelixSR", "dxc", "dxc.exe");

            return new CoreStatus
            {
                Version = CoreVersion,
                CoreDir = CoreDir,
                CoreExists = coreExists,
                WeightsBuilt = embedded || separate,
                NetworkEmbedded = embedded,
                WeightsSize = embedded ? embW : (separate ? new FileInfo(wPath).Length : 0),
                KernelsSize = embedded ? embK : (separate ? new FileInfo(kPath).Length : 0),
                DllSize = File.Exists(dllPath) ? new FileInfo(dllPath).Length : 0,
                HasPython = File.Exists(pyExe),
                HasDxc = File.Exists(dxcExe),
                PythonPath = pyExe,
                DxcPath = dxcExe
            };
        }

        public static void InstallHelixSR(GameInfo game)
        {
            if (!Directory.Exists(CoreDir))
                throw new InvalidOperationException(string.Format("HelixSR core folder missing at: {0}", CoreDir));

            var coreStatus = GetCoreStatus();
            if (!coreStatus.WeightsBuilt)
                throw new InvalidOperationException("The HelixSR network has not been built yet.\nPlease go to the 'Engine & Weights' tab and click 'Build HelixSR Network' first (HelixSR 1.8+ embeds the network into amd_fidelityfx_dx12.dll).");

            // Clean up any previous installation artifacts first so switching routes or proxy DLL names is 100% clean
            CleanupHelixSRFiles(game);

            if (game.Route == "optiscaler")
            {
                string t = game.ExeFolder ?? game.Folder;
                if (!Directory.Exists(t)) throw new DirectoryNotFoundException("Game executable directory not found.");

                string helixDir = Path.Combine(t, HelixSrFolder);
                string backupDir = Path.Combine(helixDir, BackupFolder);
                string markerPath = Path.Combine(helixDir, MarkerFile);

                Directory.CreateDirectory(helixDir);
                Directory.CreateDirectory(backupDir);

                var rec = new Dictionary<string, object>();
                var movedList = new List<string>();
                var createdList = new List<string>();

                string optiName = !string.IsNullOrEmpty(game.OptiDllName) ? game.OptiDllName : "dxgi.dll";
                string fgMode = !string.IsNullOrEmpty(game.FgMode) ? game.FgMode : "auto";
                if (fgMode.StartsWith("dlssg_")) game.UseFakeNvapi = true;

                rec["optiscaler"] = optiName;
                rec["fakenvapi"] = game.UseFakeNvapi;
                rec["fg_mode"] = fgMode;

                // Backup existing wrapper DLL if present
                string currentTarget = Path.Combine(t, optiName);
                if (File.Exists(currentTarget))
                {
                    string backupTarget = Path.Combine(backupDir, optiName);
                    if (!File.Exists(backupTarget))
                    {
                        File.Copy(currentTarget, backupTarget, true);
                        movedList.Add(optiName);
                    }
                }

                // Backup OptiScaler.ini if game already had one
                string gameIni = Path.Combine(t, "OptiScaler.ini");
                string srcIni = Path.Combine(CoreDir, "optiscaler", "OptiScaler.ini");
                if (File.Exists(gameIni))
                {
                    string backupIni = Path.Combine(backupDir, "OptiScaler.ini");
                    if (!File.Exists(backupIni))
                    {
                        File.Copy(gameIni, backupIni, true);
                    }
                    rec["ini"] = "edited";
                }
                else if (File.Exists(srcIni))
                {
                    File.Copy(srcIni, gameIni, true);
                    rec["ini"] = "created";
                }

                // Ensure no stray fake nvapi64.dll is hijacking the graphics driver on Nvidia systems
                string strayNvapi = Path.Combine(t, "nvapi64.dll");
                if (File.Exists(strayNvapi)) { try { File.Delete(strayNvapi); } catch { } }

                // Deploy fakenvapi.dll and fakenvapi.ini if enabled (for AMD/Intel GPUs via OptiScaler)
                string dstFakenvapi = Path.Combine(t, "fakenvapi.dll");
                string dstFakenvapiIni = Path.Combine(t, "fakenvapi.ini");
                if (game.UseFakeNvapi)
                {
                    string srcFakenvapi = Path.Combine(CoreDir, "optiscaler", "fakenvapi.dll");
                    string srcFakenvapiIni = Path.Combine(CoreDir, "optiscaler", "fakenvapi.ini");

                    if (File.Exists(srcFakenvapi))
                    {
                        if (!File.Exists(dstFakenvapi)) createdList.Add("fakenvapi.dll");
                        File.Copy(srcFakenvapi, dstFakenvapi, true);
                    }

                    if (File.Exists(srcFakenvapiIni))
                    {
                        if (!File.Exists(dstFakenvapiIni)) createdList.Add("fakenvapi.ini");
                        File.Copy(srcFakenvapiIni, dstFakenvapiIni, true);
                    }
                }
                else
                {
                    if (File.Exists(dstFakenvapi)) { try { File.Delete(dstFakenvapi); } catch { } }
                    if (File.Exists(dstFakenvapiIni)) { try { File.Delete(dstFakenvapiIni); } catch { } }
                }

                // Copy OptiScaler.dll as the selected opti wrapper
                string srcOptiDll = Path.Combine(CoreDir, "optiscaler", "OptiScaler.dll");
                if (File.Exists(srcOptiDll))
                {
                    File.Copy(srcOptiDll, currentTarget, true);
                }

                // Copy HelixSR DLLs (helixsr.dll & helixsr_upscaler.dll)
                string srcFfxDll = Path.Combine(CoreDir, DllFsr);
                if (File.Exists(srcFfxDll))
                {
                    File.Copy(srcFfxDll, Path.Combine(helixDir, OwnDll), true);
                    File.Copy(srcFfxDll, Path.Combine(helixDir, OwnSrDll), true);
                }

                // Separate network files only for pre-1.8 builds (1.8+ carries the network inside the DLL)
                SyncNetworkFiles(helixDir);

                // Create my-fsr folder
                string myFsrDir = Path.Combine(helixDir, MyFsrFolder);
                Directory.CreateDirectory(myFsrDir);
                File.WriteAllText(Path.Combine(myFsrDir, "README.txt"), MyFsrReadme);

                // Copy AMD fallback FSR
                string srcAmdFsr = Path.Combine(CoreDir, "amd-fsr", DllSr);
                if (File.Exists(srcAmdFsr))
                {
                    File.Copy(srcAmdFsr, Path.Combine(helixDir, AmdFsrFile), true);
                }

                // Copy optional Frame Generation DLLs from Core my-fsr or Game my-fsr if present
                string coreMyFsr = Path.Combine(CoreDir, MyFsrFolder);
                string[] fgOptFiles = new string[] { AmdFgFile, "libxess_fg.dll", "libxell.dll" };
                foreach (var fgFile in fgOptFiles)
                {
                    string srcCoreFg = Path.Combine(coreMyFsr, fgFile);
                    string srcGameFg = Path.Combine(myFsrDir, fgFile);
                    string dstHelixFg = Path.Combine(helixDir, fgFile);
                    if (File.Exists(srcGameFg)) File.Copy(srcGameFg, dstHelixFg, true);
                    else if (File.Exists(srcCoreFg)) File.Copy(srcCoreFg, dstHelixFg, true);
                }

                // HelixSR 1.8+ ships AMD's FSR frame generation (core/amd-fsr): use it when no custom FG DLL was provided
                string bundledFg = Path.Combine(CoreDir, "amd-fsr", AmdFgFile);
                string helixFg = Path.Combine(helixDir, AmdFgFile);
                if (!File.Exists(helixFg) && File.Exists(bundledFg))
                {
                    File.Copy(bundledFg, helixFg, true);
                }

                // Copy dlssg_to_fsr3_amd_is_better.dll next to game exe if present in my-fsr
                string nukemName = "dlssg_to_fsr3_amd_is_better.dll";
                string srcNukemGame = Path.Combine(myFsrDir, nukemName);
                string srcNukemCore = Path.Combine(coreMyFsr, nukemName);
                string dstNukem = Path.Combine(t, nukemName);
                if (File.Exists(srcNukemGame) || File.Exists(srcNukemCore))
                {
                    if (!File.Exists(dstNukem)) createdList.Add(nukemName);
                    File.Copy(File.Exists(srcNukemGame) ? srcNukemGame : srcNukemCore, dstNukem, true);
                }

                // Mirror HelixSR files to _storage_ subfolder if game uses Capcom RE Engine / REFramework
                string subStorage = Path.Combine(t, "_storage_");
                if (Directory.Exists(subStorage))
                {
                    string subHelix = Path.Combine(subStorage, HelixSrFolder);
                    Directory.CreateDirectory(subHelix);
                    if (File.Exists(srcFfxDll))
                    {
                        File.Copy(srcFfxDll, Path.Combine(subHelix, OwnDll), true);
                        File.Copy(srcFfxDll, Path.Combine(subHelix, OwnSrDll), true);
                    }
                    SyncNetworkFiles(subHelix);
                }

                // Clear any broken/corrupted shader caches from previous crashes so game compiles fresh clean shaders
                ClearShaderCache(game);

                // Configure OptiScaler.ini with official HelixSR backend & Frame Generation settings
                if (File.Exists(gameIni))
                {
                    string text = File.ReadAllText(gameIni);
                    text = SetIniValue(text, "Dx12Upscaler", "fsr31", "Upscalers");
                    text = SetIniValue(text, "FfxDx12Path", Path.Combine(helixDir, OwnDll), "Libraries");
                    text = SetIniValue(text, "FfxDx12SRPath", Path.Combine(helixDir, OwnSrDll), "Libraries");

                    // Decouple FfxDx12FGPath from HelixSR SR-only DLL so FidelityFX Frame Generation works simultaneously
                    string ffxFgHelix = Path.Combine(helixDir, "amd_fidelityfx_framegeneration_dx12.dll");
                    if (File.Exists(ffxFgHelix))
                        text = SetIniValue(text, "FfxDx12FGPath", ffxFgHelix, "Libraries");
                    else if (!string.IsNullOrEmpty(game.FoundFfxFgPath) && File.Exists(game.FoundFfxFgPath))
                        text = SetIniValue(text, "FfxDx12FGPath", game.FoundFfxFgPath, "Libraries");

                    string xeFgHelix = Path.Combine(helixDir, "libxess_fg.dll");
                    if (File.Exists(xeFgHelix))
                        text = SetIniValue(text, "XeFGPath", xeFgHelix, "Libraries");
                    else if (!string.IsNullOrEmpty(game.FoundXeFgPath) && File.Exists(game.FoundXeFgPath))
                        text = SetIniValue(text, "XeFGPath", game.FoundXeFgPath, "Libraries");

                    string xeLlHelix = Path.Combine(helixDir, "libxell.dll");
                    if (File.Exists(xeLlHelix))
                        text = SetIniValue(text, "XeLLPath", xeLlHelix, "Libraries");
                    else if (!string.IsNullOrEmpty(game.FoundXeLlPath) && File.Exists(game.FoundXeLlPath))
                        text = SetIniValue(text, "XeLLPath", game.FoundXeLlPath, "Libraries");

                    if (fgMode == "dlssg_xefg")
                    {
                        text = SetIniValue(text, "Enabled", "true", "FrameGen");
                        text = SetIniValue(text, "FGInput", "dlssg", "FrameGen");
                        text = SetIniValue(text, "FGOutput", "xefg", "FrameGen");
                    }
                    else if (fgMode == "dlssg_fsrfg")
                    {
                        text = SetIniValue(text, "Enabled", "true", "FrameGen");
                        text = SetIniValue(text, "FGInput", "dlssg", "FrameGen");
                        text = SetIniValue(text, "FGOutput", "fsrfg", "FrameGen");
                    }
                    else if (fgMode == "dlssg_nukems")
                    {
                        text = SetIniValue(text, "Enabled", "true", "FrameGen");
                        text = SetIniValue(text, "FGInput", "nukems", "FrameGen");
                        text = SetIniValue(text, "FGOutput", "nukems", "FrameGen");
                    }
                    else if (fgMode == "optifg_fsrfg")
                    {
                        text = SetIniValue(text, "Enabled", "true", "FrameGen");
                        text = SetIniValue(text, "FGInput", "upscaler", "FrameGen");
                        text = SetIniValue(text, "FGOutput", "fsrfg", "FrameGen");
                        text = SetIniValue(text, "HUDFix", "true", "OptiFG");
                    }
                    else
                    {
                        text = SetIniValue(text, "Enabled", "auto", "FrameGen");
                        text = SetIniValue(text, "FGInput", "auto", "FrameGen");
                        text = SetIniValue(text, "FGOutput", "auto", "FrameGen");
                    }

                    // Everything above is preconfigured, so keep OptiScaler quiet in-game: no startup splash and no
                    // "Update available" popup (the bundled OptiScaler is never the newest). Insert still opens the menu.
                    text = SetIniValue(text, "DisableSplash", "true", "Menu");
                    text = SetIniValue(text, "CheckForUpdate", "false", "Hotfix");

                    if (game.IsInZoi) text = ApplyInZoiOptiScalerIni(text);

                    File.WriteAllText(gameIni, text);
                }

                rec["moved"] = movedList;
                rec["created"] = createdList;
                rec["helixsr"] = CoreVersion;
                rec["route"] = "optiscaler";

                File.WriteAllText(markerPath, Json.Serialize(rec));
            }
            else if (game.Route == "direct")
            {
                string t = game.ExeFolder ?? game.Folder;
                string srcFfx = Path.Combine(CoreDir, DllFsr);

                if (game.FsrTargets != null && game.FsrTargets.Count > 0)
                {
                    foreach (var target in game.FsrTargets)
                    {
                        string orig = Path.ChangeExtension(target, ".original.dll");
                        if (File.Exists(target) && !File.Exists(orig))
                        {
                            File.Move(target, orig);
                        }
                        File.Copy(srcFfx, target, true);

                        SyncNetworkFiles(Path.GetDirectoryName(target));

                        string marker = Path.Combine(Path.GetDirectoryName(target), MarkerFile);
                        var rec = new Dictionary<string, object>
                        {
                            { "helixsr", CoreVersion },
                            { "files", new List<string> { Path.GetFileName(target) } },
                            { "route", "direct" }
                        };
                        File.WriteAllText(marker, Json.Serialize(rec));
                    }
                }
                else if (!string.IsNullOrEmpty(t) && Directory.Exists(t))
                {
                    // Standalone direct DLL drop into executable directory
                    var createdDlls = new List<string>();
                    foreach (var dllName in DllFiles)
                    {
                        string dst = Path.Combine(t, dllName);
                        string orig = Path.ChangeExtension(dst, ".original.dll");
                        if (File.Exists(dst) && !File.Exists(orig))
                        {
                            File.Move(dst, orig);
                        }
                        else if (!File.Exists(dst))
                        {
                            createdDlls.Add(dllName);
                        }
                        File.Copy(srcFfx, dst, true);
                    }

                    SyncNetworkFiles(t);

                    string marker = Path.Combine(t, MarkerFile);
                    var rec = new Dictionary<string, object>
                    {
                        { "helixsr", CoreVersion },
                        { "route", "direct" },
                        { "created_dlls", createdDlls }
                    };
                    File.WriteAllText(marker, Json.Serialize(rec));
                }

                // Clear broken shader cache
                ClearShaderCache(game);

                // Sanitize Capcom RE Engine config.ini if present (reset stale foreign GPU adapter locks and DLSS reflex)
                SanitizeGameConfig(game);
            }
            else if (game.Route == "dlss")
            {
                // EXPERIMENTAL (HelixSR 1.8.1): HelixSR's DLSS loader as dxgi.dll + HelixSR (one-file DLL) as nvngx.dll next
                // to the game's .exe; the game's own DLSS option then runs HelixSR, without OptiScaler.
                string t = game.ExeFolder ?? game.Folder;
                if (!Directory.Exists(t)) throw new DirectoryNotFoundException("Game executable directory not found.");
                string srcLoader = Path.Combine(CoreDir, LoaderFolder, LoaderDll);
                if (!File.Exists(srcLoader))
                    throw new FileNotFoundException(string.Format("HelixSR DLSS loader missing at: {0}", srcLoader));

                string helixDir = Path.Combine(t, HelixSrFolder);
                string backupDir = Path.Combine(helixDir, BackupFolder);
                string markerPath = Path.Combine(helixDir, MarkerFile);
                Directory.CreateDirectory(backupDir);

                var movedList = new List<string>();
                foreach (var name in new string[] { LoaderDll, NvngxCoreDll })
                {
                    string cur = Path.Combine(t, name);
                    bool ours = name == LoaderDll ? IsDlssLoaderBinary(cur) : IsHelixSrBinary(cur);
                    if (File.Exists(cur) && !ours)
                    {
                        string bak = Path.Combine(backupDir, name);
                        if (File.Exists(bak)) File.Delete(bak);
                        File.Move(cur, bak);
                        movedList.Add(name);
                    }
                }

                File.Copy(srcLoader, Path.Combine(t, LoaderDll), true);
                File.Copy(Path.Combine(CoreDir, DllFsr), Path.Combine(t, NvngxCoreDll), true);
                SyncNetworkFiles(t);

                var rec = new Dictionary<string, object>
                {
                    { "helixsr", CoreVersion },
                    { "route", "dlss" },
                    { "files", new List<string> { LoaderDll, NvngxCoreDll } },
                    { "moved", movedList },
                    { "created", new List<string>() }
                };
                File.WriteAllText(markerPath, Json.Serialize(rec));

                ClearShaderCache(game);
            }

            if (game.IsInZoi)
            {
                ApplyInZoiUserSettings(game);
            }

            if (game.InstallReFramework)
            {
                InstallReFrameworkNightly(game);
            }
            else if (File.Exists(Path.Combine(game.ExeFolder ?? game.Folder, "reframework_revision.txt")))
            {
                UninstallReFramework(game);
            }
        }

        private static void CleanupHelixSRFiles(GameInfo game)
        {
            if (game == null) return;

            // inZOI: put back the game's own upscaler settings (install applies them again)
            if (game.IsInZoi) RestoreInZoiUserSettings();

            // 1. Clean up OptiScaler route artifacts if present
            if (!string.IsNullOrEmpty(game.ExeFolder) && Directory.Exists(game.ExeFolder))
            {
                string t = game.ExeFolder;
                string helixDir = Path.Combine(t, HelixSrFolder);
                string markerPath = Path.Combine(helixDir, MarkerFile);
                string backupDir = Path.Combine(helixDir, BackupFolder);

                if (File.Exists(markerPath) || Directory.Exists(helixDir))
                {
                    string opti = "dxgi.dll";
                    string route = "";
                    var moved = new List<string>();
                    var created = new List<string>();
                    string iniMode = "";

                    if (File.Exists(markerPath))
                    {
                        try
                        {
                            var data = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(markerPath));
                            if (data != null)
                            {
                                if (data.ContainsKey("optiscaler")) opti = data["optiscaler"].ToString();
                                if (data.ContainsKey("route") && data["route"] != null) route = data["route"].ToString();
                                if (data.ContainsKey("ini")) iniMode = data["ini"].ToString();
                                if (data.ContainsKey("moved"))
                                {
                                    var list = data["moved"] as System.Collections.ArrayList;
                                    if (list != null) foreach (var item in list) moved.Add(item.ToString());
                                }
                                if (data.ContainsKey("created"))
                                {
                                    var list = data["created"] as System.Collections.ArrayList;
                                    if (list != null) foreach (var item in list) created.Add(item.ToString());
                                }
                            }
                        }
                        catch { }
                    }

                    if (route == "dlss")
                    {
                        // Experimental DLSS loader route: dxgi.dll (loader) + nvngx.dll (HelixSR) next to the .exe
                        opti = LoaderDll;
                        string coreCopy = Path.Combine(t, NvngxCoreDll);
                        if (File.Exists(coreCopy) && IsHelixSrBinary(coreCopy)) { try { File.Delete(coreCopy); } catch { } }
                        foreach (var extra in new string[] { "helixsr.log", "helixsr_loader.log" })
                        {
                            string ep = Path.Combine(t, extra);
                            if (File.Exists(ep)) { try { File.Delete(ep); } catch { } }
                        }
                        foreach (var net in NetworkFiles)
                        {
                            string np = Path.Combine(t, net);
                            if (File.Exists(np)) { try { File.Delete(np); } catch { } }
                        }
                    }

                    string optiFile = Path.Combine(t, opti);
                    if (File.Exists(optiFile) && (route != "dlss" || IsDlssLoaderBinary(optiFile))) { try { File.Delete(optiFile); } catch { } }

                    string gameIni = Path.Combine(t, "OptiScaler.ini");
                    string bIni = Path.Combine(backupDir, "OptiScaler.ini");
                    if (iniMode == "created")
                    {
                        if (File.Exists(gameIni)) { try { File.Delete(gameIni); } catch { } }
                        string optiLog = Path.Combine(t, "OptiScaler.log");
                        if (File.Exists(optiLog)) { try { File.Delete(optiLog); } catch { } }
                    }
                    else if (File.Exists(bIni))
                    {
                        try { File.Copy(bIni, gameIni, true); } catch { }
                    }

                    foreach (var c in created)
                    {
                        string cp = Path.Combine(t, c);
                        if (File.Exists(cp)) { try { File.Delete(cp); } catch { } }
                    }

                    foreach (var m in moved)
                    {
                        string bp = Path.Combine(backupDir, m);
                        string orig = Path.Combine(t, m);
                        if (File.Exists(bp))
                        {
                            try { File.Copy(bp, orig, true); } catch { }
                        }
                    }

                    if (Directory.Exists(helixDir))
                    {
                        try { Directory.Delete(helixDir, true); } catch { }
                    }

                    string subStorage = Path.Combine(t, "_storage_");
                    if (Directory.Exists(subStorage))
                    {
                        string subHelix = Path.Combine(subStorage, HelixSrFolder);
                        if (Directory.Exists(subHelix)) { try { Directory.Delete(subHelix, true); } catch { } }
                    }

                    string nvapiLeftover = Path.Combine(t, "nvapi64.dll");
                    if (File.Exists(nvapiLeftover)) { try { File.Delete(nvapiLeftover); } catch { } }
                }
            }

            // 2. Clean up Direct FSR 3.1 replacement artifacts if present
            if (game.FsrTargets != null)
            {
                foreach (var target in game.FsrTargets)
                {
                    string orig = Path.ChangeExtension(target, ".original.dll");
                    if (File.Exists(orig))
                    {
                        if (File.Exists(target)) File.Delete(target);
                        File.Move(orig, target);
                    }

                    foreach (var net in NetworkFiles)
                    {
                        string np = Path.Combine(Path.GetDirectoryName(target), net);
                        if (File.Exists(np)) { try { File.Delete(np); } catch { } }
                    }

                    string marker = Path.Combine(Path.GetDirectoryName(target), MarkerFile);
                    if (File.Exists(marker)) { try { File.Delete(marker); } catch { } }

                    string log = Path.Combine(Path.GetDirectoryName(target), "helixsr.log");
                    if (File.Exists(log)) { try { File.Delete(log); } catch { } }
                }
            }

            // Also check ExeFolder for standalone direct installation marker
            string exeDir = game.ExeFolder ?? game.Folder;
            if (!string.IsNullOrEmpty(exeDir) && Directory.Exists(exeDir))
            {
                string exeMarker = Path.Combine(exeDir, MarkerFile);
                if (File.Exists(exeMarker))
                {
                    try
                    {
                        var data = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(exeMarker));
                        if (data != null && data.ContainsKey("created_dlls"))
                        {
                            var list = data["created_dlls"] as System.Collections.ArrayList;
                            if (list != null)
                            {
                                foreach (var item in list)
                                {
                                    string p = Path.Combine(exeDir, item.ToString());
                                    if (File.Exists(p)) { try { File.Delete(p); } catch { } }
                                }
                            }
                        }
                    }
                    catch { }

                    foreach (var dllName in DllFiles)
                    {
                        string dst = Path.Combine(exeDir, dllName);
                        string orig = Path.ChangeExtension(dst, ".original.dll");
                        if (File.Exists(orig))
                        {
                            if (File.Exists(dst)) { try { File.Delete(dst); } catch { } }
                            try { File.Move(orig, dst); } catch { }
                        }
                    }

                    foreach (var net in NetworkFiles)
                    {
                        string np = Path.Combine(exeDir, net);
                        if (File.Exists(np)) { try { File.Delete(np); } catch { } }
                    }

                    try { File.Delete(exeMarker); } catch { }
                    string log = Path.Combine(exeDir, "helixsr.log");
                    if (File.Exists(log)) { try { File.Delete(log); } catch { } }
                }
            }
        }

        public static void UninstallHelixSR(GameInfo game)
        {
            CleanupHelixSRFiles(game);

            if (game.IsReEngine || game.InstallReFramework || File.Exists(Path.Combine(game.ExeFolder ?? game.Folder, "reframework_revision.txt")))
            {
                UninstallReFramework(game);
            }
        }

        public static bool ClearShaderCache(GameInfo game)
        {
            if (game == null) return false;
            bool cleared = false;
            var targetFolders = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (!string.IsNullOrEmpty(game.Folder) && Directory.Exists(game.Folder)) targetFolders.Add(game.Folder);
            if (!string.IsNullOrEmpty(game.ExeFolder) && Directory.Exists(game.ExeFolder)) targetFolders.Add(game.ExeFolder);

            foreach (var dir in targetFolders)
            {
                // Capcom RE Engine cache files
                string sc = Path.Combine(dir, "shader.cache2");
                if (File.Exists(sc)) { try { File.Delete(sc); cleared = true; } catch { } }

                string pl = Path.Combine(dir, "piplinelist.bin");
                if (File.Exists(pl)) { try { File.Delete(pl); cleared = true; } catch { } }

                // Subfolder _storage_ cache
                string subStorage = Path.Combine(dir, "_storage_");
                if (Directory.Exists(subStorage))
                {
                    string ssc = Path.Combine(subStorage, "shader.cache2");
                    if (File.Exists(ssc)) { try { File.Delete(ssc); cleared = true; } catch { } }
                    string spl = Path.Combine(subStorage, "piplinelist.bin");
                    if (File.Exists(spl)) { try { File.Delete(spl); cleared = true; } catch { } }
                }

                // Generic DirectX 12 pipeline caches
                try
                {
                    foreach (var f in Directory.EnumerateFiles(dir, "*.bin", SearchOption.TopDirectoryOnly))
                    {
                        string name = Path.GetFileName(f);
                        if (name.IndexOf("shader", StringComparison.OrdinalIgnoreCase) >= 0 ||
                            name.IndexOf("pipeline", StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            try { File.Delete(f); cleared = true; } catch { }
                        }
                    }
                }
                catch { }
            }
            return cleared;
        }

        /// <summary>
        /// Refreshes HelixSR in every installed game after the network was (re)built. Since HelixSR 1.8 the network lives
        /// inside amd_fidelityfx_dx12.dll, so the deployed DLL copies themselves are updated (plus separate network files
        /// for legacy builds). Returns the number of games updated.
        /// </summary>
        public static int SyncHelixSRToInstalledGames()
        {
            var status = GetCoreStatus();
            if (!status.WeightsBuilt) return 0;

            string srcDll = Path.Combine(CoreDir, DllFsr);
            if (!File.Exists(srcDll)) return 0;

            int count = 0;
            var allGames = ScanAllGames(null);
            foreach (var g in allGames)
            {
                if (!g.Installed) continue;
                try
                {
                    bool updated = false;
                    string t = g.ExeFolder ?? g.Folder;

                    if (g.Route == "optiscaler" && !string.IsNullOrEmpty(t))
                    {
                        foreach (var dir in new string[] { Path.Combine(t, HelixSrFolder), Path.Combine(t, "_storage_", HelixSrFolder) })
                        {
                            if (!Directory.Exists(dir)) continue;
                            File.Copy(srcDll, Path.Combine(dir, OwnDll), true);
                            File.Copy(srcDll, Path.Combine(dir, OwnSrDll), true);
                            SyncNetworkFiles(dir);
                            updated = true;
                        }
                        UpdateMarkerVersion(Path.Combine(t, HelixSrFolder, MarkerFile));
                    }
                    else if (g.Route == "dlss" && !string.IsNullOrEmpty(t))
                    {
                        string core = Path.Combine(t, NvngxCoreDll);
                        if (File.Exists(core) && IsHelixSrBinary(core))
                        {
                            File.Copy(srcDll, core, true);
                            SyncNetworkFiles(t);
                            UpdateMarkerVersion(Path.Combine(t, HelixSrFolder, MarkerFile));
                            updated = true;
                        }
                    }
                    else if (g.Route == "direct")
                    {
                        bool anyTarget = false;
                        if (g.FsrTargets != null)
                        {
                            foreach (var target in g.FsrTargets)
                            {
                                string targetDir = Path.GetDirectoryName(target);
                                string marker = Path.Combine(targetDir, MarkerFile);
                                // only targets HelixSR owns (game's file kept as *.original.dll or our install record)
                                if (!File.Exists(Path.ChangeExtension(target, ".original.dll")) && !File.Exists(marker)) continue;
                                anyTarget = true;
                                File.Copy(srcDll, target, true);
                                SyncNetworkFiles(targetDir);
                                UpdateMarkerVersion(marker);
                                updated = true;
                            }
                        }

                        string exeMarker = string.IsNullOrEmpty(t) ? null : Path.Combine(t, MarkerFile);
                        if (!anyTarget && exeMarker != null && File.Exists(exeMarker))
                        {
                            // Standalone drop-in next to the executable
                            foreach (var dllName in DllFiles)
                            {
                                string dst = Path.Combine(t, dllName);
                                if (File.Exists(dst) && IsHelixSrBinary(dst)) File.Copy(srcDll, dst, true);
                            }
                            SyncNetworkFiles(t);
                            UpdateMarkerVersion(exeMarker);
                            updated = true;
                        }
                    }

                    if (updated) count++;
                }
                catch
                {
                    // game running / file locked: leave this game as it is, the user can reinstall it from the drawer
                }
            }
            return count;
        }

        public static void SanitizeGameConfig(GameInfo game)
        {
            if (game == null) return;
            string root = game.Folder;
            if (string.IsNullOrEmpty(root) || !Directory.Exists(root)) return;

            string cfgPath = Path.Combine(root, "config.ini");
            if (File.Exists(cfgPath))
            {
                try
                {
                    string text = File.ReadAllText(cfgPath);
                    // 1. Reset stale [Render/Adapter] locking the game to a different GPU vendor (e.g. RTX 5070 vs AMD Z2)
                    text = Regex.Replace(text, @"(?m)^\[Render/Adapter\][\r\n]+(?:[A-Za-z0-9_]+=[^\r\n]*[\r\n]+)*", "");

                    // 2. Disable DLSS Reflex and Streamline FG if non-Nvidia
                    text = Regex.Replace(text, @"(?m)^DLSSReflexLowLatency=[^\r\n]*", "DLSSReflexLowLatency=OFF");
                    text = Regex.Replace(text, @"(?m)^FrameGeneration=[^\r\n]*", "FrameGeneration=OFF");

                    // 3. Set UpscalingAlgorithm to FSR3
                    if (Regex.IsMatch(text, @"(?m)^UpscalingAlgorithm="))
                    {
                        text = Regex.Replace(text, @"(?m)^UpscalingAlgorithm=[^\r\n]*", "UpscalingAlgorithm=FSR3");
                    }

                    File.WriteAllText(cfgPath, text);
                }
                catch { }
            }
        }

        public static bool DetectReEngine(string gameFolder, GameInfo game)
        {
            if (string.IsNullOrEmpty(gameFolder) || !Directory.Exists(gameFolder)) return false;

            // 1. Check for _storage_ folder (Pragmata, Monster Hunter Wilds, Dragon's Dogma 2 recent layouts)
            if (Directory.Exists(Path.Combine(gameFolder, "_storage_"))) return true;

            // 2. Check for re_chunk_000.pak or re_dlc_*.pak files
            try
            {
                if (Directory.GetFiles(gameFolder, "re_chunk_*.pak", SearchOption.TopDirectoryOnly).Length > 0) return true;
            }
            catch { }

            // 3. Check for RE Engine config.ini with [Render] Capability=DirectX12
            string cfg = Path.Combine(gameFolder, "config.ini");
            if (File.Exists(cfg))
            {
                try
                {
                    string content = File.ReadAllText(cfg);
                    if (content.Contains("[Render]") && content.Contains("Capability=DirectX12")) return true;
                }
                catch { }
            }

            // 4. Known RE Engine game titles / Steam AppIds
            string name = (game != null && !string.IsNullOrEmpty(game.Name)) ? game.Name.ToLowerInvariant() : Path.GetFileName(gameFolder).ToLowerInvariant();
            string[] reTitles = {
                "pragmata", "dragon's dogma 2", "dragons dogma 2", "dd2",
                "monster hunter wilds", "monster hunter rise", "mhwilds", "mhrise",
                "resident evil", "biohazard", "devil may cry 5", "dmc5", "street fighter 6", "sf6",
                "kunitsu-gami", "dead rising deluxe", "onimusha", "mega man star force"
            };
            foreach (var kw in reTitles)
            {
                if (name.Contains(kw)) return true;
            }

            return false;
        }

        // Unity engine profile: the player ships UnityPlayer.dll (Unity 2017.2+) and/or a "<exe>_Data" folder holding
        // globalgamemanagers / data.unity3d next to the game's .exe.
        private static readonly Regex UnityVersionRegex = new Regex(@"(?<![\d.])((?:20\d\d|6\d{3}|5)\.\d{1,2}\.\d{1,3}[abfpx]\d{1,3})", RegexOptions.Compiled);

        public static void DetectUnity(GameInfo game)
        {
            if (game == null) return;
            string exeDir = game.ExeFolder ?? game.Folder;
            if (string.IsNullOrEmpty(exeDir) || !Directory.Exists(exeDir)) return;

            string dataDir = FindUnityDataFolder(exeDir, game.ExeName);
            bool hasPlayer = File.Exists(Path.Combine(exeDir, "UnityPlayer.dll"));
            if (!hasPlayer && dataDir == null) return;

            game.IsUnity = true;

            // Scripting backend: IL2CPP builds ship GameAssembly.dll, Mono builds ship <exe>_Data\Managed
            if (File.Exists(Path.Combine(exeDir, "GameAssembly.dll")) || (dataDir != null && Directory.Exists(Path.Combine(dataDir, "il2cpp_data"))))
                game.UnityBackend = "IL2CPP";
            else if (dataDir != null && File.Exists(Path.Combine(dataDir, "Managed", "Assembly-CSharp.dll")))
                game.UnityBackend = "Mono";

            if (dataDir != null)
            {
                game.UnityVersion = ReadUnityVersion(dataDir);
                game.UnityPipeline = DetectUnityPipeline(dataDir, game.UnityBackend);
            }

            // Unity's D3D12 player loads the Agility SDK from a "D3D12" folder next to the .exe
            game.UnityHasD3D12 = File.Exists(Path.Combine(exeDir, "D3D12", "D3D12Core.dll"));
            game.UnityHasBepInEx = Directory.Exists(Path.Combine(exeDir, "BepInEx", "core"));
        }

        private static string FindUnityDataFolder(string exeDir, string exeName)
        {
            if (!string.IsNullOrEmpty(exeName))
            {
                string named = Path.Combine(exeDir, Path.GetFileNameWithoutExtension(exeName) + "_Data");
                if (IsUnityDataFolder(named)) return named;
            }
            try
            {
                foreach (var d in Directory.GetDirectories(exeDir, "*_Data", SearchOption.TopDirectoryOnly))
                {
                    if (IsUnityDataFolder(d)) return d;
                }
            }
            catch { }
            return null;
        }

        private static bool IsUnityDataFolder(string dir)
        {
            return Directory.Exists(dir) && (File.Exists(Path.Combine(dir, "globalgamemanagers")) || File.Exists(Path.Combine(dir, "data.unity3d")) || File.Exists(Path.Combine(dir, "mainData")));
        }

        /// <summary>
        /// Reads the engine version string from the header of the player's first serialized file / bundle
        /// (for example "2022.3.10f1" or "6000.0.23f1").
        /// </summary>
        public static string ReadUnityVersion(string dataDir)
        {
            foreach (var name in new[] { "globalgamemanagers", "data.unity3d", "mainData" })
            {
                string path = Path.Combine(dataDir, name);
                if (!File.Exists(path)) continue;
                try
                {
                    byte[] head = new byte[4096];
                    int read;
                    using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                    {
                        read = fs.Read(head, 0, head.Length);
                    }
                    var m = UnityVersionRegex.Match(Encoding.ASCII.GetString(head, 0, read));
                    if (m.Success) return m.Groups[1].Value;
                }
                catch { }
            }
            return null;
        }

        /// <summary>
        /// Render pipeline from the scripting assemblies the build lists (ScriptingAssemblies.json, Unity 2020.2+) or ships
        /// (Mono: Managed folder). Null when it cannot be told (older IL2CPP builds).
        /// </summary>
        public static string DetectUnityPipeline(string dataDir, string backend)
        {
            string assemblies = null;
            try
            {
                string listPath = Path.Combine(dataDir, "ScriptingAssemblies.json");
                if (File.Exists(listPath)) assemblies = File.ReadAllText(listPath);
            }
            catch { }

            if (assemblies == null && backend == "Mono")
            {
                try
                {
                    string managed = Path.Combine(dataDir, "Managed");
                    if (Directory.Exists(managed)) assemblies = string.Join("\n", Directory.GetFiles(managed, "*.dll", SearchOption.TopDirectoryOnly));
                }
                catch { }
            }

            if (assemblies == null) return null;
            if (assemblies.IndexOf("Unity.RenderPipelines.HighDefinition.Runtime", StringComparison.OrdinalIgnoreCase) >= 0) return "HDRP";
            if (assemblies.IndexOf("Unity.RenderPipelines.Universal.Runtime", StringComparison.OrdinalIgnoreCase) >= 0) return "URP";
            return "Built-in";
        }

        /// <summary>
        /// "6000.0.23f1" -> "Unity 6", "6000.1.2f1" -> "Unity 6.1", "2022.3.10f1" -> "Unity 2022.3".
        /// </summary>
        public static string FormatUnityVersion(string version)
        {
            if (string.IsNullOrEmpty(version)) return "Unity";
            var parts = version.Split('.');
            int major;
            if (parts.Length < 2 || !int.TryParse(parts[0], out major)) return "Unity " + version;
            if (major >= 6000)
            {
                int unity = major / 1000;
                return parts[1] == "0" ? string.Format("Unity {0}", unity) : string.Format("Unity {0}.{1}", unity, parts[1]);
            }
            return string.Format("Unity {0}.{1}", parts[0], parts[1]);
        }

        // inZOI (KRAFTON, Unreal Engine 5): project name "BlueClient", Steam AppId 2456740
        public const string InZoiAppId = "2456740";
        private const string InZoiSettingsSection = "/Script/BlueClient.B1GameUserSettings";
        private const string InZoiBackupFile = "GameUserSettings.helixsr-backup.json";
        private static readonly string[] InZoiSettingKeys = { "DLSSValue", "DLSSG", "FSR3Value", "FSR3FI" };

        public static bool DetectInZoi(string gameFolder, GameInfo game)
        {
            if (game != null && game.AppId == InZoiAppId) return true;
            if (string.IsNullOrEmpty(gameFolder) || !Directory.Exists(gameFolder)) return false;

            // 1. Unreal project folder "BlueClient" with its Win64 binaries
            if (Directory.Exists(Path.Combine(gameFolder, "BlueClient", "Binaries", "Win64"))) return true;

            // 2. Shipping executable name
            if (game != null && !string.IsNullOrEmpty(game.ExeName))
            {
                string exe = game.ExeName.ToLowerInvariant();
                if (exe.StartsWith("blueclient") || exe.StartsWith("inzoi")) return true;
            }

            // 3. Title / folder name
            string name = (game != null && !string.IsNullOrEmpty(game.Name)) ? game.Name : Path.GetFileName(gameFolder);
            return name.ToLowerInvariant().Replace(" ", "").Contains("inzoi");
        }

        /// <summary>
        /// inZOI keeps its graphics options in %LOCALAPPDATA%\BlueClient\Saved\Config\Windows\GameUserSettings.ini.
        /// </summary>
        public static string GetInZoiUserSettingsPath()
        {
            string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            return Path.Combine(localApp, "BlueClient", "Saved", "Config", "Windows", "GameUserSettings.ini");
        }

        /// <summary>
        /// OptiScaler.ini values for inZOI: OptiScaler's documented Unreal Engine on AMD fixes (resource barriers against
        /// rainbow colors, forced auto exposure against crushed dark areas).
        /// </summary>
        public static string ApplyInZoiOptiScalerIni(string text)
        {
            text = SetIniValue(text, "AutoExposure", "true", "InitFlags");
            text = SetIniValue(text, "ColorResourceBarrier", "4", "Hotfix");
            text = SetIniValue(text, "MotionVectorResourceBarrier", "8", "Hotfix");
            return text;
        }

        /// <summary>
        /// Selects the in-game upscaler that feeds HelixSR: DLSS for the OptiScaler and DLSS loader routes, FSR 3 for the
        /// direct route. The game's own values are saved next to the file and put back by RestoreInZoiUserSettings.
        /// </summary>
        public static void ApplyInZoiUserSettings(GameInfo game)
        {
            string cfgPath = GetInZoiUserSettingsPath();
            if (!File.Exists(cfgPath)) return; // the game writes it on first launch; install again afterwards to apply

            try
            {
                string text = File.ReadAllText(cfgPath);
                string backupPath = Path.Combine(Path.GetDirectoryName(cfgPath), InZoiBackupFile);
                if (!File.Exists(backupPath))
                {
                    var original = new Dictionary<string, object>();
                    foreach (var key in InZoiSettingKeys) original[key] = GetUeIniValue(text, InZoiSettingsSection, key);
                    File.WriteAllText(backupPath, Json.Serialize(original));
                }

                if (game.Route == "direct")
                {
                    int fsr;
                    if (!int.TryParse(GetUeIniValue(text, InZoiSettingsSection, "FSR3Value"), out fsr) || fsr <= 0)
                        text = SetUeIniValue(text, InZoiSettingsSection, "FSR3Value", "4"); // Quality
                    text = SetUeIniValue(text, InZoiSettingsSection, "DLSSValue", "0");
                    text = SetUeIniValue(text, InZoiSettingsSection, "DLSSG", "False");
                }
                else
                {
                    int dlss;
                    if (!int.TryParse(GetUeIniValue(text, InZoiSettingsSection, "DLSSValue"), out dlss) || dlss <= 0)
                        text = SetUeIniValue(text, InZoiSettingsSection, "DLSSValue", "4"); // Quality
                    text = SetUeIniValue(text, InZoiSettingsSection, "FSR3Value", "0");
                    text = SetUeIniValue(text, InZoiSettingsSection, "FSR3FI", "False");
                    // DLSS-G only when OptiScaler translates it (DLSS-G input modes); it does not work with the DLSS loader
                    bool dlssg = game.Route == "optiscaler" && !string.IsNullOrEmpty(game.FgMode) && game.FgMode.StartsWith("dlssg_");
                    text = SetUeIniValue(text, InZoiSettingsSection, "DLSSG", dlssg ? "True" : "False");
                }

                File.WriteAllText(cfgPath, text);
            }
            catch { }
        }

        public static void RestoreInZoiUserSettings()
        {
            string cfgPath = GetInZoiUserSettingsPath();
            string backupPath = Path.Combine(Path.GetDirectoryName(cfgPath), InZoiBackupFile);
            if (!File.Exists(backupPath)) return;

            try
            {
                if (File.Exists(cfgPath))
                {
                    var original = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(backupPath));
                    string text = File.ReadAllText(cfgPath);
                    foreach (var key in InZoiSettingKeys)
                    {
                        object val = (original != null && original.ContainsKey(key)) ? original[key] : null;
                        text = val == null ? RemoveUeIniValue(text, InZoiSettingsSection, key) : SetUeIniValue(text, InZoiSettingsSection, key, val.ToString());
                    }
                    File.WriteAllText(cfgPath, text);
                }
                File.Delete(backupPath);
            }
            catch { }
        }

        private static Match FindUeIniSection(string text, string section)
        {
            // Section body runs from its header to the next header (or end of file)
            return Regex.Match(text, string.Format(@"(?ms)^\[{0}\][ \t]*\r?\n(.*?)(?=^\[|\z)", Regex.Escape(section)));
        }

        public static string GetUeIniValue(string text, string section, string key)
        {
            var sec = FindUeIniSection(text, section);
            if (!sec.Success) return null;
            var m = Regex.Match(sec.Groups[1].Value, string.Format(@"(?m)^{0}[ \t]*=[ \t]*([^\r\n]*?)[ \t]*\r?$", Regex.Escape(key)));
            return m.Success ? m.Groups[1].Value : null;
        }

        /// <summary>
        /// Section-scoped "Key=Value" setter for Unreal Engine config files (no spaces around '=', unlike SetIniValue).
        /// </summary>
        public static string SetUeIniValue(string text, string section, string key, string value)
        {
            string line = string.Format("{0}={1}", key, value);
            var sec = FindUeIniSection(text, section);
            if (!sec.Success)
            {
                string sep = text.Length == 0 || text.EndsWith("\n") ? "" : "\r\n";
                return text + sep + string.Format("[{0}]\r\n{1}\r\n", section, line);
            }

            var body = sec.Groups[1];
            var keyRegex = new Regex(string.Format(@"(?m)^{0}[ \t]*=[^\r\n]*", Regex.Escape(key)));
            string newBody;
            if (keyRegex.IsMatch(body.Value))
            {
                newBody = keyRegex.Replace(body.Value, line.Replace("$", "$$"), 1);
            }
            else
            {
                // Append after the section's last non-empty line
                string trimmed = body.Value.TrimEnd('\r', '\n');
                string tail = body.Value.Substring(trimmed.Length);
                newBody = (trimmed.Length > 0 ? trimmed + "\r\n" : "") + line + (tail.Length > 0 ? tail : "\r\n");
            }
            return text.Substring(0, body.Index) + newBody + text.Substring(body.Index + body.Length);
        }

        public static string RemoveUeIniValue(string text, string section, string key)
        {
            var sec = FindUeIniSection(text, section);
            if (!sec.Success) return text;
            var body = sec.Groups[1];
            string newBody = Regex.Replace(body.Value, string.Format(@"(?m)^{0}[ \t]*=[^\r\n]*\r?\n?", Regex.Escape(key)), "");
            return text.Substring(0, body.Index) + newBody + text.Substring(body.Index + body.Length);
        }

        public static void InstallReFrameworkNightly(GameInfo game)
        {
            if (game == null) return;
            string root = game.ExeFolder ?? game.Folder;
            if (string.IsNullOrEmpty(root) || !Directory.Exists(root)) return;

            try
            {
                ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072; // TLS 1.2
            }
            catch { }

            string cacheDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HelixSR", "cache", "reframework");
            Directory.CreateDirectory(cacheDir);
            string cachedDll = Path.Combine(cacheDir, "dinput8.dll");
            string cachedRev = Path.Combine(cacheDir, "reframework_revision.txt");
            string zipPath = Path.Combine(cacheDir, "REFramework.zip");

            // Download latest monolithic REFramework.zip from praydog/REFramework-nightly
            bool downloaded = false;
            try
            {
                string url = "https://github.com/praydog/REFramework-nightly/releases/latest/download/REFramework.zip";
                var req = (HttpWebRequest)WebRequest.Create(url);
                req.UserAgent = "HelixSR-Manager/" + AppVersion;
                req.Timeout = 20000;
                req.ReadWriteTimeout = 20000;
                req.AllowAutoRedirect = true;

                using (var resp = req.GetResponse())
                using (var stream = resp.GetResponseStream())
                using (var fs = new FileStream(zipPath, FileMode.Create, FileAccess.Write))
                {
                    byte[] buffer = new byte[65536];
                    int read;
                    while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
                    {
                        fs.Write(buffer, 0, read);
                    }
                }

                if (File.Exists(zipPath) && new FileInfo(zipPath).Length > 100000)
                {
                    using (var archive = ZipFile.OpenRead(zipPath))
                    {
                        foreach (var entry in archive.Entries)
                        {
                            if (string.Equals(entry.Name, "dinput8.dll", StringComparison.OrdinalIgnoreCase))
                            {
                                entry.ExtractToFile(cachedDll, true);
                                downloaded = true;
                            }
                            else if (string.Equals(entry.Name, "reframework_revision.txt", StringComparison.OrdinalIgnoreCase))
                            {
                                entry.ExtractToFile(cachedRev, true);
                            }
                        }
                    }
                }
            }
            catch
            {
                // If offline or GitHub unreachable, fall back to cached dinput8.dll if present
            }
            finally
            {
                if (File.Exists(zipPath)) { try { File.Delete(zipPath); } catch { } }
            }

            if (!downloaded && !File.Exists(cachedDll)) return;

            // Deploy dinput8.dll to game root (and _storage_ if present)
            var targets = new List<string> { root };
            string subStorage = Path.Combine(root, "_storage_");
            if (Directory.Exists(subStorage)) targets.Add(subStorage);

            foreach (var dir in targets)
            {
                string dstDll = Path.Combine(dir, "dinput8.dll");
                File.Copy(cachedDll, dstDll, true);

                if (File.Exists(cachedRev))
                {
                    try { File.Copy(cachedRev, Path.Combine(dir, "reframework_revision.txt"), true); } catch { }
                }
            }
        }

        public static void UninstallReFramework(GameInfo game)
        {
            if (game == null) return;
            var dirs = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (!string.IsNullOrEmpty(game.Folder) && Directory.Exists(game.Folder)) dirs.Add(game.Folder);
            if (!string.IsNullOrEmpty(game.ExeFolder) && Directory.Exists(game.ExeFolder)) dirs.Add(game.ExeFolder);

            string subStorage = Path.Combine(game.ExeFolder ?? game.Folder, "_storage_");
            if (Directory.Exists(subStorage)) dirs.Add(subStorage);

            string[] refFiles = {
                "dinput8.dll",
                "reframework_revision.txt",
                "re2_framework_log.txt",
                "re2_fw_config.txt",
                "reframework_crash.dmp",
                "reframework_accessed_files.txt",
                "reframework_faulty_files.txt",
                "reframework_loose_files.txt",
                "ref_ui.ini"
            };

            foreach (var dir in dirs)
            {
                foreach (var f in refFiles)
                {
                    string p = Path.Combine(dir, f);
                    if (File.Exists(p)) { try { File.Delete(p); } catch { } }
                }

                string refSubDir = Path.Combine(dir, "reframework");
                if (Directory.Exists(refSubDir))
                {
                    try { Directory.Delete(refSubDir, true); } catch { }
                }
            }
        }

        public static string SetIniValue(string text, string key, string value, string section)
        {
            var keyRegex = new Regex(string.Format(@"(?m)^({0})[ \t]*=[ \t]*([^\r\n]*?)[ \t]*(?=\r?$)", Regex.Escape(key)));
            if (keyRegex.IsMatch(text))
            {
                return keyRegex.Replace(text, string.Format("{0} = {1}", key, value), 1);
            }
            if (!string.IsNullOrEmpty(section))
            {
                var secRegex = new Regex(string.Format(@"(?m)^\[{0}\][ \t]*(\r?\n)", Regex.Escape(section)));
                var match = secRegex.Match(text);
                if (match.Success)
                {
                    int idx = match.Index + match.Length;
                    return text.Substring(0, idx) + string.Format("{0} = {1}\r\n", key, value) + text.Substring(idx);
                }
                return text + string.Format("\r\n[{0}]\r\n{1} = {2}\r\n", section, key, value);
            }
            return text + string.Format("\r\n{0} = {1}\r\n", key, value);
        }

        public static string ReadGameLog(string gameFolder, string logName)
        {
            string p1 = Path.Combine(gameFolder, HelixSrFolder, logName);
            if (File.Exists(p1)) return File.ReadAllText(p1);

            string p2 = Path.Combine(gameFolder, logName);
            if (File.Exists(p2)) return File.ReadAllText(p2);

            return "No log content found.";
        }

        public static string ReadOptiScalerIni(string gameFolder)
        {
            string p = Path.Combine(gameFolder, "OptiScaler.ini");
            if (File.Exists(p)) return File.ReadAllText(p);
            return "";
        }

        public static void SaveOptiScalerIni(string gameFolder, string content)
        {
            string p = Path.Combine(gameFolder, "OptiScaler.ini");
            File.WriteAllText(p, content);
        }

        public static List<GpuInfo> GetGpuInfo()
        {
            var list = new List<GpuInfo>();
            try
            {
                using (var searcher = new System.Management.ManagementObjectSearcher("SELECT Name, AdapterRAM, DriverVersion FROM Win32_VideoController"))
                {
                    foreach (var mo in searcher.Get())
                    {
                        string name = mo["Name"] as string;
                        if (!string.IsNullOrEmpty(name))
                        {
                            long ram = 0;
                            try { ram = Convert.ToInt64(mo["AdapterRAM"]) / (1024 * 1024); } catch { }
                            string driver = mo["DriverVersion"] as string;
                            list.Add(new GpuInfo { Name = name, RamMB = ram, Driver = driver });
                        }
                    }
                }
            }
            catch
            {
                list.Add(new GpuInfo { Name = "Direct3D 12 Compatible GPU", RamMB = 0, Driver = "N/A" });
            }
            return list;
        }
    }
}
