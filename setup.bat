@echo off
REM ================================================================
REM  SU Member Verifier — Windows One-Click Setup
REM  Double-click this file. It installs everything automatically.
REM ================================================================
echo.
echo  ============================================
echo   SU Member Verifier — Setup
echo  ============================================
echo.

REM --- Check for Python ---
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo  [ERROR] Python is not installed.
    echo.
    echo  Please install Python first:
    echo    1. Open Microsoft Store
    echo    2. Search "Python 3.12"
    echo    3. Click Install
    echo    4. Re-run this script
    echo.
    pause
    exit /b 1
)
echo  [OK] Python found

REM --- Create virtual environment ---
if not exist ".venv" (
    echo  Creating virtual environment...
    python -m venv .venv
)
echo  [OK] Virtual environment ready

REM --- Install dependencies ---
echo  Installing dependencies...
call .venv\Scripts\pip install -e . --quiet
echo  [OK] Dependencies installed

REM --- Install Playwright browser ---
echo  Installing Chromium browser (one-time download, ~150MB)...
call .venv\Scripts\playwright install chromium
echo  [OK] Chromium installed

REM --- Check for .env ---
if not exist ".env" (
    echo  Creating .env from template...
    copy .env.example .env >nul
    echo  [NOTE] Edit .env with your Discord token and other settings
)

echo.
echo  ============================================
echo   Setup complete!
echo  ============================================
echo.
echo  Next steps:
echo    1. Edit .env with your Discord bot token, guild ID, and role ID
echo    2. Create a Google Form with these fields:
echo       - Discord Username (short answer)
echo       - Student Email (short answer)  
echo    3. Run: .venv\Scripts\su-verify status   (to check config)
echo    4. Run: .venv\Scripts\su-verify scrape   (to get SU member list)
echo    5. Run: .venv\Scripts\su-verify run      (to verify + assign roles)
echo.
echo  For help, read README.md
echo.
pause
