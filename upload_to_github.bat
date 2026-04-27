@echo off
setlocal EnableDelayedExpansion
echo ==========================================
echo   Hand Gesture Control - GitHub Uploader
echo ==========================================
echo.

:: 1. Initialize Git First
if not exist .git (
    echo [1/6] Initializing Git repository...
    git init
) else (
    echo [1/6] Git repository found.
)

:: 2. Configure Identity (Local Repo Only - More Reliable)
echo.
echo [2/6] Configuring Git Identity...
echo   Please enter your info slightly differently this time.
echo.

set /p GIT_NAME="Enter your Name: "
set /p GIT_EMAIL="Enter your Email: "

:: Force set local config
git config user.name "!GIT_NAME!"
git config user.email "!GIT_EMAIL!"

:: Verify it stuck
echo.
echo   Verifying config...
git config user.name
git config user.email
echo.

:: 3. Add Files
echo [3/6] Adding files...
git add .

:: 4. Commit
echo [4/6] Committing changes...
git commit -m "Initial upload by Agent"

:: 5. Link to GitHub
echo [5/6] Linking to GitHub...
git remote remove origin 2>nul
git remote add origin https://github.com/Aman130901/-hand-gesture-control.git
git branch -M main

:: 6. Push
echo.
echo [6/6] Pushing to GitHub...
echo.
echo    Please sign in if a browser window pops up!
echo.
git push -u origin main

echo.
echo ==========================================
if %errorlevel% equ 0 (
    echo   SUCCESS! Project uploaded.
) else (
    echo   ERROR: Push failed.
    echo   If "src refspec main does not match any" appears, the commit failed.
)
echo ==========================================
pause
