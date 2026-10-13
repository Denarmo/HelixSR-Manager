$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.IO.Compression.FileSystem

$CoreVersion = "1.8.1"   # bundled upstream HelixSR core (keep in sync with Engine.CoreVersion / CORE_VERSION)

$RootDir = Split-Path -Parent $PSScriptRoot
$BuildDir = Join-Path $RootDir "build"
$WinBuild = Join-Path $BuildDir "windows"
$LinBuild = Join-Path $BuildDir "linux"
$CoreSrc = Join-Path $RootDir "helixsr_core\HelixSR-$CoreVersion"

Write-Host "[HelixSR Manager Build] Generating build\windows and build\linux distributions..." -ForegroundColor Yellow

# Prepare directories
New-Item -ItemType Directory -Force -Path $WinBuild | Out-Null
New-Item -ItemType Directory -Force -Path $LinBuild | Out-Null

# Clean up any legacy Swapper filenames or local config.json in build folders
Remove-Item -Path (Join-Path $WinBuild "HelixSR-Swapper.exe") -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $WinBuild "config.json") -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $LinBuild "HelixSR-Swapper.sh") -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $LinBuild "HelixSR-Swapper.desktop") -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $LinBuild "config.json") -Force -ErrorAction SilentlyContinue

# Remove cores of older versions from previous packaging runs
foreach ($b in @($WinBuild, $LinBuild)) {
    $coreRoot = Join-Path $b "helixsr_core"
    if (Test-Path $coreRoot) {
        Get-ChildItem -Path $coreRoot -Directory | Where-Object { $_.Name -ne "HelixSR-$CoreVersion" } | Remove-Item -Recurse -Force
    }
}

# Files that only exist after a local network build. They contain NVIDIA's network and must never be packaged.
$ExcludeDirs = @("__pycache__", "manual-install", "fsr3-drop-in")
$ExcludeFiles = @("*.pyc", "helixsr_weights.bin", "helixsr_kernels.pak", "helixsr_setup.json", "*.log")

# HelixSR 1.8+ appends the network to amd_fidelityfx_dx12.dll after a local build (one-file DLL, trailer "HXSRNET1").
# Cut it off again so the packages only ever contain the DLL as released upstream.
function Remove-EmbeddedNetwork($dllPath) {
    if (-not (Test-Path $dllPath)) { return }
    $fs = [System.IO.File]::Open($dllPath, 'Open', 'ReadWrite')
    try {
        if ($fs.Length -lt 32) { return }
        $fs.Seek(-32, 'End') | Out-Null
        $tail = New-Object byte[] 32
        [void]$fs.Read($tail, 0, 32)
        if ([System.Text.Encoding]::ASCII.GetString($tail, 0, 8) -ne "HXSRNET1") { return }
        $nw = [System.BitConverter]::ToUInt64($tail, 8)
        $nk = [System.BitConverter]::ToUInt64($tail, 16)
        $newLen = $fs.Length - 32 - [int64]$nw - [int64]$nk
        if ($newLen -le 0) { throw "Corrupt HelixSR network trailer in $dllPath" }
        $fs.SetLength($newLen)
        Write-Host "  stripped locally built network from $dllPath" -ForegroundColor DarkYellow
    } finally {
        $fs.Close()
    }
}

function Copy-Core($dst) {
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    & robocopy $CoreSrc $dst /MIR /XD $ExcludeDirs /XF $ExcludeFiles /NFL /NDL /NJH /NJS /NP /R:2 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) copying core to $dst" }
    Get-ChildItem -Path $dst -Filter "amd_fidelityfx_dx12.dll" -Recurse | ForEach-Object { Remove-EmbeddedNetwork $_.FullName }
}

# ---------------------------------------------------------
# 1. Populate build\windows
# ---------------------------------------------------------
Copy-Item -Path (Join-Path $RootDir "HelixSR-Manager.exe") -Destination (Join-Path $WinBuild "HelixSR-Manager.exe") -Force
if (Test-Path (Join-Path $RootDir "README.md")) {
    Copy-Item -Path (Join-Path $RootDir "README.md") -Destination (Join-Path $WinBuild "README.md") -Force
}
if (Test-Path (Join-Path $RootDir "LICENSE")) {
    Copy-Item -Path (Join-Path $RootDir "LICENSE") -Destination (Join-Path $WinBuild "LICENSE") -Force
}

# HelixSR-Manager.exe is now 100% standalone with all necessary core files embedded inside the binary.
if (Test-Path (Join-Path $WinBuild "helixsr_core")) {
    Remove-Item -Path (Join-Path $WinBuild "helixsr_core") -Recurse -Force
}

# ---------------------------------------------------------
# 2. Populate build\linux (SteamOS / Linux)
# ---------------------------------------------------------
function Copy-WithLf($srcFile, $dstFile) {
    $raw = [System.IO.File]::ReadAllText($srcFile, [System.Text.Encoding]::UTF8)
    $lf = $raw -replace "`r`n", "`n"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($dstFile, $lf, $utf8NoBom)
}

Copy-WithLf (Join-Path $RootDir "src\linux\HelixSR-Manager.sh") (Join-Path $LinBuild "HelixSR-Manager.sh")
Copy-WithLf (Join-Path $RootDir "src\linux\HelixSR-Manager.desktop") (Join-Path $LinBuild "HelixSR-Manager.desktop")
Copy-WithLf (Join-Path $RootDir "src\linux\helixsr_swapper_linux.py") (Join-Path $LinBuild "helixsr_swapper_linux.py")

if (Test-Path (Join-Path $RootDir "README.md")) {
    Copy-WithLf (Join-Path $RootDir "README.md") (Join-Path $LinBuild "README.md")
}
if (Test-Path (Join-Path $RootDir "LICENSE")) {
    Copy-WithLf (Join-Path $RootDir "LICENSE") (Join-Path $LinBuild "LICENSE")
}

