#!/bin/bash

# JAKAL Enterprise Application - Ubuntu Quick Setup Script
# Fast, reliable installation with error handling
# Usage: bash setup-jakal-quick.sh

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   JAKAL Enterprise Penetration Testing Platform               ║"
echo "║   Ubuntu Quick Setup                                          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# ============================================================================
# STEP 1: Check prerequisites
# ============================================================================
echo "[1/8] Checking prerequisites..."

if ! command -v git &> /dev/null; then
    echo "Installing git..."
    sudo apt-get update && sudo apt-get install -y git
fi

if ! command -v python3.11 &> /dev/null; then
    echo "Installing Python 3.11..."
    sudo apt-get update && sudo apt-get install -y python3.11 python3.11-venv python3.11-dev
fi

echo "✅ Prerequisites OK"
echo ""

# ============================================================================
# STEP 2: Clone repository
# ============================================================================
echo "[2/8] Cloning repository..."

REPO_DIR="$HOME/Enterprise-Application"

if [ -d "$REPO_DIR" ]; then
    echo "Repository already exists. Updating..."
    cd "$REPO_DIR"
    git pull origin main
else
    git clone https://github.com/thepeoplesrealty100-ops/Enterprise-Application.git "$REPO_DIR"
fi

cd "$REPO_DIR"
echo "✅ Repository ready at $REPO_DIR"
echo ""

# ============================================================================
# STEP 3: Create virtual environment
# ============================================================================
echo "[3/8] Creating Python 3.11 virtual environment..."

if [ -d "venv" ]; then
    rm -rf venv
fi

python3.11 -m venv venv
source venv/bin/activate

echo "✅ Virtual environment created"
echo ""

# ============================================================================
# STEP 4: Upgrade pip
# ============================================================================
echo "[4/8] Upgrading pip..."

pip install --upgrade pip setuptools wheel

echo "✅ Pip upgraded"
echo ""

# ============================================================================
# STEP 5: Install dependencies
# ============================================================================
echo "[5/8] Installing Python dependencies..."

pip install -r backend/requirements.txt

echo "✅ Dependencies installed"
echo ""

# ============================================================================
# STEP 6: Create directories
# ============================================================================
echo "[6/8] Creating application directories..."

mkdir -p data logs backups

echo "✅ Directories created"
echo ""

# ============================================================================
# STEP 7: Create environment file
# ============================================================================
echo "[7/8] Configuring backend environment..."

if [ -f "backend/.env" ]; then
    echo "⚠️  backend/.env already exists (skipping)"
else
    # If CLAUDE_API_KEY is already set in your shell environment, it's picked
    # up automatically. Otherwise a placeholder is written for you to edit —
    # never a real key. See https://console.anthropic.com/account/keys.
    CLAUDE_KEY_VALUE="${CLAUDE_API_KEY:-sk-ant-your-api-key-here}"
    # v2.5: JAKAL_MASTER_KEY wraps persisted encryption session keys (see
    # crypto/encryption_manager.py). Unlike the Claude key this isn't a
    # credential you have to obtain — it's safe (and correct) to generate
    # a random one locally right now, once, so it stays stable across
    # restarts instead of leaving encrypted data unrecoverable.
    if [ -n "${JAKAL_MASTER_KEY:-}" ]; then
        MASTER_KEY_VALUE="${JAKAL_MASTER_KEY}"
    elif command -v openssl >/dev/null 2>&1; then
        MASTER_KEY_VALUE="$(openssl rand -hex 32)"
    else
        MASTER_KEY_VALUE="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    fi
    cat > backend/.env << ENVEOF
# JAKAL Backend Configuration
# Update CLAUDE_API_KEY with your Anthropic API key from https://console.anthropic.com

# Server Configuration
HOST=0.0.0.0
PORT=8000
ENVIRONMENT=development

# Claude LLM (REQUIRED - add your API key)
LLM_ENGINE=claude
CLAUDE_API_KEY=${CLAUDE_KEY_VALUE}
CLAUDE_MODEL=claude-3-5-sonnet-20241022

# Encryption key wrapping (auto-generated locally — do not share/commit)
JAKAL_MASTER_KEY=${MASTER_KEY_VALUE}

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
ENVEOF
    echo "✅ Created backend/.env"
fi

echo ""

# ============================================================================
# STEP 8: Verify installation
# ============================================================================
echo "[8/8] Verifying installation..."

python3 << 'PYEOF'
import sys
modules = {
    'anthropic': 'Anthropic SDK',
    'fastapi': 'FastAPI',
    'uvicorn': 'Uvicorn',
    'duckdb': 'DuckDB'
}

all_ok = True
for mod, name in modules.items():
    try:
        __import__(mod)
        print(f"  ✅ {name}")
    except ImportError:
        print(f"  ❌ {name}")
        all_ok = False

if all_ok:
    print("\n✅ All dependencies verified!")
else:
    print("\n⚠️  Some modules missing (but this shouldn't happen)")
PYEOF

echo ""

# ============================================================================
# Final message
# ============================================================================
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                   ✅ SETUP COMPLETE                            ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "📋 IMPORTANT - Add your Claude API key:"
echo ""
echo "   nano $REPO_DIR/backend/.env"
echo ""
echo "   Replace this line with your actual key:"
echo "   CLAUDE_API_KEY=sk-ant-your-api-key-here"
echo ""
echo "   Get free key at: https://console.anthropic.com/account/keys"
echo ""
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "🚀 START THE APPLICATION:"
echo ""
echo "   cd $REPO_DIR"
echo "   source venv/bin/activate"
echo "   python3 -m uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000"
echo ""
echo "   Then visit: http://localhost:8000/docs"
echo ""
echo "════════════════════════════════════════════════════════════════"
echo ""
