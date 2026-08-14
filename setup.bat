@echo off
REM JAKAL Phase 2 Setup Script - Windows PowerShell

echo ============================================================================
echo JAKAL Phase 2: Local Setup & Dependencies
echo ============================================================================

cd /d C:\Users\Freddy\projects\JAKAL

REM Create virtual environment
echo.
echo Creating Python virtual environment...
python -m venv venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment
    echo Please ensure Python is installed and in PATH
    pause
    exit /b 1
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip

REM Install dependencies
echo.
echo Installing Python dependencies...
echo This may take 5-10 minutes...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo ============================================================================
echo Setup Complete!
echo ============================================================================
echo.
echo To start the backend:
echo   1. Open PowerShell in project root: C:\Users\Freddy\projects\JAKAL
echo   2. Run: .\venv\Scripts\Activate.ps1
echo   3. Run: python backend/app.py
echo.
echo To test endpoints:
echo   - Visit: http://localhost:8000/health
echo   - API docs: http://localhost:8000/docs
echo.
pause
