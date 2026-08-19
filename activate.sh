#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# Quant Trading System — Cross-platform venv activation & setup
# ──────────────────────────────────────────────────────────────────────
# Usage:
#   Linux/macOS:  source activate.sh
#   Windows:      .\activate.ps1  (or run activate.bat)
# ──────────────────────────────────────────────────────────────────────

# Detect OS
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OS" == "Windows_NT" ]]; then
    echo "Windows detected — use activate.ps1 or activate.bat instead"
    return 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating .venv ..."
    python3 -m venv "$VENV_DIR"
fi

# Activate
source "$VENV_DIR/bin/activate"

# Upgrade pip
pip install --upgrade pip setuptools wheel >/dev/null 2>&1

# Install core deps
pip install -r "$SCRIPT_DIR/requirements.txt"

echo ""
echo "✓ Virtual environment activated: $VENV_DIR"
echo ""
echo "To install CUDA torch:"
echo "  pip install torch --index-url https://download.pytorch.org/whl/cu121"
echo ""
echo "To install CPU-only torch:"
echo "  pip install torch --index-url https://download.pytorch.org/whl/cpu"
echo ""
echo "To install optional ML/RL/NLP deps:"
echo "  pip install -r requirements-optional.txt"
