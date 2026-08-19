# ──────────────────────────────────────────────────────────────────────
# Quant Trading System — Windows venv activation & setup (PowerShell)
# ──────────────────────────────────────────────────────────────────────
# Usage:  .\activate.ps1
# ──────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ScriptDir ".venv"

if (-not (Test-Path $VenvDir)) {
    Write-Host "Creating .venv ..."
    python -m venv $VenvDir
}

# Activate
$ActivateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
if (Test-Path $ActivateScript) {
    & $ActivateScript
} else {
    Write-Error "Cannot find venv activation script at $ActivateScript"
    exit 1
}

# Upgrade pip
pip install --upgrade pip setuptools wheel *> $null

# Install core deps
pip install -r (Join-Path $ScriptDir "requirements.txt")

Write-Host ""
Write-Host "Virtual environment activated: $VenvDir"
Write-Host ""
Write-Host "To install CUDA torch:"
Write-Host "  pip install torch --index-url https://download.pytorch.org/whl/cu121"
Write-Host ""
Write-Host "To install CPU-only torch:"
Write-Host "  pip install torch --index-url https://download.pytorch.org/whl/cpu"
Write-Host ""
Write-Host "To install optional ML/RL/NLP deps:"
Write-Host "  pip install -r requirements-optional.txt"
