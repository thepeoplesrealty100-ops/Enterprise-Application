# JAKAL Phase 2 Setup Script - Windows PowerShell

Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "JAKAL Phase 2: Local Setup & Dependencies" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan

Set-Location "C:\Users\Freddy\projects\JAKAL"

# Create virtual environment
Write-Host ""
Write-Host "Creating Python virtual environment..." -ForegroundColor Yellow
python -m venv venv
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to create virtual environment" -ForegroundColor Red
    Write-Host "Please ensure Python is installed and in PATH" -ForegroundColor Red
    exit 1
}

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Yellow
& ".\venv\Scripts\Activate.ps1"

# Upgrade pip
Write-Host "Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip

# Install dependencies
Write-Host ""
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
Write-Host "This may take 5-10 minutes..." -ForegroundColor Yellow
pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install dependencies" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================================================" -ForegroundColor Green
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "============================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start the backend:" -ForegroundColor Cyan
Write-Host "  1. Open PowerShell in project root: C:\Users\Freddy\projects\JAKAL" -ForegroundColor White
Write-Host "  2. Run: .\venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "  3. Run: python backend/app.py" -ForegroundColor White
Write-Host ""
Write-Host "To test endpoints:" -ForegroundColor Cyan
Write-Host "  - Health check: http://localhost:8000/health" -ForegroundColor White
Write-Host "  - API docs: http://localhost:8000/docs" -ForegroundColor White
Write-Host ""
