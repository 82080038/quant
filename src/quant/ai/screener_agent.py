"""Screener Agent — regime-conditioned factor ensemble construction.

Inspired by AlphaCrafter's Screener module. The Screener Agent:
  1. Detects current market regime (bull, bear, sideways, crisis)
  2. Selects the best subset of factors for the current regime
  3. Constructs an ensemble weighting based on regime-conditional IC
  4. Produces a composite signal per ticker

The Screener sits between the Miner (factor discovery) and Trader (execution),
acting as the portfolio selection layer in the weight-centric pipeline:
  w_t = R_t(T_t(A_t(S_t(X_≤t))))
  S_t = Screener Agent output (stock selection + scoring)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from quant.ai.llm_gateway import LLMGateway
from quant.evaluation.regime_conditional import RegimeConditionalEvaluator
from quant.evaluation.ic_tracking import ICTracker
from quant.features.factor_library import FactorLibrary

logger = logging.getLogger(__name__)


@dataclass
class ScreeningResult:
    """Result of screening pass."""
    regime: str
    selected_tickers: list[str]
    scores: dict[str, float]
    factor_weights: dict[str, float]
    regime_confidence: float
    llm_rationale: str


SCREENER_SYSTEM_PROMPT = """You are a quantitative portfolio screener for the Indonesian stock market (IDX).

Given the current market regime and factor performance data, your task is to:
1. Select the optimal subset of factors for the current regime
2. Assign weights to each factor based on regime-conditional IC
3. Explain your reasoning

Regime guidelines:
- Bull: Favor momentum, technical, and global market factors
- Bear: Favor fundamental, macro, and policy event factors
- Sideways: Favor mean reversion, volume, and sentiment factors
- Crisis: Favor macro, policy events, and risk-off factors

Respond in JSON with factor_weights and rationale."""


class ScreenerAgent:
    """Regime-conditioned factor ensemble construction agent.

    Usage:
        screener = ScreenerAgent()
        result = screener.screen(
            tickers=["BBCA.JK", "BBRI.JK", "TLKM.JK"],
            as_of_date=date(2024, 6, 1),
            factor_names=["rsi_14", "momentum_20", "reversal_5"],
        )
        for ticker, score in result.scores.items():
            print(f"{ticker}: {score:.4f}")
    """

    # Regime-conditional factor weight templates
    REGIME_FACTOR_WEIGHTS = {
        "bull": {
            "momentum_20": 0.25, "rsi_14": 0.15, "ewma_momentum": 0.15,
            "macd_hist": 0.10, "volume_ratio_20": 0.10, "bb_width": 0.05,
            "adx_14": 0.10, "kama_10": 0.10,
        },
        "bear": {
            "reversal_5": 0.20, "volatility_20": 0.15, "atr_14": 0.15,
            "bb_width": 0.10, "mfi_14": 0.10, "rsi_14": 0.10,
            "vwap_dev": 0.10, "obv": 0.10,
        },
        "sideways": {
            "reversal_5": 0.20, "vwap_dev": 0.15, "mfi_14": 0.15,
            "rsi_14": 0.10, "bb_width": 0.10, "volume_ratio_20": 0.10,
            "obv": 0.10, "adx_14": 0.10,
        },
        "crisis": {
            "volatility_20": 0.25, "atr_14": 0.20, "reversal_5": 0.15,
            "bb_width": 0.10, "mfi_14": 0.10, "rsi_14": 0.10,
            "obv": 0.05, "vwap_dev": 0.05,
        },
    }

    def __init__(
        self,
        gateway: Optional[LLMGateway] = None,
        library: Optional[FactorLibrary] = None,
        session=None,
    ):
        self.gateway = gateway or LLMGateway()
        self.library = library
        self._session = session
        self._regime_evaluator = RegimeConditionalEvaluator()
        self._ic_tracker = ICTracker(session=session)

    def detect_regime(
        self,
        market_returns: pd.Series,
        window: int = 63,
    ) -> tuple[str, float]:
        """Detect current market regime.

        Args:
            market_returns: IHSG/IDX daily returns series
            window: Rolling window for regime classification

        Returns:
            (regime_label, confidence)
        """
        if market_returns.empty or len(market_returns) < window:
            return "sideways", 0.5

        regimes = self._regime_evaluator.classify_regime(market_returns, window=window)
        current = regimes.iloc[-1]

        recent = market_returns.tail(window)
        rolling_mean = recent.mean()
        rolling_vol = recent.std()
        historical_vol = market_returns.expanding(min_periods=60).std().shift(1).iloc[-1]

        if historical_vol and historical_vol > 0:
            vol_ratio = rolling_vol / historical_vol
        else:
            vol_ratio = 1.0

        if current == "bull":
            confidence = min(1.0, abs(rolling_mean) / (rolling_vol + 1e-8) * 2)
        elif current == "bear":
            confidence = min(1.0, abs(rolling_mean) / (rolling_vol + 1e-8) * 2)
        elif current == "crisis":
            confidence = min(1.0, vol_ratio / 3)
        else:
            confidence = 0.5

        return current, float(confidence)

    def screen(
        self,
        tickers: list[str],
        as_of_date: date,
        factor_names: list[str],
        market_returns: Optional[pd.Series] = None,
        use_llm: bool = True,
        top_k: int = 20,
    ) -> ScreeningResult:
        """Screen and score tickers based on regime-conditioned factors.

        Args:
            tickers: Universe of tickers to screen
            as_of_date: Decision date
            factor_names: Factors to use for screening
            market_returns: Market index returns for regime detection
            use_llm: Use LLM for factor weight optimization
            top_k: Number of top tickers to select

        Returns:
            ScreeningResult with selected tickers and scores
        """
        regime, confidence = self.detect_regime(market_returns) if market_returns is not None else ("sideways", 0.5)

        factor_weights = self._get_factor_weights(regime, factor_names, use_llm)

        scores = {}
        for ticker in tickers:
            score = self._score_ticker(ticker, as_of_date, factor_names, factor_weights)
            if score is not None:
                scores[ticker] = score

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        selected = [t for t, _ in ranked[:top_k]]

        llm_rationale = ""
        if use_llm:
            llm_rationale = self._llm_rationale(regime, factor_weights, ranked[:5])

        return ScreeningResult(
            regime=regime,
            selected_tickers=selected,
            scores=scores,
            factor_weights=factor_weights,
            regime_confidence=confidence,
            llm_rationale=llm_rationale,
        )

    def _get_factor_weights(
        self,
        regime: str,
        factor_names: list[str],
        use_llm: bool,
    ) -> dict[str, float]:
        """Get regime-conditional factor weights."""
        template = self.REGIME_FACTOR_WEIGHTS.get(regime, {})

        weights = {}
        for fname in factor_names:
            weights[fname] = template.get(fname, 1.0 / len(factor_names))

        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        if use_llm:
            llm_weights = self._llm_factor_weights(regime, factor_names)
            if llm_weights:
                for fname in factor_names:
                    if fname in llm_weights:
                        weights[fname] = llm_weights[fname]
                total = sum(weights.values())
                if total > 0:
                    weights = {k: v / total for k, v in weights.items()}

        return weights

    def _llm_factor_weights(self, regime: str, factors: list[str]) -> dict[str, float]:
        """Ask LLM for optimal factor weights given regime."""
        user_prompt = f"""Current regime: {regime}
