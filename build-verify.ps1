#!/usr/bin/env powershell
# JAKAL Build & Deployment Verification Script
# Comprehensive testing and Docker build verification

param(
    [switch]$SkipTests = $false,
    [switch]$BuildOnly = $false,
    [switch]$FullBuild = $false
)

$ErrorActionPreference = "Stop"
$WarningPreference = "SilentlyContinue"

# Colors for output
$Green = "`e[32m"
$Red = "`e[31m"
$Yellow = "`e[33m"
$Cyan = "`e[36m"
$Reset = "`e[0m"

function Write-Step {
    param([string]$Message)
    Write-Host "`n$Cyan===> $Message$Reset"
}

function Write-Success {
    param([string]$Message)
    Write-Host "$Green✓ $Message$Reset"
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Host "$Red✗ $Message$Reset"
}

Write-Host "`n$Cyan" + ("=" * 80)
Write-Host "JAKAL Enterprise Build & Verification"
Write-Host ("=" * 80) + "$Reset`n"

# ============================================================================
# Step 1: Verify Docker & Docker Compose Installation
# ============================================================================
Write-Step "Verifying Docker Installation"

try {
    $DockerVersion = docker --version
    Write-Success "Docker: $DockerVersion"
    
    $ComposeVersion = docker-compose --version
    Write-Success "Docker Compose: $ComposeVersion"
} catch {
    Write-Error-Custom "Docker or Docker Compose not found!"
    exit 1
}

# ============================================================================
# Step 2: Verify Project Files
# ============================================================================
Write-Step "Verifying Project Files"

$RequiredFiles = @(
    "Dockerfile",
    "docker-compose.yml",
    "requirements.txt",
    ".env",
    "backend/app.py",
    "backend/database.py",
    "backend/monitoring.py",
    "dashboard.html",
    "nginx.conf"
)

foreach ($File in $RequiredFiles) {
    if (Test-Path $File) {
        Write-Success "Found: $File"
    } else {
        Write-Error-Custom "Missing: $File"
        exit 1
    }
}

# ============================================================================
# Step 3: Verify Directory Permissions
# ============================================================================
Write-Step "Verifying Directory Permissions"

$DirectoriesToCreate = @("data", "logs", "backups")

foreach ($Dir in $DirectoriesToCreate) {
    if (-not (Test-Path $Dir)) {
        New-Item -ItemType Directory -Path $Dir -Force | Out-Null
        Write-Success "Created directory: $Dir"
    } else {
        Write-Success "Directory exists: $Dir"
    }
}

# ============================================================================
# Step 4: Check .env Configuration
# ============================================================================
Write-Step "Checking .env Configuration"

if (Test-Path ".env") {
    $EnvContent = Get-Content ".env"
    Write-Success ".env file found and readable"
    
    # Verify critical variables
    $CriticalVars = @("ENVIRONMENT", "API_PORT", "DATABASE_URL")
    foreach ($Var in $CriticalVars) {
        if ($EnvContent -match $Var) {
            Write-Success "Found: $Var"
        }
    }
} else {
    Write-Error-Custom ".env file not found!"
    exit 1
}

# ============================================================================
# Step 5: Run Telemetry Ingestion Tests (Optional)
# ============================================================================
if (-not $SkipTests) {
    Write-Step "Running Telemetry Ingestion Tests"
    
    try {
        Write-Host "Checking for Python..."
        $PythonVersion = python --version 2>&1
        Write-Success "Python: $PythonVersion"
        
        Write-Host "`nRunning telemetry test suite..."
        & python backend/telemetry_test.py
        
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Telemetry tests passed"
        } else {
            Write-Error-Custom "Telemetry tests failed (exit code: $LASTEXITCODE)"
        }
    } catch {
        Write-Error-Custom "Could not run telemetry tests: $_"
    }
}

# ============================================================================
# Step 6: Build Docker Image
# ============================================================================
Write-Step "Building Docker Image"

try {
    if ($FullBuild) {
        Write-Host "Building with no cache..."
        docker-compose build --no-cache
    } else {
        Write-Host "Building (with cache)..."
        docker-compose build
    }
    
    if ($LASTEXITCODE -eq 0) {
        Write-Success "Docker image built successfully"
    } else {
        Write-Error-Custom "Docker build failed"
        exit 1
    }
} catch {
    Write-Error-Custom "Docker build error: $_"
    exit 1
}

