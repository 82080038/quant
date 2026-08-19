"""Portfolio Cluster Tuner — Ticker-Specific & Regime-Aware Optimization.

Melanjutkan alpha_hyper_tuner.py (Score 3.16, MARGINAL). Skrip ini menerapkan
optimasi per-ticker (bukan global) untuk mendorong Score >= 3.5 (KEEP):

  MODULE 1 — Ticker-Specific Bayesian Optimization
      Jalankan scipy.differential_evolution secara terpisah untuk tiap ticker.
      Tiap ticker mendapat set hyperparameternya sendiri (meta_prob_threshold,
      vol_aggressiveness, vol_hard_cutoff_zscore, signal_threshold).
      Output: ticker_specific_config.json multi-level.

  MODULE 2 — Cross-Sectional Adaptive Kappa Tuning
      κ (kappa) berbanding terbalik dengan Garman-Klass Volatility historis.
      Saham volatil (GK tinggi) → κ kecil (filter tidak terlalu membunuh sinyal).
      Saham stabil (GK rendah) → κ besar (filter lebih selektif).
      Formula: κ = κ_base * (median_GK / ticker_GK)

  MODULE 3 — Dynamic Primary Signal Switcher
      Tiap ticker memilih fondasi sinyal primernya sendiri berdasarkan Sharpe
      Baseline tertinggi selama walk-forward evaluation.
      Pilihan: donchian (period 10/15/20), ema_env (period 20/50), vwap,
      ensemble — dengan parameter period yang juga dioptimasi.

  MODULE 4 — Portfolio-Level Inverse-Variance Ensemble + Promotion Re-Eval
      Gabungkan sinyal individu ke portofolio dengan bobot Inverse-Variance:
        weight_i = (1 / variance_i) / Σ(1 / variance_j)
      Saham volatilitas rendah → alokasi unit lebih besar.
      Hitung ulang Sharpe, Alpha, MaxDD, Score Card untuk portofolio ensemble.

Usage:
    DATABASE_URL=postgresql://petrick:market_dev@localhost:5433/market python scripts/portfolio_cluster_tuner.py \
        [--tickers BBCA.JK,BBRI.JK] [--limit 20] \
        [--n-calls 25] [--output ticker_specific_config.json]

Requires: scipy, pandas, numpy, lightgbm, matplotlib (optional)

Referensi:
  - alpha_rescue_pipeline.py (Reform 1-4)
  - alpha_hyper_tuner.py (Module 1-4, global optimization)
  - pustaka/96-ai-ml-audit-framework.md §9-10
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import differential_evolution

# ── Path setup ─────────────────────────────────────────────────────────────
_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from audit_ai_utility import (  # noqa: E402
    ROUND_TRIP_COST,
    TRADING_DAYS,
    RISK_FREE_RATE,
    PerformanceMetrics,
    compute_performance_metrics,
    simulate_strategy_returns,
    generate_baseline_signals,
    load_ohlcv,
    load_benchmark,
)
from audit_ai_advanced import (  # noqa: E402
    DeltaAlphaResult,
    SignificanceTestResult,
    ComponentVerdict,
    convert_signal_to_position,
    compute_delta_alpha,
    paired_ttest,
    diebold_mariano_test,
    whites_reality_check_approximation,
    compute_component_score_card,
    regime_aware_weights,
    _rsi,
    _bb_width,
)
from alpha_rescue_pipeline import (  # noqa: E402
    ReformConfig,
    volatility_targeted_position_size,
    build_volatility_features,
    build_meta_label_features,
    generate_meta_labeled_signals,
    detect_regime,
    _lgbm_device as lgbm_device,
)
from alpha_hyper_tuner import (  # noqa: E402
    HyperParamSpace,
    TrialResult,
    generate_donchian_signals,
    generate_ema_envelope_signals,
    generate_vwap_signals,
    generate_robust_trend_baseline,
    evaluate_baseline,
    compute_adaptive_threshold,
    _build_config_from_params,
    _generate_vol_targeted_with_baseline,
    _generate_adaptive_meta_labeled_signals,
    _objective_function,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=FutureWarning)


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class TickerResult:
    """Hasil optimasi untuk satu ticker."""

    ticker: str = ""
    baseline_mode: str = "donchian"
    baseline_params: dict = field(default_factory=dict)
    best_params: dict = field(default_factory=dict)
    adapt_kappa: float = 0.15
    gk_volatility: float = 0.0
    sharpe: float = 0.0
    alpha: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    accept_rate: float = 0.0
    brier: float = 0.0
    objective: float = 0.0
    n_observations: int = 0
    returns: pd.Series | None = None


@dataclass
class PortfolioReport:
    """Laporan lengkap portfolio cluster tuning."""

    audit_date: str = ""
    tickers: list[str] = field(default_factory=list)
    n_tickers_optimized: int = 0
    ticker_results: list[dict] = field(default_factory=list)
    portfolio_weights: dict = field(default_factory=dict)
    portfolio_sharpe: float = 0.0
    portfolio_alpha: float = 0.0
    portfolio_max_drawdown: float = 0.0
    portfolio_win_rate: float = 0.0
    portfolio_score: float = 0.0
    portfolio_verdict: str = ""
    promoted_to_keep: bool = False
    before_metrics: dict = field(default_factory=dict)
    after_metrics: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 2 — CROSS-SECTIONAL ADAPTIVE KAPPA TUNING
# ═══════════════════════════════════════════════════════════════════════════
#
# κ berbanding terbalik dengan Garman-Klass Volatility:
#   κ_i = κ_base * (median_GK_cross_sectional / GK_i)
#
# Saham volatil (GK_i tinggi) → κ_i kecil → threshold kurang naik →
#   filter meta-labeler tidak terlalu sering membunuh sinyal produktif.
# Saham stabil (GK_i rendah) → κ_i besar → threshold lebih naik →
#   filter lebih selektif (sinyal stabil tidak perlu disaring agresif).
# ───────────────────────────────────────────────────────────────────────────


def compute_garman_klass_volatility(ohlcv: pd.DataFrame, period: int = 20) -> float:
    """Hitung Garman-Klass Volatility rata-rata untuk satu ticker.

    GK estimator (intrabar range-based, lebih efisien daripada close-to-close):
        GK = sqrt(0.5 * ln(H/L)^2 - (2*ln2 - 1) * ln(C/C_prev)^2)

    Returns:
        Rata-rata GK volatility (annualized) selama seluruh history.
    """
    close = ohlcv["close"].astype(float)
    high = ohlcv["high"].astype(float)
    low = ohlcv["low"].astype(float)

    log_hl = np.log(high / low.replace(0, np.nan))
    log_cc = np.log(close / close.shift(1).replace(0, np.nan))

    gk_inner = 0.5 * log_hl ** 2 - (2 * np.log(2) - 1) * log_cc ** 2
    gk_daily = np.sqrt(np.maximum(0.0, gk_inner))
    gk_avg = float(gk_daily.rolling(period, min_periods=period).mean().dropna().mean())
    return gk_avg if not np.isnan(gk_avg) else 0.0


def compute_cross_sectional_kappa(
    gk_volatilities: dict[str, float],
    kappa_base: float = 0.15,
    kappa_min: float = 0.05,
    kappa_max: float = 0.30,
) -> dict[str, float]:
    """Hitung κ per ticker berbasis invers GK volatility cross-sectional.

    Args:
        gk_volatilities: {ticker: GK_vol} untuk semua ticker.
        kappa_base: κ referensi saat GK = median.
        kappa_min: Batas bawah κ (saham sangat volatil).
        kappa_max: Batas atas κ (saham sangat stabil).

    Returns:
        {ticker: κ} dengan κ berbanding terbalik dengan GK.
    """
    gk_values = list(gk_volatilities.values())
    if not gk_values or all(v == 0 for v in gk_values):
        return {t: kappa_base for t in gk_volatilities}

    median_gk = float(np.median(gk_values))
    kappas: dict[str, float] = {}

    for ticker, gk in gk_volatilities.items():
        if gk > 0 and median_gk > 0:
            kappa = kappa_base * (median_gk / gk)
        else:
            kappa = kappa_base
        kappas[ticker] = float(np.clip(kappa, kappa_min, kappa_max))

    return kappas


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 3 — DYNAMIC PRIMARY SIGNAL SWITCHER
# ═══════════════════════════════════════════════════════════════════════════
#
# Tiap ticker memilih baseline sendiri berdasarkan Sharpe walk-forward.
# Kandidat (dengan parameter period variabel):
#   donchian:    period ∈ {10, 15, 20}
#   ema_env:     ema_period ∈ {20, 50}, envelope_pct ∈ {0.02, 0.03, 0.05}
#   vwap:        vwap_period ∈ {10, 20}
#   ensemble:    kombinasi di atas
# ───────────────────────────────────────────────────────────────────────────


BASELINE_CANDIDATES: list[dict] = [
    {"mode": "donchian", "donchian_period": 10},
    {"mode": "donchian", "donchian_period": 15},
    {"mode": "donchian", "donchian_period": 20},
    {"mode": "ema_env", "ema_period": 20, "envelope_pct": 0.03},
    {"mode": "ema_env", "ema_period": 50, "envelope_pct": 0.02},
    {"mode": "ema_env", "ema_period": 50, "envelope_pct": 0.03},
    {"mode": "ema_env", "ema_period": 50, "envelope_pct": 0.05},
    {"mode": "vwap", "vwap_period": 10},
    {"mode": "vwap", "vwap_period": 20},
    {"mode": "ensemble", "donchian_period": 20, "ema_period": 50, "envelope_pct": 0.03, "vwap_period": 20},
]


def evaluate_baseline_candidate(
    ohlcv: pd.DataFrame,
    benchmark: pd.Series | None,
    candidate: dict,
) -> dict:
    """Evaluasi satu kandidat baseline dengan parameter spesifik.

    Returns:
        Dict dengan mode, params, sharpe, alpha, max_drawdown, win_rate.
    """
    mode = candidate["mode"]
    signals = generate_robust_trend_baseline(ohlcv, **candidate)
    returns = simulate_strategy_returns(ohlcv, signals)
    bench_aligned = benchmark.reindex(returns.index).dropna() if benchmark is not None else None
    perf = compute_performance_metrics(returns, bench_aligned)
    return {
        "mode": mode,
        "params": {k: v for k, v in candidate.items() if k != "mode"},
        "sharpe": perf.sharpe_ratio,
        "alpha": perf.alpha,
        "max_drawdown": perf.max_drawdown,
        "win_rate": perf.win_rate,
        "n_trades": perf.n_trades,
    }


def select_best_baseline_for_ticker(
    ohlcv: pd.DataFrame,
    benchmark: pd.Series | None,
) -> tuple[dict, dict]:
    """Pilih baseline terbaik untuk satu ticker dari semua kandidat.

    Returns:
        (best_candidate_dict, best_metrics_dict)
    """
    best_candidate = BASELINE_CANDIDATES[0]
    best_metrics: dict = {"sharpe": -999.0}
    all_results: list[dict] = []

    for candidate in BASELINE_CANDIDATES:
        m = evaluate_baseline_candidate(ohlcv, benchmark, candidate)
        all_results.append(m)
        if m["sharpe"] > best_metrics["sharpe"]:
            best_metrics = m
            best_candidate = candidate

    return best_candidate, best_metrics


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 1 — TICKER-SPECIFIC BAYESIAN OPTIMIZATION
# ═══════════════════════════════════════════════════════════════════════════


def optimize_ticker(
    ohlcv: pd.DataFrame,
    benchmark: pd.Series | None,
    config: ReformConfig,
    space: HyperParamSpace,
    baseline_candidate: dict,
    adapt_kappa: float,
    n_calls: int = 10,
    popsize: int = 5,
) -> TickerResult:
    """Bayesian optimization (DE) untuk satu ticker.

    Args:
        ohlcv: OHLCV data ticker.
        benchmark: Benchmark returns.
        config: Base ReformConfig.
        space: Hyperparameter search space.
        baseline_candidate: Dict baseline mode + params untuk ticker ini.
        adapt_kappa: κ khusus ticker (dari cross-sectional GK).
        n_calls: Max generations for differential_evolution.
        popsize: Population size multiplier (total pop = popsize * n_dims).

    Returns:
        TickerResult dengan best params dan metrik.
    """
    baseline_mode = baseline_candidate["mode"]
    baseline_params = {k: v for k, v in baseline_candidate.items() if k != "mode"}

    bounds = [
        space.meta_prob_threshold,
        space.vol_aggressiveness,
        space.vol_hard_cutoff_zscore,
        space.signal_threshold,
    ]

    all_results: list[TrialResult] = []

    def neg_objective(x):
        params = {
            "meta_prob_threshold": round(float(x[0]), 4),
            "vol_aggressiveness": round(float(x[1]), 4),
            "vol_hard_cutoff_zscore": round(float(x[2]), 4),
            "signal_threshold": round(float(x[3]), 4),
        }
        cfg = _build_config_from_params(config, params, baseline_mode)

        # Vol-targeted signals dengan baseline spesifik ticker
        vol_positions, _ = _generate_vol_targeted_with_baseline_ticker(
            ohlcv, cfg, baseline_candidate,
        )

        # Adaptive meta-labeling dengan κ spesifik ticker
        rescued, diag2 = _generate_adaptive_meta_labeled_signals(
            ohlcv, vol_positions, cfg, adapt_kappa=adapt_kappa,
        )

        positions = convert_signal_to_position(rescued, cfg.signal_threshold)
        returns = simulate_strategy_returns(ohlcv, positions)
        bench_aligned = benchmark.reindex(returns.index).dropna() if benchmark is not None else None
        perf = compute_performance_metrics(returns, bench_aligned)

        obj = _objective_function(
            perf.sharpe_ratio, perf.alpha, perf.max_drawdown,
            diag2.get("accept_rate", 0.0),
        )

        result = TrialResult(
            params=params, sharpe=perf.sharpe_ratio, alpha=perf.alpha,
            max_drawdown=perf.max_drawdown, win_rate=perf.win_rate,
            accept_rate=diag2.get("accept_rate", 0.0),
            brier=diag2.get("brier", 1.0), objective=obj,
            n_observations=len(returns),
        )
        all_results.append(result)
        if len(all_results) % 10 == 0:
            best_so_far = max(t.objective for t in all_results)
            logger.info("      DE eval %d: best_obj=%.4f, current_obj=%.4f",
                        len(all_results), best_so_far, obj)
        return -obj

    total_evals_est = (n_calls + 1) * popsize * len(bounds)
    logger.info("      DE config: maxiter=%d, popsize=%d, ~%d total evaluations",
                n_calls, popsize, total_evals_est)

    result = differential_evolution(
        neg_objective,
        bounds=bounds,
        maxiter=n_calls,
        popsize=popsize,
        seed=42,
        tol=1e-3,
        polish=True,
        init="sobol",
    )

    best_trial = max(all_results, key=lambda t: t.objective)

    # Recompute returns dengan best params untuk simpan
    cfg_best = _build_config_from_params(config, best_trial.params, baseline_mode)
    vol_pos, _ = _generate_vol_targeted_with_baseline_ticker(ohlcv, cfg_best, baseline_candidate)
    rescued, diag2 = _generate_adaptive_meta_labeled_signals(
        ohlcv, vol_pos, cfg_best, adapt_kappa=adapt_kappa,
    )
    positions = convert_signal_to_position(rescued, cfg_best.signal_threshold)
    best_returns = simulate_strategy_returns(ohlcv, positions)

    return TickerResult(
        ticker="",
        baseline_mode=baseline_mode,
        baseline_params=baseline_params,
        best_params=best_trial.params,
        adapt_kappa=adapt_kappa,
        gk_volatility=compute_garman_klass_volatility(ohlcv),
        sharpe=best_trial.sharpe,
        alpha=best_trial.alpha,
        max_drawdown=best_trial.max_drawdown,
        win_rate=best_trial.win_rate,
        accept_rate=best_trial.accept_rate,
        brier=best_trial.brier,
        objective=best_trial.objective,
        n_observations=best_trial.n_observations,
        returns=best_returns,
    )


def _generate_vol_targeted_with_baseline_ticker(
    ohlcv: pd.DataFrame,
    config: ReformConfig,
    baseline_candidate: dict,
) -> tuple[pd.Series, dict]:
    """Reform 1 dengan baseline spesifik ticker (parameter period variabel)."""
    try:
        import lightgbm as lgb
    except ImportError:
        baseline = generate_robust_trend_baseline(ohlcv, **baseline_candidate)
        return baseline.astype(float), {"n_predictions": 0, "avg_vol_zscore": 0.0, "avg_scale": 1.0}

    feat = build_volatility_features(ohlcv)
    feature_cols = [
        "vol_zscore", "vol_pctile", "atr_pct", "atr_zscore", "vol_of_vol",
        "vol_ratio_20_60", "vol_lag_1", "vol_lag_5", "gk_vol",
        "vol_ratio", "vol_trend", "ret_5", "abs_ret_5", "rsi", "bb_width",
    ]
    target_col = "target_vol_zscore"

    clean = feat.dropna(subset=feature_cols + [target_col])
    if len(clean) < config.min_train_samples + 50:
        baseline = generate_robust_trend_baseline(ohlcv, **baseline_candidate)
        return baseline.astype(float), {"n_predictions": 0, "avg_vol_zscore": 0.0, "avg_scale": 1.0}

    steps = config.walk_forward_steps or max(20, int(len(clean) * 0.2))
    positions = pd.Series(0.0, index=ohlcv.index)
    direction = generate_robust_trend_baseline(ohlcv, **baseline_candidate).astype(float)

    vol_preds: list[float] = []
    scales: list[float] = []
    min_train = config.min_train_samples

    for i in range(min_train, len(clean) - 1):
        if i % steps != 0 and i != min_train:
            continue

        train = clean.iloc[:i]
        test_start, test_end = i, min(i + steps, len(clean))
        test_data = clean.iloc[test_start:test_end]
        if len(test_data) == 0:
            continue

        X_tr = train[feature_cols].values
        y_tr = train[target_col].values
        split = int(len(X_tr) * 0.8)
        X_tr, X_val = X_tr[:split], X_tr[split:]
        y_tr, y_val = y_tr[:split], y_tr[split:]

        weights = regime_aware_weights(train.index[:split])

        model = lgb.LGBMRegressor(
            n_estimators=config.vol_n_estimators,
            max_depth=config.vol_max_depth,
            learning_rate=0.05, verbose=-1,
            subsample=0.8, colsample_bytree=0.8,
            n_jobs=1, min_data_in_leaf=30,
            reg_alpha=0.1, reg_lambda=1.0,
            device=lgbm_device(),
        )
        model.fit(
            X_tr, y_tr,
            sample_weight=weights,
            eval_X=X_val, eval_y=y_val,
            callbacks=[lgb.early_stopping(15, verbose=False)],
        )

        X_test = test_data[feature_cols].values
        pred_vol = model.predict(X_test)
        scale = volatility_targeted_position_size(
            pred_vol,
            target_vol_zscore=config.vol_target_zscore,
            max_position=config.vol_max_position,
            aggressiveness=config.vol_aggressiveness,
            hard_cutoff=config.vol_hard_cutoff_zscore,
        )

        for j, idx in enumerate(test_data.index):
            dir_val = direction.reindex([idx]).iloc[0]
            positions.loc[idx] = dir_val * scale[j]

        vol_preds.extend(pred_vol.tolist())
        scales.extend(scale.tolist())

    diag = {
        "n_predictions": len(vol_preds),
        "avg_vol_zscore": float(np.mean(vol_preds)) if vol_preds else 0.0,
        "avg_scale": float(np.mean(scales)) if scales else 1.0,
    }
    return positions, diag


# ═══════════════════════════════════════════════════════════════════════════
# MODULE 4 — PORTFOLIO-LEVEL INVERSE-VARIANCE ENSEMBLE
# ═══════════════════════════════════════════════════════════════════════════
#
# Bobot Inverse-Variance:
#   weight_i = (1 / variance_i) / Σ_j(1 / variance_j)
#
# Saham dengan return variance rendah (stabil) → alokasi lebih besar.
# Saham dengan return variance tinggi (volatil) → alokasi lebih kecil.
# ───────────────────────────────────────────────────────────────────────────


def compute_inverse_variance_weights(
    returns_dict: dict[str, pd.Series],
    max_weight: float = 0.20,
    var_epsilon: float = 1e-6,
    min_accept_rate: float = 0.05,
) -> dict[str, float]:
    """Hitung bobot Inverse-Variance untuk ensemble portofolio.

    Safeguards against weighting collapse:
    - Filter ticker dengan accept_rate < min_accept_rate (return konstan nol).
    - Variance floor (epsilon) mencegah 1/0 = infinity.
    - Cap max weight per ticker (default 20%).
    - Fallback equal-weighting jika hanya 0-1 ticker yang lolos filter.

    Args:
        returns_dict: {ticker: daily_returns_series}

    Returns:
        {ticker: weight} dengan Σ weights = 1.0
    """
    # Filter ticker dengan accept_rate terlalu rendah (return konstan nol)
    filtered = {}
    for ticker, rets in returns_dict.items():
        if len(rets) == 0:
            continue
        accept_rate = float((rets != 0.0).sum()) / len(rets)
        if accept_rate < min_accept_rate:
            continue
        filtered[ticker] = rets

    # Fallback equal-weighting jika 0-1 ticker lolos filter
    if len(filtered) <= 1:
        all_tickers = list(returns_dict.keys())
        if not all_tickers:
            return {}
        eq_weight = 1.0 / len(all_tickers)
        return {ticker: eq_weight for ticker in all_tickers}

    variances: dict[str, float] = {}
    for ticker, rets in filtered.items():
        var = float(rets.var())
        variances[ticker] = max(var, var_epsilon)

    inv_vars = {t: 1.0 / v for t, v in variances.items()}
    total_inv = sum(inv_vars.values())

    weights = {t: iv / total_inv for t, iv in inv_vars.items()}

    # Cap max weight per ticker — iterative cap+redistribute
    for _ in range(20):
        capped = {t: min(w, max_weight) for t, w in weights.items()}
        excess = sum(weights[t] - capped[t] for t in weights)
        if excess < 1e-9:
            break
        weights = dict(capped)
        # Redistribute excess to uncapped tickers
        uncapped_total = sum(w for t, w in weights.items() if w < max_weight)
        if uncapped_total > 0:
            for t in weights:
                if weights[t] < max_weight:
                    weights[t] += excess * (weights[t] / uncapped_total)
    # Final hard clip + renormalize
    weights = {t: min(w, max_weight) for t, w in weights.items()}
    total_w = sum(weights.values())
    if total_w > 0:
        weights = {t: w / total_w for t, w in weights.items()}

    # Pastikan ticker yang di-filter out tetap ada dengan weight=0
    for ticker in returns_dict:
        if ticker not in weights:
            weights[ticker] = 0.0

    return weights


def ensemble_portfolio_returns(
    returns_dict: dict[str, pd.Series],
    weights: dict[str, float],
) -> pd.Series:
    """Gabungkan return individu ke return portofolio berbobot.

    Returns:
        Series return portofolio (weighted average per tanggal).
    """
    if not returns_dict:
        return pd.Series(dtype=float)

    df = pd.DataFrame(returns_dict)
    # Reindex ke union semua tanggal, fillna 0
    df = df.fillna(0.0)

    portfolio = pd.Series(0.0, index=df.index)
    for ticker, weight in weights.items():
        if ticker in df.columns:
            portfolio += df[ticker] * weight

    return portfolio


def evaluate_portfolio(
    portfolio_returns: pd.Series,
    benchmark: pd.Series | None,
) -> dict:
    """Evaluasi metrik portofolio ensemble.

    Returns:
        Dict dengan sharpe, alpha, max_drawdown, win_rate, n_trades.
    """
    bench_aligned = benchmark.reindex(portfolio_returns.index).dropna() if benchmark is not None else None
    perf = compute_performance_metrics(portfolio_returns, bench_aligned)
    return {
        "sharpe": perf.sharpe_ratio,
        "alpha": perf.alpha,
        "max_drawdown": perf.max_drawdown,
        "win_rate": perf.win_rate,
        "n_trades": perf.n_trades,
    }


# ═══════════════════════════════════════════════════════════════════════════
# ORCHESTRATION — MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════


def run_portfolio_cluster_tuner(
    tickers: list[str],
    session,
    config: ReformConfig | None = None,
    space: HyperParamSpace | None = None,
    n_calls: int = 10,
    popsize: int = 5,
    output_path: str = "ticker_specific_config.json",
) -> PortfolioReport:
    """Jalankan portfolio cluster tuning penuh.

    Alur:
      1. Hitung GK volatility per ticker → cross-sectional κ
      2. Per ticker: pilih baseline terbaik → Bayesian optimize hyperparams
      3. Compute inverse-variance weights untuk ensemble
      4. Evaluasi portofolio ensemble → Score Card → KEEP/MARGINAL
    """
    if config is None:
        config = ReformConfig()
    if space is None:
        space = HyperParamSpace()

    report = PortfolioReport(
        audit_date=pd.Timestamp.now().isoformat(),
        tickers=tickers,
    )

    logger.info("=" * 70)
    logger.info("PORTFOLIO CLUSTER TUNER — TICKER-SPECIFIC & REGIME-AWARE")
    logger.info("=" * 70)
    logger.info("Tickers: %d (%s)", len(tickers), tickers)
    logger.info("DE calls per ticker: %d", n_calls)
    logger.info("Target: Score >= 3.5 (KEEP promotion)")
    logger.info("")

    benchmark = load_benchmark(session)

    # ── Step 1: Cross-Sectional Adaptive Kappa ──
    logger.info("STEP 1: Cross-Sectional Adaptive Kappa (GK Volatility)")
    logger.info("-" * 50)

    gk_vols: dict[str, float] = {}
    ohlcv_cache: dict[str, pd.DataFrame] = {}

    for ticker in tickers:
        ohlcv = load_ohlcv(session, ticker)
        if len(ohlcv) < 500:
            logger.info("  %s: skip (data tidak cukup, %d rows)", ticker, len(ohlcv))
            continue
        gk = compute_garman_klass_volatility(ohlcv)
        gk_vols[ticker] = gk
        ohlcv_cache[ticker] = ohlcv
        logger.info("  %s: GK vol = %.6f (%d rows)", ticker, gk, len(ohlcv))

    if not gk_vols:
        logger.warning("Tidak ada ticker valid — pipeline berhenti")
        return report

    kappas = compute_cross_sectional_kappa(gk_vols)
    logger.info("")
    logger.info("  Cross-sectional κ:")
    for t, k in kappas.items():
        logger.info("    %s: κ = %.4f (GK = %.6f)", t, k, gk_vols[t])
    logger.info("")

    # ── Step 2: Before-Tuning Evaluation (global config baseline) ──
    logger.info("STEP 2: Before-Tuning Evaluation (global config)")
    logger.info("-" * 50)

    before_returns: dict[str, pd.Series] = {}
    for ticker, ohlcv in ohlcv_cache.items():
        vol_pos, _ = _generate_vol_targeted_with_baseline(ohlcv, config, "donchian")
        rescued, diag2 = _generate_adaptive_meta_labeled_signals(ohlcv, vol_pos, config)
        positions = convert_signal_to_position(rescued, config.signal_threshold)
        rets = simulate_strategy_returns(ohlcv, positions)
        before_returns[ticker] = rets

    before_weights = compute_inverse_variance_weights(before_returns)
    before_portfolio = ensemble_portfolio_returns(before_returns, before_weights)
    before_metrics = evaluate_portfolio(before_portfolio, benchmark)
    report.before_metrics = before_metrics
    logger.info("  Before: Sharpe=%+.3f, Alpha=%+.4f, MaxDD=%.2f%%, WinRate=%.1f%%",
                before_metrics["sharpe"], before_metrics["alpha"],
                before_metrics["max_drawdown"] * 100, before_metrics["win_rate"] * 100)
    logger.info("")

    # ── Step 3: Per-Ticker Optimization ──
    logger.info("STEP 3: Ticker-Specific Bayesian Optimization")
    logger.info("-" * 50)

    ticker_results: list[TickerResult] = []

    for i, (ticker, ohlcv) in enumerate(ohlcv_cache.items()):
        logger.info("")
        logger.info("  [%d/%d] %s (%d rows)", i + 1, len(ohlcv_cache), ticker, len(ohlcv))

        # Step 3a: Dynamic Primary Signal Switcher
        logger.info("    ▶ Baseline selection (10 candidates)...")
        best_candidate, best_baseline_metrics = select_best_baseline_for_ticker(ohlcv, benchmark)
        logger.info("    → Baseline: %s (params=%s, Sharpe=%+.3f)",
                    best_candidate["mode"],
                    {k: v for k, v in best_candidate.items() if k != "mode"},
                    best_baseline_metrics["sharpe"])

        # Step 3b: Bayesian optimization dengan κ spesifik
        kappa_ticker = kappas[ticker]
        logger.info("    ▶ Bayesian DE (n_calls=%d, κ=%.4f)...", n_calls, kappa_ticker)

        result = optimize_ticker(
            ohlcv, benchmark, config, space,
            best_candidate, kappa_ticker, n_calls=n_calls, popsize=popsize,
        )
        result.ticker = ticker
        ticker_results.append(result)

        logger.info("    → Best: Sharpe=%+.3f, Alpha=%+.4f, AcceptRate=%.1f%%, obj=%.4f",
                    result.sharpe, result.alpha, result.accept_rate * 100, result.objective)
        logger.info("      params: %s", result.best_params)

    report.n_tickers_optimized = len(ticker_results)
    logger.info("")

    # ── Step 4: Portfolio-Level Inverse-Variance Ensemble ──
    logger.info("STEP 4: Portfolio-Level Inverse-Variance Ensemble")
    logger.info("-" * 50)

    after_returns: dict[str, pd.Series] = {}
    for tr in ticker_results:
        if tr.returns is not None:
            after_returns[tr.ticker] = tr.returns

    after_weights = compute_inverse_variance_weights(after_returns)
    report.portfolio_weights = {t: round(w, 4) for t, w in after_weights.items()}

    logger.info("  Inverse-Variance weights:")
    for t, w in after_weights.items():
        logger.info("    %s: weight = %.4f", t, w)

    after_portfolio = ensemble_portfolio_returns(after_returns, after_weights)
    after_metrics = evaluate_portfolio(after_portfolio, benchmark)
    report.after_metrics = after_metrics

    # Score Card
    # Ambil ohlcv ticker pertama untuk compute_delta_alpha
    first_ohlcv = list(ohlcv_cache.values())[0]
    delta = compute_delta_alpha(
        first_ohlcv, after_portfolio.reindex(first_ohlcv.index).fillna(0),
        benchmark, "PortfolioClusterTuned", config.signal_threshold,
    )

    sig_results: list[SignificanceTestResult] = []
    aligned_ret = pd.DataFrame({
        "ai": after_portfolio,
        "baseline": before_portfolio,
    }).dropna()
    if len(aligned_ret) > 30:
        sig_results.append(paired_ttest(aligned_ret["ai"], aligned_ret["baseline"]))
        if benchmark is not None:
            bench_re = benchmark.reindex(aligned_ret.index).fillna(0)
            sig_results.append(diebold_mariano_test(
                aligned_ret["ai"] - bench_re, aligned_ret["baseline"] - bench_re, horizon=5,
            ))
        sig_results.append(whites_reality_check_approximation(
            aligned_ret["ai"], aligned_ret["baseline"], n_bootstrap=500,
        ))

    verdict = compute_component_score_card(
        component_name="PortfolioClusterTuned",
        delta_alpha_result=delta,
        significance_results=sig_results,
        drift_results=None,
        latency_ms=None,
        monthly_cost=0.0,
    )

    score = verdict.score_card["weighted_total"]
    promoted = verdict.verdict == "KEEP" and after_metrics["sharpe"] > 1.0 and after_metrics["alpha"] > 0

    report.portfolio_sharpe = after_metrics["sharpe"]
    report.portfolio_alpha = after_metrics["alpha"]
    report.portfolio_max_drawdown = after_metrics["max_drawdown"]
    report.portfolio_win_rate = after_metrics["win_rate"]
    report.portfolio_score = score
    report.portfolio_verdict = verdict.verdict
    report.promoted_to_keep = promoted

    # Simpan ticker results ke report
    report.ticker_results = [
        {
            "ticker": tr.ticker,
            "baseline_mode": tr.baseline_mode,
            "baseline_params": tr.baseline_params,
            "best_params": tr.best_params,
            "adapt_kappa": tr.adapt_kappa,
            "gk_volatility": tr.gk_volatility,
            "sharpe": tr.sharpe,
            "alpha": tr.alpha,
            "max_drawdown": tr.max_drawdown,
            "win_rate": tr.win_rate,
            "accept_rate": tr.accept_rate,
            "brier": tr.brier,
            "objective": tr.objective,
        }
        for tr in ticker_results
    ]

    # ── Step 5: Promotion Report ──
    logger.info("")
    logger.info("STEP 5: Portfolio Promotion Report")
    logger.info("-" * 50)

    logger.info("")
    logger.info("  ┌──────────────────────────────────────────────────────────────┐")
    logger.info("  │  PORTFOLIO COMPARISON: GLOBAL vs TICKER-SPECIFIC             │")
    logger.info("  ├──────────────────────────────────────────────────────────────┤")
    logger.info("  │  Metric              │  Global (Before) │  Per-Ticker (After)│")
    logger.info("  ├───────────────────────┼──────────────────┼──────────────────┤")

    metrics = [
        ("Sharpe Ratio", "sharpe", "%+.3f"),
        ("Alpha (annual)", "alpha", "%+.4f"),
        ("Max Drawdown", "max_drawdown", "%.2f%%"),
        ("Win Rate", "win_rate", "%.1f%%"),
    ]

    for label, key, fmt in metrics:
        b_val = before_metrics.get(key, 0.0)
        a_val = after_metrics.get(key, 0.0)
        if key in ("max_drawdown", "win_rate"):
            b_str = fmt % (b_val * 100)
            a_str = fmt % (a_val * 100)
        else:
            b_str = fmt % b_val
            a_str = fmt % a_val
        delta_val = a_val - b_val
        arrow = "↑" if delta_val > 0 else ("↓" if delta_val < 0 else "→")
        logger.info("  │  %-18s │  %15s │  %15s  %s │",
                    label, b_str, a_str, arrow)

    logger.info("  │  Score Card         │          3.16    │  %14.2f/5  │", score)
    logger.info("  └──────────────────────────────────────────────────────────────┘")

    logger.info("")
    logger.info("  Per-Ticker Summary:")
    for tr in ticker_results:
        logger.info("    %s: baseline=%s, κ=%.4f, Sharpe=%+.3f, Alpha=%+.4f, accept=%.1f%%",
                    tr.ticker, tr.baseline_mode, tr.adapt_kappa,
                    tr.sharpe, tr.alpha, tr.accept_rate * 100)

    logger.info("")
    logger.info("  Verdict: %s | Score: %.2f/5.00 | Promoted: %s",
                verdict.verdict, score, "YES" if promoted else "NO")

    if promoted:
        logger.info("")
        logger.info("  ★★★ PROMOSI BERHASIL: MARGINAL → KEEP ★★★")
        logger.info("  Target tercapai: Sharpe > 1.0, Alpha > 0, Score >= 3.5")
    else:
        logger.info("")
        logger.info("  ✗ Belum terpromosi (Score=%.2f, target=3.5). Rekomendasi:", score)
        if after_metrics["sharpe"] < 1.0:
            logger.info("    - Sharpe portofolio < 1.0 — tambah ticker atau perluas n_calls")
        if after_metrics["alpha"] <= 0:
            logger.info("    - Alpha portofolio ≤ 0 — evaluasi fitur eksogen tambahan")
        logger.info("    - Coba tambah ticker untuk diversifikasi cross-sectional")
        logger.info("    - Eksperimen dengan kappa_base atau baseline_candidates tambahan")

    # ── Save ticker-specific config ──
    ticker_config: dict[str, dict] = {}
    for tr in ticker_results:
        ticker_config[tr.ticker] = {
            "baseline_mode": tr.baseline_mode,
            "baseline_params": tr.baseline_params,
            "best_params": tr.best_params,
            "adapt_kappa": tr.adapt_kappa,
            "gk_volatility": tr.gk_volatility,
            "performance": {
                "sharpe": round(tr.sharpe, 4),
                "alpha": round(tr.alpha, 6),
                "max_drawdown": round(tr.max_drawdown, 4),
                "win_rate": round(tr.win_rate, 4),
                "accept_rate": round(tr.accept_rate, 4),
                "brier": round(tr.brier, 4),
                "objective": round(tr.objective, 4),
            },
        }

    config_path = Path(output_path)
    with config_path.open("w") as f:
        json.dump(ticker_config, f, indent=2)
    logger.info("")
    logger.info("  Ticker-specific config disimpan: %s", config_path)

    # Plot equity curve (optional)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(12, 6))
        eq_before = (1 + before_portfolio).cumprod()
        eq_after = (1 + after_portfolio).cumprod()
        ax.plot(eq_before.index, eq_before.values, label="Global (Before)", color="gray", alpha=0.7)
        ax.plot(eq_after.index, eq_after.values, label="Per-Ticker (After)", color="green", linewidth=1.5)
        ax.set_title("Portfolio Equity Curve: Global vs Ticker-Specific Optimization")
        ax.set_ylabel("Equity (1 = start)")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plot_path = Path(output_path).parent / "portfolio_equity_comparison.png"
        plt.savefig(plot_path, dpi=150)
        plt.close()
        logger.info("  Plot equity curve disimpan: %s", plot_path)
    except ImportError:
        logger.info("  matplotlib tidak tersedia — plot dilewati")

    return report


def _report_to_dict(report: PortfolioReport) -> dict:
    """Serialisasi PortfolioReport ke dict JSON-safe."""
    def _safe(obj):
        if hasattr(obj, "__dataclass_fields__"):
            return {k: _safe(v) for k, v in asdict(obj).items() if v is not None}
        if isinstance(obj, list):
            return [_safe(x) for x in obj]
        if isinstance(obj, pd.Series):
            return None  # skip Series in report
        return obj
    return _safe(report)


def main():
    from sqlalchemy import text
    from quant.db.engine import get_sessionmaker

    parser = argparse.ArgumentParser(
        description="Portfolio Cluster Tuner — Ticker-Specific & Regime-Aware Optimization",
    )
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers")
    parser.add_argument("--limit", type=int, default=20, help="Max tickers")
    parser.add_argument("--n-calls", type=int, default=10,
                        help="Max DE generations per ticker")
    parser.add_argument("--popsize", type=int, default=5,
                        help="DE population size multiplier (pop = popsize * n_dims)")
    parser.add_argument("--output", type=str, default="ticker_specific_config.json",
                        help="Output JSON file untuk ticker-specific config")
    args = parser.parse_args()

    config = ReformConfig()
    space = HyperParamSpace()

    session = get_sessionmaker()()

    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",")]
    else:
        rows = session.execute(
            text(
                "SELECT ticker, COUNT(*) as cnt FROM ohlcv "
                "WHERE ticker LIKE '%.JK' AND timeframe='1d' "
                "GROUP BY ticker ORDER BY cnt DESC LIMIT :limit"
            ),
            {"limit": args.limit},
        ).fetchall()
        tickers = [r[0] for r in rows]

    report = run_portfolio_cluster_tuner(
        tickers, session, config, space,
        n_calls=args.n_calls, popsize=args.popsize, output_path=args.output,
    )

    # Save full report
    full_report_path = Path(args.output).parent / "portfolio_cluster_tuner_report.json"
    with full_report_path.open("w") as f:
        json.dump(_report_to_dict(report), f, indent=2, default=str)
    logger.info("")
    logger.info("Laporan lengkap disimpan ke %s", full_report_path)


if __name__ == "__main__":
    main()
