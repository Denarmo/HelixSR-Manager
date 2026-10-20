@echo off
rem Builds HelixSRBridge.dll for a Unity Mono game with BepInEx 5 installed, and copies it plus the native plugin in.
rem Usage: build-plugin.bat "D:\SteamLibrary\steamapps\common\artofrally"
rem Needs the .NET Framework compiler that ships with Windows (no SDK required).
setlocal
set "GAME=%~1"
if "%GAME%"=="" (echo Usage: %~nx0 "path\to\game folder" & exit /b 1)
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" (echo csc.exe not found at %CSC% & exit /b 1)
if not exist "%GAME%\BepInEx\core\BepInEx.dll" (echo BepInEx 5 is not installed in "%GAME%" & exit /b 1)

set "MANAGED="
for /d %%D in ("%GAME%\*_Data") do if exist "%%D\Managed\UnityEngine.CoreModule.dll" set "MANAGED=%%D\Managed"
if "%MANAGED%"=="" (echo No *_Data\Managed\UnityEngine.CoreModule.dll in "%GAME%" - not a Mono Unity game? & exit /b 1)

set "HERE=%~dp0"
"%CSC%" /nologo /target:library /out:"%GAME%\BepInEx\plugins\HelixSRBridge.dll" ^
  /r:"%GAME%\BepInEx\core\BepInEx.dll" ^
  /r:"%MANAGED%\UnityEngine.dll" /r:"%MANAGED%\UnityEngine.CoreModule.dll" ^
  "%HERE%src\HelixMath.cs" "%HERE%src\NativeBridge.cs" "%HERE%src\HelixSRBridgePlugin.cs"
if errorlevel 1 exit /b 1

rem helixsr_unity.dll next to the game's exe (the exe folder is the one holding UnityPlayer.dll)
copy /y "%HERE%prebuilt\helixsr_unity.dll" "%GAME%\helixsr_unity.dll" >nul
echo Built BepInEx\plugins\HelixSRBridge.dll and copied helixsr_unity.dll into "%GAME%".
endlocal
