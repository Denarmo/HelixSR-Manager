$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.IO.Compression.FileSystem

$RootDir = Split-Path -Parent $PSScriptRoot
$BuildDir = Join-Path $RootDir "build"
$WinBuild = Join-Path $BuildDir "windows"
$LinBuild = Join-Path $BuildDir "linux"
$CoreSrc = Join-Path $RootDir "helixsr_core\HelixSR-1.7.0"

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

$WinCoreDst = Join-Path $WinBuild "helixsr_core\HelixSR-1.7.0"
New-Item -ItemType Directory -Force -Path $WinCoreDst | Out-Null
& robocopy $CoreSrc $WinCoreDst /MIR /XD "__pycache__" "manual-install" /XF "*.pyc" "helixsr_weights.bin" "helixsr_kernels.pak" "helixsr_setup.json" /NFL /NDL /NJH /NJS /NP /R:2 /W:1 | Out-Null

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

# Copy HelixSR-1.7.0 core to Linux build and ensure shell/python scripts have Unix LF endings
$LinCoreDst = Join-Path $LinBuild "helixsr_core\HelixSR-1.7.0"
New-Item -ItemType Directory -Force -Path $LinCoreDst | Out-Null
& robocopy $CoreSrc $LinCoreDst /MIR /XD "__pycache__" "manual-install" /XF "*.pyc" "helixsr_weights.bin" "helixsr_kernels.pak" "helixsr_setup.json" /NFL /NDL /NJH /NJS /NP /R:2 /W:1 | Out-Null

$SetupSh = Join-Path $LinCoreDst "helixsr-setup.sh"
if (Test-Path $SetupSh) {
    Copy-WithLf $SetupSh $SetupSh
}
Get-ChildItem -Path (Join-Path $LinCoreDst "setup") -Filter "*.py" -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-WithLf $_.FullName $_.FullName
}

# ---------------------------------------------------------
# 3. Generate Zip Archives (helixsr-manager-platform.zip)
# ---------------------------------------------------------
$WinZip = Join-Path $BuildDir "helixsr-manager-windows.zip"
$LinZip = Join-Path $BuildDir "helixsr-manager-linux.zip"

if (Test-Path $WinZip) { Remove-Item -Path $WinZip -Force }
if (Test-Path $LinZip) { Remove-Item -Path $LinZip -Force }

Write-Host "[HelixSR Manager Build] Creating zip packages..." -ForegroundColor Yellow
[System.IO.Compression.ZipFile]::CreateFromDirectory($WinBuild, $WinZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
[System.IO.Compression.ZipFile]::CreateFromDirectory($LinBuild, $LinZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)

Write-Host "[SUCCESS] Generated standalone distributions and zip packages:" -ForegroundColor Green
Write-Host "  -> Windows Folder : $WinBuild" -ForegroundColor Green
Write-Host "  -> Linux Folder   : $LinBuild" -ForegroundColor Green
Write-Host "  -> Windows Zip    : $WinZip" -ForegroundColor Green
Write-Host "  -> Linux Zip      : $LinZip" -ForegroundColor Green
exit 0
