@echo off
setlocal
cd /d "%~dp0"

echo [HelixSR Manager] Compiling native standalone HelixSR-Manager.exe...

set "NETDIR=C:\Windows\Microsoft.NET\Framework64\v4.0.30319"
set "WPFDIR=%NETDIR%\WPF"
set "CSC=%NETDIR%\csc.exe"

if not exist "%CSC%" (
    echo [ERROR] Microsoft Visual C# Compiler not found at %CSC%
    pause
    exit /b 1
)

taskkill /F /IM HelixSR-Manager.exe /T >nul 2>&1

"%CSC%" /nologo /target:winexe /win32icon:src\app.ico /out:HelixSR-Manager.exe ^
  /r:"%NETDIR%\System.dll" ^
  /r:"%NETDIR%\System.Core.dll" ^
  /r:"%NETDIR%\System.IO.Compression.dll" ^
  /r:"%NETDIR%\System.IO.Compression.FileSystem.dll" ^
  /r:"%NETDIR%\System.Xaml.dll" ^
  /r:"%NETDIR%\System.Windows.Forms.dll" ^
  /r:"%NETDIR%\System.Management.dll" ^
  /r:"%NETDIR%\System.Web.Extensions.dll" ^
  /r:"%WPFDIR%\PresentationFramework.dll" ^
  /r:"%WPFDIR%\PresentationCore.dll" ^
  /r:"%WPFDIR%\WindowsBase.dll" ^
  src\IEnvironmentSettings.cs src\DefaultEnvironmentSettings.cs src\Models.cs src\Engine.cs src\MainWindow.cs src\Program.cs

if %errorlevel% neq 0 (
    echo [ERROR] Compilation failed.
    exit /b %errorlevel%
)

echo [SUCCESS] Built native HelixSR-Manager.exe successfully!

powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0src\package-builds.ps1"
if %errorlevel% neq 0 (
    echo [ERROR] Packaging build\windows, build\linux, and zip archives failed.
    exit /b %errorlevel%
)
