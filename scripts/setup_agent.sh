#!/usr/bin/env bash
# setup_agent.sh — Automated installation of Agentic AI + ML dependencies
#
# Installs all required libraries into the existing .venv without
# breaking existing trading dependencies.
#
# Usage:
#   chmod +x scripts/setup_agent.sh
#   ./scripts/setup_agent.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_ROOT/.venv"

echo "============================================================"
echo "  AGENTIC AI SETUP — Linux/macOS"
echo "============================================================"

# ── 1. Verify .venv exists ──────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "❌ .venv not found at $VENV_DIR"
    echo "   Create it first: python3 -m venv .venv && source .venv/bin/activate"
    exit 1
fi

PIP="$VENV_DIR/bin/pip"
PYTHON="$VENV_DIR/bin/python"

if [ ! -f "$PIP" ]; then
    echo "❌ pip not found in .venv"
    exit 1
fi

echo "✅ Using venv: $VENV_DIR"
echo "   Python: $($PYTHON --version 2>&1)"
echo ""

# ── 2. Install Agentic AI dependencies ──────────────────────────
echo "📦 Installing Agentic AI dependencies..."

# Core ML / NLP (lightweight, no GPU required)
$PIP install --quiet \
    "scikit-learn>=1.3,<2.0" \
    "numpy>=1.24,<3.0" \
    "scipy>=1.11,<2.0"

# LLM / Agent framework support
$PIP install --quiet \
    "requests>=2.31,<3.0"

# Playwright (if not already installed)
if ! $PYTHON -c "import playwright" 2>/dev/null; then
    echo "📦 Installing Playwright..."
    $PIP install --quiet "playwright>=1.40,<2.0"
    $PYTHON -m playwright install chromium
fi

# Optional: LangChain (for advanced agent orchestration)
# Uncomment if you want to use LangChain instead of the built-in orchestrator
# $PIP install --quiet "langchain>=0.1,<0.3" "langchain-community>=0.0.20"

# Optional: CrewAI (for CrewAI-based multi-agent)
# $PIP install --quiet "crewai>=0.1,<0.5"

# Optional: PyTorch (for CUDA-aware ML models)
# Uncomment if you need GPU-accelerated ML
# $PIP install --quiet torch --index-url https://download.pytorch.org/whl/cu121

echo "✅ Agentic AI dependencies installed"
echo ""

# ── 3. Verify existing trading deps still work ──────────────────
echo "🔍 Verifying existing trading dependencies..."
TRADE_DEPS=("fastapi" "uvicorn" "sqlalchemy" "pandas" "yfinance")
for dep in "${TRADE_DEPS[@]}"; do
    if $PYTHON -c "import $dep" 2>/dev/null; then
        echo "  ✅ $dep"
    else
        echo "  ⚠️  $dep not found (may need separate install)"
    fi
done
echo ""

# ── 4. Verify new Agentic AI deps ───────────────────────────────
echo "🔍 Verifying Agentic AI dependencies..."
AGENT_DEPS=("sklearn" "numpy" "scipy" "playwright" "requests")
for dep in "${AGENT_DEPS[@]}"; do
    if $PYTHON -c "import $dep" 2>/dev/null; then
        echo "  ✅ $dep"
    else
        echo "  ❌ $dep FAILED"
    fi
done
echo ""

# ── 5. Verify Ollama (optional) ─────────────────────────────────
if command -v ollama &>/dev/null; then
    echo "✅ Ollama detected: $(ollama --version 2>&1 || echo 'version unknown')"
    if ! ollama list 2>/dev/null | grep -q "deepseek"; then
        echo "   💡 Recommended: ollama pull deepseek-r1:1.5b"
    fi
else
    echo "⚠️  Ollama not found. Install from https://ollama.ai for local LLM support."
    echo "   Agents will use rule-based fallback without Ollama."
fi
echo ""

# ── 6. Test import ──────────────────────────────────────────────
echo "🧪 Testing agentic module import..."
if $PYTHON -c "from quant.agentic import AgenticOrchestrator; print('OK')" 2>&1; then
    echo "✅ Agentic AI module imports successfully"
else
    echo "❌ Agentic AI module import failed"
    exit 1
fi

echo ""
echo "============================================================"
echo "  ✅ SETUP COMPLETE"
echo "============================================================"
echo ""
echo "  Next steps:"
echo "    1. Start Ollama: ollama serve"
echo "    2. Start backend: uvicorn quant.api.app:app --port 8000"
echo "    3. Start frontend: cd frontend && npm run dev"
echo "    4. Run agentic loop:"
echo "       python -c \"from quant.agentic import AgenticOrchestrator, ToolRegistry"
echo "       orch = AgenticOrchestrator(tools=ToolRegistry.create())"
echo "       result = orch.run(task='Add health check endpoint')\""
echo ""
