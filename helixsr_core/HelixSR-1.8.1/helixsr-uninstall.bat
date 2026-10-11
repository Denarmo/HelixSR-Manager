@echo off
rem HelixSR uninstaller: removes HelixSR from your games and puts back what it replaced (see helixsr-uninstall.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0helixsr-uninstall.ps1" %*
pause