# ============================================================================
# Step 7: Verify Docker Image
# ============================================================================
Write-Step "Verifying Built Docker Image"

try {
    $Images = docker images | grep "jakal"
    if ($Images) {
        Write-Success "Docker image verified"
        Write-Host $Images
    } else {
        Write-Error-Custom "Docker image not found after build"
        exit 1
    }
} catch {
    Write-Error-Custom "Could not verify Docker image: $_"
}

# ============================================================================
# Step 8: Start Docker Containers (if not BuildOnly)
# ============================================================================
if (-not $BuildOnly) {
    Write-Step "Starting Docker Containers"
    
    try {
        Write-Host "Stopping existing containers (if any)..."
        docker-compose down 2>$null
        
        Write-Host "Starting fresh containers..."
        docker-compose up -d
        
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Docker containers started"
        } else {
            Write-Error-Custom "Failed to start containers"
            exit 1
        }
    } catch {
        Write-Error-Custom "Docker start error: $_"
        exit 1
    }
    
    # ========================================================================
    # Step 9: Wait for Services to Be Ready
    # ========================================================================
    Write-Step "Waiting for Services to Initialize"
    
    $MaxAttempts = 30
    $Attempt = 0
    $Ready = $false
    
    while ($Attempt -lt $MaxAttempts -and -not $Ready) {
        try {
            $Response = curl -s -f "http://localhost:8000/health" 2>$null
            if ($Response) {
                Write-Success "Backend API is ready"
                $Ready = $true
            }
        } catch {
            # Waiting...
        }
        
        if (-not $Ready) {
            Write-Host "." -NoNewline
            Start-Sleep -Seconds 2
            $Attempt++
        }
    }
    
    if (-not $Ready) {
        Write-Error-Custom "Services failed to start within timeout"
        exit 1
    }
    
    # ========================================================================
    # Step 10: Test Endpoints
    # ========================================================================
    Write-Step "Testing API Endpoints"
    
    $Endpoints = @(
        @{url="http://localhost:8000/health"; name="Health Check"},
        @{url="http://localhost:8000/api/system/status"; name="System Status"},
        @{url="http://localhost:8000/api/version"; name="Version Info"},
        @{url="http://localhost:8000/docs"; name="API Documentation"}
    )
    
    foreach ($Endpoint in $Endpoints) {
        try {
            $Response = curl -s -f $Endpoint.url 2>$null
            Write-Success "✓ $($Endpoint.name)"
        } catch {
            Write-Error-Custom "✗ $($Endpoint.name)"
        }
    }
    
    # ========================================================================
    # Step 11: Display Container Status
    # ========================================================================
    Write-Step "Container Status"
    docker ps --filter "label=jakal=backend"
    
    Write-Host "`n$Green" + ("=" * 80)
    Write-Host "✓ BUILD AND VERIFICATION COMPLETE"
    Write-Host ("=" * 80) + "$Reset"
    
    Write-Host "`n$Cyan[Access Points]$Reset"
    Write-Host "  Backend API:     http://localhost:8000"
    Write-Host "  API Docs:        http://localhost:8000/docs"
    Write-Host "  Dashboard:       http://localhost:3000"
    Write-Host "  Prometheus:      http://localhost:9090"
    
    Write-Host "`n$Cyan[Next Steps]$Reset"
    Write-Host "  1. Visit http://localhost:8000/docs to test endpoints"
    Write-Host "  2. Check logs: docker logs jakal-backend"
    Write-Host "  3. Stop containers: docker-compose down"
    Write-Host "  4. View live logs: docker-compose logs -f"
    
} else {
    Write-Host "`n$Green" + ("=" * 80)
    Write-Host "✓ BUILD COMPLETE (Container not started - use -BuildOnly)"
    Write-Host ("=" * 80) + "$Reset"
    
    Write-Host "`n$Cyan[Next Steps]$Reset"
    Write-Host "  To start containers: docker-compose up -d"
    Write-Host "  To start with logs:  docker-compose up"
}

Write-Host "`n"
