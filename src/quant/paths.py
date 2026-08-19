"""Cross-platform path defaults for Linux and Windows developer machines.

The application is developed on both Linux (original: /opt/lampp/htdocs/market)
and Windows (C:\\xampp\\htdocs\\market). External data drives also differ:

  - Linux:   /media/petrick/Parquet/{pustaka_data,trading_data,projects/market}
  - Windows: E:\\{pustaka_data,trading_data,projects\\market}

This module provides OS-aware defaults so that code does NOT hardcode a single
OS path. All defaults can still be overridden via environment variables (see
.env.example) or CLI flags (e.g. --seed-dir).

Usage:
    from quant.paths import default_parquet_archive, default_external_data, \
        default_parquet_seed, default_global_trading_data

References: AGENTS.md §7 (Cross-Platform OS Awareness).
"""

from __future__ import annotations

import sys
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")

# ── Linux defaults (original developer machine) ─────────────────────────
_LINUX_PARQUET_BASE = Path("/media/petrick/Parquet")
_LINUX_PROJECT_DIR = Path("/opt/lampp/htdocs/market")

# ── Windows defaults (portable / second developer machine) ──────────────
_WIN_PARQUET_BASE = Path("E:/")
_WIN_PROJECT_DIR = Path("C:/xampp/htdocs/market")

# Active base directories (selected by OS at import time)
_PARQUET_BASE = _WIN_PARQUET_BASE if IS_WINDOWS else _LINUX_PARQUET_BASE
_PROJECT_DIR = _WIN_PROJECT_DIR if IS_WINDOWS else _LINUX_PROJECT_DIR


def default_parquet_archive() -> str:
    """Pustaka data parquet archive (read/write for export, read for seed)."""
    return str(_PARQUET_BASE / "pustaka_data")


def default_external_data() -> str:
    """External drive backup path for DB parts and large CSVs."""
    return str(_PARQUET_BASE / "projects" / "market")


def default_parquet_seed() -> str:
    """Parquet seed source directory (table-level parquet files)."""
    return str(_PARQUET_BASE / "pustaka_data" / "archive" / "tables")


def default_global_trading_data() -> str:
    """Global project trading_data (read-only — do not write from this project)."""
    return str(_PARQUET_BASE / "trading_data")


def default_global_archive_tables() -> str:
    """Global project archive/tables parquet directory."""
    return str(_PARQUET_BASE / "trading_data" / "archive" / "tables")


def default_global_sqlite_backup() -> str:
    """Global project raw/sqlite_backup parquet directory."""
    return str(_PARQUET_BASE / "trading_data" / "raw" / "sqlite_backup")


def default_global_trading_suspensions() -> str:
    """Global project archive/trading_suspensions parquet directory."""
    return str(_PARQUET_BASE / "trading_data" / "archive" / "trading_suspensions")


def default_dataset_saham_idx() -> str:
    """Dataset-Saham-IDX path (relative to project, same on both OS)."""
    return "data/dataset-saham-idx"
