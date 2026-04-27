@echo off
title Hand2.0 Enterprise Controller
echo Starting Hand Gesture Control System (Enterprise Edition)...
echo.
echo [INFO] Initializing Camera...
echo [INFO] Starting Flask Server...
echo [INFO] Launching Desktop Interface...
echo.

:: Ensure we are in the correct directory
cd /d "%~dp0"

:: Run the desktop application
python desktop_app.py
echo.
echo Application Closed.
pause
