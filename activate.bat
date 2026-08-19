@echo off
REM ──────────────────────────────────────────────────────────────────────
REM Quant Trading System — Windows venv activation (CMD)
REM Usage: activate.bat
REM ──────────────────────────────────────────────────────────────────────

set SCRIPT_DIR=%~dp0
set VENV_DIR=%SCRIPT_DIR%.venv

if not exist "%VENV_DIR%" (
    echo Creating .venv ...
    python -m venv "%VENV_DIR%"
)

call "%VENV_DIR%\Scripts\activate.bat"

pip install --upgrade pip setuptools wheel >nul 2>&1
pip install -r "%SCRIPT_DIR%requirements.txt"

echo.
echo Virtual environment activated: %VENV_DIR%
echo.
echo To install CUDA torch:
echo   pip install torch --index-url https://download.pytorch.org/whl/cu121
echo.
echo To install CPU-only torch:
echo   pip install torch --index-url https://download.pytorch.org/whl/cpu
echo.
echo To install optional ML/RL/NLP deps:
echo   pip install -r requirements-optional.txt
