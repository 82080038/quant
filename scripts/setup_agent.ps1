# setup_agent.ps1 — Automated installation of Agentic AI + ML dependencies (Windows)
#
# Installs all required libraries into the existing .venv without
# breaking existing trading dependencies.
#
# Usage:
#   .\scripts\setup_agent.ps1

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$VenvDir = Join-Path $ProjectRoot ".venv"

Write-Host "============================================================"
Write-Host "  AGENTIC AI SETUP — Windows"
Write-Host "============================================================"

# ── 1. Verify .venv exists ──────────────────────────────────────
if (-not (Test-Path $VenvDir)) {
    Write-Host "❌ .venv not found at $VenvDir"
    Write-Host "   Create it first: python -m venv .venv ; .\.venv\Scripts\Activate.ps1"
    exit 1
}

$Python = Join-Path $VenvDir "Scripts\python.exe"
$Pip = Join-Path $VenvDir "Scripts\pip.exe"

if (-not (Test-Path $Pip)) {
    Write-Host "❌ pip not found in .venv"
    exit 1
}

Write-Host "✅ Using venv: $VenvDir"
Write-Host "   Python: (& $Python --version)"
Write-Host ""

# ── 2. Install Agentic AI dependencies ──────────────────────────
Write-Host "📦 Installing Agentic AI dependencies..."

# Core ML / NLP (lightweight, no GPU required)
& $Pip install --quiet `
    "scikit-learn>=1.3,<2.0" `
    "numpy>=1.24,<3.0" `
    "scipy>=1.11,<2.0"

# LLM / Agent framework support
& $Pip install --quiet `
    "requests>=2.31,<3.0"

# Playwright (if not already installed)
$hasPlaywright = & $Python -c "import playwright; print('yes')" 2>$null
if ($hasPlaywright -ne "yes") {
    Write-Host "📦 Installing Playwright..."
    & $Pip install --quiet "playwright>=1.40,<2.0"
    & $Python -m playwright install chromium
}

# Optional: PyTorch (for CUDA-aware ML models)
# Uncomment if you need GPU-accelerated ML
# & $Pip install --quiet torch --index-url https://download.pytorch.org/whl/cu121

Write-Host "✅ Agentic AI dependencies installed"
Write-Host ""

# ── 3. Verify existing trading deps still work ──────────────────
Write-Host "🔍 Verifying existing trading dependencies..."
$TradeDeps = @("fastapi", "uvicorn", "sqlalchemy", "pandas", "yfinance")
foreach ($dep in $TradeDeps) {
    $result = & $Python -c "import $dep; print('ok')" 2>$null
    if ($result -eq "ok") {
        Write-Host "  ✅ $dep"
    } else {
        Write-Host "  ⚠️  $dep not found (may need separate install)"
    }
}
Write-Host ""

# ── 4. Verify new Agentic AI deps ───────────────────────────────
Write-Host "🔍 Verifying Agentic AI dependencies..."
$AgentDeps = @("sklearn", "numpy", "scipy", "playwright", "requests")
foreach ($dep in $AgentDeps) {
    $result = & $Python -c "import $dep; print('ok')" 2>$null
    if ($result -eq "ok") {
        Write-Host "  ✅ $dep"
    } else {
        Write-Host "  ❌ $dep FAILED"
    }
}
Write-Host ""

# ── 5. Verify Ollama (optional) ─────────────────────────────────
$ollamaPath = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaPath) {
    Write-Host "✅ Ollama detected"
} else {
    Write-Host "⚠️  Ollama not found. Install from https://ollama.ai for local LLM support."
    Write-Host "   Agents will use rule-based fallback without Ollama."
}
Write-Host ""

# ── 6. Test import ──────────────────────────────────────────────
Write-Host "🧪 Testing agentic module import..."
$importResult = & $Python -c "from quant.agentic import AgenticOrchestrator; print('OK')" 2>&1
if ($importResult -eq "OK") {
    Write-Host "✅ Agentic AI module imports successfully"
} else {
    Write-Host "❌ Agentic AI module import failed: $importResult"
    exit 1
}

Write-Host ""
Write-Host "============================================================"
Write-Host "  ✅ SETUP COMPLETE"
Write-Host "============================================================"
