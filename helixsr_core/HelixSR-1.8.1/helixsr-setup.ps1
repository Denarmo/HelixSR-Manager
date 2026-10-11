# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
#
# HelixSR setup for Windows, the only thing to run:
#   1. the first time (or with -Rebuild): builds HelixSR's network into its DLL (one file) from NVIDIA's DLSS 310.7.0 DLL
#      (downloaded from NVIDIA's GitHub after you agree, or -Dlss <file>);
#   2. lists your DLSS games and installs HelixSR + OptiScaler into the ones you pick, or removes them again.
#
#   helixsr-setup.bat [GAME_FOLDER].. [-Dlss nvngx_dlss.dll] [-Rebuild] [-Yes]
#
# A GAME_FOLDER (or a folder dropped onto helixsr-setup.bat) adds a game the setup does not find by itself.
# One-time downloads into %LOCALAPPDATA%\HelixSR: Python
# (python.org embeddable package) + numpy (PyPI) and the DirectX Shader Compiler (Microsoft's GitHub). Nothing is
# installed system-wide and no admin rights are needed.
param(
    [string]$Dlss = "",
    [switch]$Yes,
    [switch]$Rebuild,
    [switch]$Wave64,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Folders = @()
)
$Target = $PSScriptRoot
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is much faster without the progress bar

$Here = $PSScriptRoot
$Data = Join-Path $env:LOCALAPPDATA 'HelixSR'
$Downloads = @{
    python = @{ url = 'https://www.python.org/ftp/python/3.14.8/python-3.14.8-embed-amd64.zip'
                sha = 'a93abe456ab01bd96d7a085b3cdb6566b3063f4241360d114142fbdb07f0a310' }
    numpy  = @{ url = 'https://files.pythonhosted.org/packages/a4/73/d2c08231e4fde7e415501fd02c715d96e98599b2d8384445933944152984/numpy-2.5.3-cp314-cp314-win_amd64.whl'
                sha = '2c25dfa72943e4336ddb6b0ee4277b47a0c85bede0807530ec68103bf58e2c10' }
    dxc    = @{ url = 'https://github.com/microsoft/DirectXShaderCompiler/releases/download/v1.9.2607/dxc_2026_07_29.zip'
                sha = 'a1dfb116ba3eeae6a1582291b53a8e7bf65ad760676bd3194685c8f7367cd241' }
}

function Say($m) { Write-Host "[helixsr-setup] $m" }
function Fetch($name, $file) {
    $d = $Downloads[$name]
    Say "downloading $(Split-Path $file -Leaf)"
    Invoke-WebRequest -Uri $d.url -OutFile $file -UseBasicParsing
    if ((Get-FileHash -Algorithm SHA256 $file).Hash.ToLower() -ne $d.sha) {
        Remove-Item $file -Force
        throw "$(Split-Path $file -Leaf): checksum mismatch"
    }
}

try {
    if (-not (Test-Path $Target -PathType Container)) { throw "not a folder: $Target" }
    New-Item -ItemType Directory -Force -Path $Data | Out-Null

    # --- Python + numpy (embeddable package: no installer, no PATH changes) ---
    $Py = Join-Path $Data 'python\python.exe'
    if (-not (Test-Path (Join-Path $Data 'python\numpy'))) {
        $zip = Join-Path $Data 'python.zip'
        Fetch 'python' $zip
        Expand-Archive -Path $zip -DestinationPath (Join-Path $Data 'python') -Force
        Remove-Item $zip -Force
        $whl = Join-Path $Data 'numpy.zip'   # a wheel is a zip
        Fetch 'numpy' $whl
        Expand-Archive -Path $whl -DestinationPath (Join-Path $Data 'python') -Force
        Remove-Item $whl -Force
    }

    # --- network: built once, into HelixSR's DLL ---
    # built = the network inside HelixSR's DLL (one-file DLL), or the two separate files of an older setup
    $w = Join-Path $Target 'helixsr_weights.bin'; $k = Join-Path $Target 'helixsr_kernels.pak'
    $built = (Test-Path $w) -and (Test-Path $k) -and ((Get-Item $w).Length -gt 0) -and ((Get-Item $k).Length -gt 0)
    $dll = Join-Path $Target 'amd_fidelityfx_dx12.dll'
    if (-not $built -and (Test-Path $dll) -and (Get-Item $dll).Length -gt 32) {
        $fs = [System.IO.File]::OpenRead($dll)
        try {
            $null = $fs.Seek(-32, [System.IO.SeekOrigin]::End)
            $tag = New-Object byte[] 8
            $null = $fs.Read($tag, 0, 8)
            $built = [System.Text.Encoding]::ASCII.GetString($tag) -eq 'HXSRNET1'
        } finally { $fs.Close() }
    }
    if ($built -and -not $Rebuild -and -not $Wave64) {
        Say "the network is already built (-Rebuild builds it again)"
    } else {
    # --- DirectX Shader Compiler ---
    $Dxc = Join-Path $Data 'dxc\dxc.exe'
    if (-not (Test-Path $Dxc)) {
        $zip = Join-Path $Data 'dxc.zip'
        Fetch 'dxc' $zip
        $tmp = Join-Path $Data 'dxc-unpack'
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        New-Item -ItemType Directory -Force -Path (Join-Path $Data 'dxc') | Out-Null
        Copy-Item (Join-Path $tmp 'bin\x64\*') (Join-Path $Data 'dxc') -Force
        Remove-Item $zip, $tmp -Recurse -Force
    }

    # --- build ---
    $pass = @((Resolve-Path $Target).Path, '--dxc', $Dxc)
    if ($Dlss) { $pass += @('--dlss', (Resolve-Path $Dlss).Path) }
    if ($Yes) { $pass += '--yes' }
    if ($Wave64) { $pass += '--wave64' }
    & $Py (Join-Path $Here 'setup\helixsr_setup.py') @pass
    if ($LASTEXITCODE -ne 0) { throw "setup failed (exit $LASTEXITCODE)" }
    }

    # --- games ---
    $inst = @((Resolve-Path $Target).Path)
    foreach ($f in $Folders) {
        if (-not (Test-Path $f -PathType Container)) { throw "not a folder: $f" }
        $inst += @('--folder', (Resolve-Path $f).Path)
    }
    & $Py (Join-Path $Here 'setup\helixsr_install.py') @inst
    if ($LASTEXITCODE -ne 0) { throw "game setup failed (exit $LASTEXITCODE)" }
}
catch {
    Write-Host "[helixsr-setup] error: $_" -ForegroundColor Red
    exit 1
}
