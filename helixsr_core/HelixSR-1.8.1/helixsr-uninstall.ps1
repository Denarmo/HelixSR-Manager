# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
#
# HelixSR uninstaller for Windows: removes HelixSR (and the OptiScaler it installed) from the games you pick and puts
# back everything it replaced; then optionally deletes the built network files and the setup's downloads
# (%LOCALAPPDATA%\HelixSR).
#
#   helixsr-uninstall.bat [GAME_FOLDER]..
#
# A GAME_FOLDER (or a folder dropped onto helixsr-uninstall.bat) adds a game the uninstaller does not find by itself.
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Folders = @())
$ErrorActionPreference = 'Stop'
$Here = $PSScriptRoot
$Data = Join-Path $env:LOCALAPPDATA 'HelixSR'
try {
    $Py = Join-Path $Data 'python\python.exe'
    if (-not (Test-Path $Py)) {
        $Py = $null
        foreach ($c in @('py', 'python')) {
            $cmd = Get-Command $c -ErrorAction SilentlyContinue
            if ($cmd -and $cmd.Source -notlike '*WindowsApps*') { $Py = $cmd.Source; break }
        }
        if (-not $Py) { throw "no Python found (the setup's Python in $Data is gone): HelixSR can be removed by hand, see manual-install\README.txt" }
    }
    $inst = @((Resolve-Path $Here).Path, 'remove')
    foreach ($f in $Folders) {
        if (-not (Test-Path $f -PathType Container)) { throw "not a folder: $f" }
        $inst += @('--folder', (Resolve-Path $f).Path)
    }
    & $Py (Join-Path $Here 'setup\helixsr_install.py') @inst
    if ($LASTEXITCODE -eq 3) {
        Remove-Item $Data -Recurse -Force
        Write-Host "[helixsr-uninstall] deleted $Data"
    } elseif ($LASTEXITCODE -ne 0) { throw "uninstall failed (exit $LASTEXITCODE)" }
}
catch {
    Write-Host "[helixsr-uninstall] error: $_" -ForegroundColor Red
    exit 1
}
