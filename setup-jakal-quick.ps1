#Requires -Version 5.1
<#
.SYNOPSIS
    JAKAL Enterprise Penetration Testing Platform — Windows / PowerShell Quick Setup
.DESCRIPTION
    PowerShell equivalent of setup-jakal-quick.sh, for Windows machines that
    aren't running WSL/Ubuntu. Same 8 steps, same result: a working local
    venv with backend/requirements.txt installed and backend/.env created.
.USAGE
    powershell -ExecutionPolicy Bypass -File setup-jakal-quick.ps1
    (or, from an already-elevated PowerShell prompt: .\setup-jakal-quick.ps1)
#>

$ErrorActionPreference = "Stop"

function Write-Banner {
    Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║   JAKAL Enterprise Penetration Testing Platform                ║" -ForegroundColor Cyan
    Write-Host "║   Windows / PowerShell Quick Setup                              ║" -ForegroundColor Cyan
    Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    Write-Host ""
}

Write-Banner

# ============================================================================
# STEP 1: Check prerequisites
# ============================================================================
Write-Host "[1/8] Checking prerequisites..." -ForegroundColor Yellow

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

if (-not (Test-Command git)) {
    Write-Host "❌ git not found. Install it from https://git-scm.com/download/win and re-run this script." -ForegroundColor Red
    exit 1
}

$pythonCmd = $null
foreach ($cand in @("python3.11", "python3", "python")) {
    if (Test-Command $cand) {
        $verOutput = & $cand --version 2>&1
        if ($verOutput -match "3\.(1[1-9]|[2-9]\d)") {
            $pythonCmd = $cand
            break
        }
    }
}
if (-not $pythonCmd) {
    Write-Host "❌ Python 3.11+ not found on PATH." -ForegroundColor Red
    Write-Host "   Install it from https://www.python.org/downloads/ (check 'Add python.exe to PATH')," -ForegroundColor Red
    Write-Host "   or via winget: winget install Python.Python.3.11" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Prerequisites OK (python: $pythonCmd)" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 2: Clone repository
# ============================================================================
Write-Host "[2/8] Cloning repository..." -ForegroundColor Yellow

$RepoDir = Join-Path $HOME "Enterprise-Application"

if (Test-Path $RepoDir) {
    Write-Host "Repository already exists. Updating..."
    Push-Location $RepoDir
    git pull origin main
    Pop-Location
} else {
    git clone https://github.com/thepeoplesrealty100-ops/Enterprise-Application.git $RepoDir
}

Set-Location $RepoDir
Write-Host "✅ Repository ready at $RepoDir" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 3: Create virtual environment
# ============================================================================
Write-Host "[3/8] Creating Python virtual environment..." -ForegroundColor Yellow

if (Test-Path "venv") {
    Remove-Item -Recurse -Force "venv"
}

& $pythonCmd -m venv venv
$ActivateScript = Join-Path $RepoDir "venv\Scripts\Activate.ps1"
. $ActivateScript

Write-Host "✅ Virtual environment created" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 4: Upgrade pip
# ============================================================================
Write-Host "[4/8] Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip setuptools wheel
Write-Host "✅ Pip upgraded" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 5: Install dependencies
# ============================================================================
Write-Host "[5/8] Installing Python dependencies..." -ForegroundColor Yellow
pip install -r backend\requirements.txt
Write-Host "✅ Dependencies installed" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 6: Create directories
# ============================================================================
Write-Host "[6/8] Creating application directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "data", "logs", "backups" | Out-Null
Write-Host "✅ Directories created" -ForegroundColor Green
Write-Host ""

# ============================================================================
# STEP 7: Create environment file
# ============================================================================
Write-Host "[7/8] Configuring backend environment..." -ForegroundColor Yellow

$EnvPath = "backend\.env"
if (Test-Path $EnvPath) {
    Write-Host "⚠️  backend\.env already exists (skipping)" -ForegroundColor DarkYellow
} else {
    $envContent = @"
# JAKAL Backend Configuration
# Update CLAUDE_API_KEY with your Anthropic API key from https://console.anthropic.com

# Server Configuration
HOST=0.0.0.0
PORT=8000
ENVIRONMENT=development

# Claude LLM (REQUIRED - add your API key)
LLM_ENGINE=claude
CLAUDE_API_KEY=sk-ant-your-api-key-here
CLAUDE_MODEL=claude-3-5-sonnet-20241022

# Ollama (local fallback - optional)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# Database
DUCKDB_PATH=./jakal.duckdb

# Security Tools
NMAP_TIMEOUT=120
NUCLEI_TIMEOUT=120

# Optional
IBM_QUANTUM_TOKEN=
SHODAN_API_KEY=
"@
    Set-Content -Path $EnvPath -Value $envContent -Encoding UTF8
    Write-Host "✅ Created backend\.env" -ForegroundColor Green
}
Write-Host ""

# ============================================================================
# STEP 8: Verify installation
# ============================================================================
Write-Host "[8/8] Verifying installation..." -ForegroundColor Yellow

$verifyScript = @"
import sys
modules = {'anthropic': 'Anthropic SDK', 'fastapi': 'FastAPI', 'uvicorn': 'Uvicorn', 'duckdb': 'DuckDB'}
all_ok = True
for mod, name in modules.items():
    try:
        __import__(mod)
        print(f'  [OK] {name}')
    except ImportError:
        print(f'  [MISSING] {name}')
        all_ok = False
print('\nAll dependencies verified!' if all_ok else '\nSome modules missing.')
"@
$verifyScript | python -

Write-Host ""

# ============================================================================
# Final message
# ============================================================================
Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                   ✅ SETUP COMPLETE                              ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "📋 IMPORTANT - Add your Claude API key:" -ForegroundColor Yellow
Write-Host ""
Write-Host "   notepad $RepoDir\backend\.env"
Write-Host ""
Write-Host "   Replace this line with your actual key:"
Write-Host "   CLAUDE_API_KEY=sk-ant-your-api-key-here"
Write-Host ""
Write-Host "   Get free key at: https://console.anthropic.com/account/keys"
Write-Host ""
Write-Host "════════════════════════════════════════════════════════════════"
Write-Host ""
Write-Host "🚀 START THE APPLICATION:" -ForegroundColor Green
Write-Host ""
Write-Host "   cd $RepoDir"
Write-Host "   .\venv\Scripts\Activate.ps1"
Write-Host "   python -m uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000"
Write-Host ""
Write-Host "   Then visit: http://localhost:8000/docs"
Write-Host ""
Write-Host "════════════════════════════════════════════════════════════════"
Write-Host ""