Available factors: {', '.join(factors)}

Assign weights (0.0-1.0) to each factor for this regime. Higher weight = more important.
Respond as JSON: {{"factor_weights": {{"factor_name": weight, ...}}, "rationale": "..."}}"""

        resp = self.gateway.complete(
            system=SCREENER_SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.2,
            json_mode=True,
            max_tokens=1024,
        )

        if resp.success and resp.parsed:
            return resp.parsed.get("factor_weights", {})
        return {}

    def _score_ticker(
        self,
        ticker: str,
        as_of: date,
        factor_names: list[str],
        weights: dict[str, float],
    ) -> Optional[float]:
        """Compute composite score for a ticker.

        Normalizes each factor via its recent z-score (using the factor's
        own historical distribution) before weighted combination.
        This ensures factors with different scales (RSI 0-100, MACD real,
        momentum fraction) contribute comparably.
        """
        if self.library is None:
            return None

        score = 0.0
        total_weight = 0.0

        for fname in factor_names:
            w = weights.get(fname, 0.0)
            if w == 0:
                continue

            series = self.library.get_factor(fname, ticker, as_of, lookback=60)
            if series.empty or len(series) < 5:
                continue

            val = float(series.iloc[-1])
            if np.isnan(val):
                continue

            # Z-score normalize: (current - mean) / std
            mean = float(series.mean())
            std = float(series.std())
            if std > 1e-8:
                z = (val - mean) / std
            else:
                z = 0.0

            # Clip to [-3, 3] then scale to [-1, 1]
            z = float(np.clip(z, -3.0, 3.0) / 3.0)

            score += z * w
            total_weight += w

        if total_weight == 0:
            return None

        return float(np.clip(score / total_weight, -1, 1))

    def _llm_rationale(self, regime: str, weights: dict, top_tickers: list) -> str:
        """Get LLM rationale for screening decision."""
        ticker_str = ", ".join(f"{t}: {s:.4f}" for t, s in top_tickers)
        user_prompt = f"""Regime: {regime}
Factor weights: {weights}
Top selected: {ticker_str}

Briefly explain (2-3 sentences) why these stocks were selected and the factor weighting rationale."""

        resp = self.gateway.complete(
            system=SCREENER_SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.3,
            max_tokens=512,
        )

        if resp.success:
            return resp.text
        return ""
