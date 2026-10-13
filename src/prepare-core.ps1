$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.IO.Compression.FileSystem

$CoreVersion = "1.8.1"
$RootDir = Split-Path -Parent $PSScriptRoot
$CoreSrc = Join-Path $RootDir "helixsr_core\HelixSR-$CoreVersion"
$BuildDir = Join-Path $RootDir "build"
$StageDir = Join-Path $BuildDir "core_embed"
$ZipOut = Join-Path $BuildDir "helixsr_core.zip"

if (-not (Test-Path $CoreSrc)) {
    throw "Core source folder not found at: $CoreSrc"
}

Write-Host "[HelixSR Manager] Preparing clean core bundle for standalone embedding..." -ForegroundColor Yellow

# Clean up any existing stage directory and zip file
if (Test-Path $StageDir) { Remove-Item -Path $StageDir -Recurse -Force }
if (Test-Path $ZipOut) { Remove-Item -Path $ZipOut -Force }

New-Item -ItemType Directory -Force -Path $StageDir | Out-Null
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

$ExcludeDirs = @("__pycache__", "manual-install", "fsr3-drop-in")
$ExcludeFiles = @("*.pyc", "helixsr_weights.bin", "helixsr_kernels.pak", "helixsr_setup.json", "*.log")

# Robocopy clean core files to stage directory
& robocopy $CoreSrc $StageDir /MIR /XD $ExcludeDirs /XF $ExcludeFiles /NFL /NDL /NJH /NJS /NP /R:2 /W:1 | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE) staging core to $StageDir" }

# Function to remove any local network trailer from amd_fidelityfx_dx12.dll
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

Get-ChildItem -Path $StageDir -Filter "amd_fidelityfx_dx12.dll" -Recurse | ForEach-Object { Remove-EmbeddedNetwork $_.FullName }

# Compress staged files into helixsr_core.zip
[System.IO.Compression.ZipFile]::CreateFromDirectory($StageDir, $ZipOut, [System.IO.Compression.CompressionLevel]::Optimal, $false)

# Clean up stage directory
Remove-Item -Path $StageDir -Recurse -Force

$zipSizeMb = [math]::round((Get-Item $ZipOut).Length / 1MB, 2)
Write-Host "[SUCCESS] Created embedded core bundle: $ZipOut ($zipSizeMb MB)" -ForegroundColor Green
exit 0