# Copy public web UI assets for Linux/SteamOS app window
$LinPublicDst = Join-Path $LinBuild "public"
New-Item -ItemType Directory -Force -Path $LinPublicDst | Out-Null
& robocopy (Join-Path $RootDir "public") $LinPublicDst /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:1 | Out-Null

# Copy the HelixSR core to the Linux build and ensure shell/python scripts have Unix LF endings
$LinCoreDst = Join-Path $LinBuild "helixsr_core\HelixSR-$CoreVersion"
Copy-Core $LinCoreDst

Get-ChildItem -Path $LinCoreDst -Filter "*.sh" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-WithLf $_.FullName $_.FullName
}
Get-ChildItem -Path (Join-Path $LinCoreDst "setup") -Filter "*.py" -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-WithLf $_.FullName $_.FullName
}

# ---------------------------------------------------------
# 3. Generate Zip Archives (helixsr-manager-platform.zip)
# ---------------------------------------------------------
function Set-ZipUnixPermissions($zipPath) {
    $fs = [System.IO.File]::Open($zipPath, 'Open', 'ReadWrite')
    try {
        if ($fs.Length -lt 22) { return }
        $searchLen = [Math]::Min([int64]65557, $fs.Length)
        $fs.Seek(-$searchLen, 'End') | Out-Null
        $tail = New-Object byte[] $searchLen
        [void]$fs.Read($tail, 0, [int]$searchLen)

        $eocdIdx = -1
        for ($i = [int]$searchLen - 22; $i -ge 0; $i--) {
            if ($tail[$i] -eq 0x50 -and $tail[$i+1] -eq 0x4B -and $tail[$i+2] -eq 0x05 -and $tail[$i+3] -eq 0x06) {
                $eocdIdx = $i
                break
            }
        }
        if ($eocdIdx -lt 0) { throw "EOCD record not found in $zipPath" }

        $entryCount = [System.BitConverter]::ToUInt16($tail, $eocdIdx + 10)
        $cdOffset = [System.BitConverter]::ToUInt32($tail, $eocdIdx + 16)

        $pos = [int64]$cdOffset
        $hdr = New-Object byte[] 46
        for ($e = 0; $e -lt $entryCount; $e++) {
            $fs.Seek($pos, 'Begin') | Out-Null
            [void]$fs.Read($hdr, 0, 46)
            $sig = [System.BitConverter]::ToUInt32($hdr, 0)
            if ($sig -ne 0x02014B50) { throw "Invalid Central Directory header at offset $pos in $zipPath" }

            $fnLen = [System.BitConverter]::ToUInt16($hdr, 28)
            $extraLen = [System.BitConverter]::ToUInt16($hdr, 30)
            $commentLen = [System.BitConverter]::ToUInt16($hdr, 32)

            $fnBytes = New-Object byte[] $fnLen
            [void]$fs.Read($fnBytes, 0, $fnLen)
            $entryName = [System.Text.Encoding]::UTF8.GetString($fnBytes).Replace('\', '/')

            # VersionMadeBy: spec 2.0 (20), host OS = Unix (3)
            $hdr[4] = 20
            $hdr[5] = 3

            if ($entryName.EndsWith("/")) {
                # 0040755 (drwxr-xr-x) << 16 | 0x10 (0x41ED0010 little-endian)
                $hdr[38] = 0x10; $hdr[39] = 0x00; $hdr[40] = 0xED; $hdr[41] = 0x41
            } elseif (
                $entryName.EndsWith(".sh") -or
                $entryName.EndsWith(".desktop") -or
                $entryName.EndsWith(".py") -or
                $entryName.EndsWith("/launch_synth") -or
                ($entryName -eq "launch_synth")
            ) {
                # 0100755 (-rwxr-xr-x) << 16 (0x81ED0000 little-endian)
                $hdr[38] = 0x00; $hdr[39] = 0x00; $hdr[40] = 0xED; $hdr[41] = 0x81
            } else {
                # 0100644 (-rw-r--r--) << 16 (0x81A40000 little-endian)
                $hdr[38] = 0x00; $hdr[39] = 0x00; $hdr[40] = 0xA4; $hdr[41] = 0x81
            }

            $fs.Seek($pos, 'Begin') | Out-Null
            $fs.Write($hdr, 0, 46)

            $pos += 46 + $fnLen + $extraLen + $commentLen
        }
    } finally {
        $fs.Close()
    }
}

$WinZip = Join-Path $BuildDir "helixsr-manager-windows.zip"
$LinZip = Join-Path $BuildDir "helixsr-manager-linux.zip"

if (Test-Path $WinZip) { Remove-Item -Path $WinZip -Force }
if (Test-Path $LinZip) { Remove-Item -Path $LinZip -Force }

Write-Host "[HelixSR Manager Build] Creating zip packages..." -ForegroundColor Yellow
[System.IO.Compression.ZipFile]::CreateFromDirectory($WinBuild, $WinZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
[System.IO.Compression.ZipFile]::CreateFromDirectory($LinBuild, $LinZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
Set-ZipUnixPermissions $LinZip

Write-Host "[SUCCESS] Generated standalone distributions and zip packages:" -ForegroundColor Green
Write-Host "  -> Windows Folder : $WinBuild" -ForegroundColor Green
Write-Host "  -> Linux Folder   : $LinBuild" -ForegroundColor Green
Write-Host "  -> Windows Zip    : $WinZip" -ForegroundColor Green
Write-Host "  -> Linux Zip      : $LinZip" -ForegroundColor Green
exit 0
