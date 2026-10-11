@echo off
rem HelixSR setup: builds the network into nvngx.dll and installs HelixSR into your games (see helixsr-setup.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0helixsr-setup.ps1" %*
pause
