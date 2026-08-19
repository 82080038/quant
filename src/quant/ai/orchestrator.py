"""Gigantic AI Orchestrator — multi-agent pipeline coordinator.

Coordinates the full multi-agent pipeline:
  Miner → Screener → Trader → Risk Manager → Sentiment

Weight-centric pipeline:
  w_t = R_t(T_t(A_t(S_t(X_≤t))))

  S_t = Screener (stock selection + scoring)
  A_t = Trader (portfolio allocation via HRP-µ / RL / Kelly)
  T_t = Timing adjustment (regime gate)
  R_t = Risk overlay (fail-closed risk gate)

Usage:
    from quant.ai.orchestrator import GiganticAI

    ai = GiganticAI()
    result = ai.run(
        tickers=["BBCA.JK", "BBRI.JK", "TLKM.JK"],
        as_of_date=date(2024, 6, 1),
    )
    if result.risk_check.passed:
        for ticker, weight in result.final_weights.items():
            print(f"{ticker}: {weight:.2%}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from quant.ai.llm_gateway import LLMGateway
from quant.ai.miner_agent import MinerAgent, DiscoveryResult
from quant.ai.screener_agent import ScreenerAgent, ScreeningResult
from quant.ai.trader_agent import TraderAgent, TradingDecision
from quant.ai.risk_agent import RiskManagerAgent, RiskCheckResult, RiskState
from quant.ai.sentiment_agent import SentimentAnalystAgent
from quant.features.factor_library import FactorLibrary
from quant.signals.aggregator import SignalResult

logger = logging.getLogger(__name__)


@dataclass
class GiganticAIResult:
    """Final output of the Gigantic AI pipeline."""
    discovery: Optional[DiscoveryResult]
    screening: ScreeningResult
    trading: TradingDecision
    risk_check: RiskCheckResult
    final_weights: dict[str, float]
    sentiment_signals: list[SignalResult]
    pipeline_success: bool
    errors: list[str] = field(default_factory=list)


class GiganticAI:
    """Multi-agent LLM pipeline orchestrator.

    Coordinates all agents in the weight-centric pipeline:
      1. Miner: Discover new factors (optional, periodic)
      2. Screener: Select stocks + score based on regime
      3. Sentiment: Add sentiment signals from IndoBERT
      4. Trader: Allocate portfolio (HRP-µ / RL / Kelly)
      5. Risk Manager: Fail-closed risk gate

    Usage:
        ai = GiganticAI()
        result = ai.run(
            tickers=["BBCA.JK", "BBRI.JK"],
            as_of_date=date(2024, 6, 1),
        )
    """

    def __init__(
        self,
        gateway: Optional[LLMGateway] = None,
        library: Optional[FactorLibrary] = None,
        allocation_method: str = "hrp_mu",
        session=None,
    ):
        self.gateway = gateway or LLMGateway()
        self.library = library
        self.session = session

        # Initialize agents
        self.miner = MinerAgent(gateway=self.gateway, library=self.library)
        self.screener = ScreenerAgent(gateway=self.gateway, library=self.library, session=session)
        self.trader = TraderAgent(gateway=self.gateway, allocation_method=allocation_method)
        self.risk_mgr = RiskManagerAgent(gateway=self.gateway)
        self.sentiment = SentimentAnalystAgent(session=session)

    def run(
        self,
        tickers: list[str],
        as_of_date: date,
        factor_names: Optional[list[str]] = None,
        market_returns: Optional[pd.Series] = None,
        covariance: Optional[pd.DataFrame] = None,
        run_discovery: bool = False,
        run_sentiment: bool = True,
        sector_map: Optional[dict[str, str]] = None,
        returns_history: Optional[pd.DataFrame] = None,
        current_nav: float = 100_000_000,
        current_positions: Optional[dict[str, float]] = None,
    ) -> GiganticAIResult:
        """Run the full multi-agent pipeline.

        Args:
            tickers: Universe of tickers
            as_of_date: Decision date
            factor_names: Factors to use (default: all registered)
            market_returns: Market index returns for regime detection
            covariance: Covariance matrix for portfolio allocation
            run_discovery: Run Miner Agent for new factor discovery
            run_sentiment: Run Sentiment Analyst Agent
            sector_map: ticker → sector mapping for risk checks
            returns_history: Historical returns for VaR computation
            current_nav: Current portfolio NAV
            current_positions: Current positions (ticker → weight)

        Returns:
            GiganticAIResult with full pipeline output
        """
        errors = []

        # ── Default factor names ───────────────────────────────────
        if factor_names is None:
            if self.library and self.library.factor_names:
                factor_names = self.library.factor_names
            else:
                factor_names = [
                    "rsi_14", "macd_hist", "momentum_20", "reversal_5",
                    "bb_width", "volume_ratio_20", "adx_14", "atr_14",
                ]

        # ── Step 1: Factor Discovery (optional) ────────────────────
        discovery = None
        if run_discovery:
            try:
                existing = self.library.factor_names if self.library else factor_names
                discovery = self.miner.discover(
                    existing_factors=existing,
                    market_context="",
                    n_proposals=2,
                )
            except Exception as e:
                errors.append(f"Miner: {e}")
                logger.warning("Miner agent failed: %s", e)

        # ── Step 2: Sentiment Analysis ─────────────────────────────
        sentiment_signals = []
        if run_sentiment:
            try:
                sentiment_signals = self.sentiment.generate_signals(
                    tickers=tickers,
                    as_of_date=as_of_date,
                )
            except Exception as e:
                errors.append(f"Sentiment: {e}")
                logger.warning("Sentiment agent failed: %s", e)

        # ── Step 3: Screening ──────────────────────────────────────
        try:
            screening = self.screener.screen(
                tickers=tickers,
                as_of_date=as_of_date,
                factor_names=factor_names,
                market_returns=market_returns,
                use_llm=self.gateway.is_available() if hasattr(self.gateway, 'is_available') else False,
            )
        except Exception as e:
            errors.append(f"Screener: {e}")
            logger.error("Screener agent failed: %s", e)
            return GiganticAIResult(
                discovery=discovery,
                screening=ScreeningResult(
                    regime="unknown", selected_tickers=[], scores={},
                    factor_weights={}, regime_confidence=0, llm_rationale="",
                ),
                trading=TradingDecision(
                    weights={}, timing_adjusted={}, regime="unknown",
                    method="none", confidence=0, llm_rationale="",
                ),
                risk_check=RiskCheckResult(passed=False, violations=["Screener failed"]),
                final_weights={},
                sentiment_signals=sentiment_signals,
                pipeline_success=False,
                errors=errors,
            )

        # Merge sentiment signals into screening scores
        if sentiment_signals:
            for sig in sentiment_signals:
                if sig.ticker in screening.scores:
                    existing = screening.scores[sig.ticker]
                    screening.scores[sig.ticker] = (
                        0.6 * existing + 0.4 * sig.signal_value
                    )

        # ── Step 4: Trading (Allocation) ───────────────────────────
        try:
            trading = self.trader.execute(
                screening=screening,
                as_of_date=as_of_date,
                covariance=covariance,
                use_llm=self.gateway.is_available() if hasattr(self.gateway, 'is_available') else False,
            )
        except Exception as e:
            errors.append(f"Trader: {e}")
            logger.error("Trader agent failed: %s", e)
            return GiganticAIResult(
                discovery=discovery,
                screening=screening,
                trading=TradingDecision(
                    weights={}, timing_adjusted={}, regime=screening.regime,
                    method="none", confidence=0, llm_rationale="",
                ),
                risk_check=RiskCheckResult(passed=False, violations=["Trader failed"]),
                final_weights={},
                sentiment_signals=sentiment_signals,
                pipeline_success=False,
                errors=errors,
            )

        # ── Step 5: Risk Check ─────────────────────────────────────
        risk_state = self.risk_mgr.update_risk_state(
            current_nav=current_nav,
            positions=current_positions or {},
            sector_map=sector_map,
        )

        risk_check = self.risk_mgr.check_decision(
            decision=trading,
            risk_state=risk_state,
            returns_history=returns_history,
            sector_map=sector_map,
        )

        # ── Final weights (only if risk check passes) ──────────────
        if risk_check.passed:
            final_weights = trading.timing_adjusted or trading.weights
        else:
            final_weights = {}
            logger.warning("Risk gate blocked: %s", risk_check.violations)

        return GiganticAIResult(
            discovery=discovery,
            screening=screening,
            trading=trading,
            risk_check=risk_check,
            final_weights=final_weights,
            sentiment_signals=sentiment_signals,
            pipeline_success=risk_check.passed,
            errors=errors,
        )
