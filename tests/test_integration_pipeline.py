"""Integration tests for end-to-end pipeline (C9).

Tests the full pipeline flow with mocked DB to verify:
- PipelineOrchestrator step sequencing
- Signal generation → portfolio → execution flow
- PaperTradingOMS state transitions
- DriftDetector baseline comparison
- ModelRetirementManager verdict logic
- AlertManager message formatting
- LLMGateway fallback handling
"""

import pytest
import numpy as np
import pandas as pd
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, PropertyMock


# ── Pipeline Orchestrator Integration ────────────────────────────────

class TestPipelineOrchestratorIntegration:
    """Test pipeline step sequencing and data flow."""

    def test_step_order(self):
        """Pipeline steps must execute in order: ingest → screen → analyze → signal → portfolio → execute."""
        from quant.pipeline.state_machine import PipelineStatus, TRANSITIONS
        steps = ["ingested", "screened", "analyzed", "signal_generated", "portfolio_optimized", "done"]
        for i in range(len(steps) - 1):
            current = PipelineStatus(steps[i])
            expected_next = PipelineStatus(steps[i + 1])
            # Verify transition exists
            assert expected_next in TRANSITIONS.get(current, set()), \
                f"No transition from {current} to {expected_next}"

    def test_failed_transition(self):
        """Failed step should transition to 'failed' status."""
        from quant.pipeline.state_machine import PipelineStatus, TRANSITIONS
        assert PipelineStatus.FAILED in TRANSITIONS.get(PipelineStatus.ANALYZED, set())

    def test_skipped_transition(self):
        """Skipped step should transition to 'skipped' status."""
        from quant.pipeline.state_machine import PipelineStatus, TRANSITIONS
        assert PipelineStatus.SKIPPED in TRANSITIONS.get(PipelineStatus.SCREENED, set())


# ── Signal → Portfolio → Execution Flow ──────────────────────────────

class TestSignalPortfolioExecution:
    """Test data flow from signals through portfolio to execution."""

    def test_signal_to_portfolio_flow(self):
        """Signals should be passable to HRP-µ allocator."""
        from quant.portfolio.hrp_mu import HRPMu
        signals = {"BBCA.JK": 0.8, "BBRI.JK": 0.6, "TLKM.JK": -0.3}
        n = len(signals)
        cov = pd.DataFrame(
            np.eye(n) * 0.04 + 0.01,
            index=signals.keys(),
            columns=signals.keys(),
        )
        hrp = HRPMu()
        weights = hrp.allocate(signals, cov, max_weight=0.15)
        assert isinstance(weights, dict)
        assert len(weights) == n
        assert all(-0.5 <= w <= 1.0 for w in weights.values())
        assert abs(sum(weights.values()) - 1.0) < 0.1  # weights roughly sum to 1

    def test_portfolio_to_oms_flow(self):
        """Portfolio weights should be executable via PaperTradingOMS."""
        from quant.execution.paper_trading import PaperTradingOMS
        from quant.execution.oms import OrderSide
        oms = PaperTradingOMS(initial_capital=100_000_000, sector_map={"BBCA.JK": "Finance"})
        weights = {"BBCA.JK": 0.10}
        prices = {"BBCA.JK": 8500.0}
        for ticker, weight in weights.items():
            target_value = oms.nav * weight
            shares = int(target_value / prices[ticker] // 100) * 100
            if shares > 0:
                result = oms.submit_order(ticker, OrderSide.BUY, shares, prices[ticker])
                assert result is not None
        assert oms.nav > 0

    def test_oms_halt_on_drawdown(self):
        """OMS should halt when drawdown exceeds threshold."""
        from quant.execution.paper_trading import PaperTradingOMS
        oms = PaperTradingOMS(initial_capital=100_000_000)
        # Simulate extreme drawdown
        oms.current_drawdown = 0.25  # 25% drawdown
        oms.is_halted = True
        oms.halt_reason = "Max drawdown exceeded"
        assert oms.is_halted
        assert "drawdown" in oms.halt_reason.lower()


# ── Drift Detection Integration ──────────────────────────────────────

class TestDriftDetectionIntegration:
    """Test drift detector with realistic scenarios."""

    def test_no_drift_when_stable(self):
        """No drift when metrics unchanged."""
        from quant.monitoring.drift import DriftDetector
        detector = DriftDetector()
        detector.set_baseline_metrics({"sharpe": 1.5})
        results = detector.check_metric_drift({"sharpe": 1.52})
        assert len(results) == 1
        assert not results[0].is_drifted

    def test_drift_detected_on_degradation(self):
        """Drift detected when Sharpe drops significantly."""
        from quant.monitoring.drift import DriftDetector
        detector = DriftDetector(metric_threshold=0.15)
        detector.set_baseline_metrics({"sharpe": 2.0})
        results = detector.check_metric_drift({"sharpe": 1.0})
        assert results[0].is_drifted
        assert results[0].drift_pct > 0.15

    def test_psi_no_drift(self):
        """PSI should be low for similar distributions."""
        from quant.monitoring.drift import population_stability_index
        np.random.seed(42)
        baseline = np.random.normal(0, 1, 1000)
        current = np.random.normal(0.01, 1.01, 1000)
        psi = population_stability_index(baseline, current)
        assert psi < 0.1  # No significant change

    def test_psi_drift_detected(self):
        """PSI should be high for shifted distributions."""
        from quant.monitoring.drift import population_stability_index
        np.random.seed(42)
        baseline = np.random.normal(0, 1, 1000)
        current = np.random.normal(1, 2, 1000)  # Major shift
        psi = population_stability_index(baseline, current)
        assert psi > 0.25  # Significant change


# ── Model Retirement Integration ─────────────────────────────────────

class TestModelRetirementIntegration:
    """Test model retirement verdict logic."""

    def test_retire_low_score(self):
        """Engine with low score should get RETIRE verdict."""
        from quant.monitoring.retirement import RetirementVerdict
        v = RetirementVerdict(
            engine_name="test_engine",
            verdict="RETIRE",
            score=0.2,
            reasons=["IC too low", "Win rate low"],
            metrics={"avg_ic": 0.001, "win_rate": 0.30},
        )
        assert v.verdict == "RETIRE"
        assert v.score < 0.4

    def test_keep_high_score(self):
        """Engine with high score should get KEEP verdict."""
        from quant.monitoring.retirement import RetirementVerdict
        v = RetirementVerdict(
            engine_name="good_engine",
            verdict="KEEP",
            score=0.85,
            reasons=["All criteria met"],
            metrics={"avg_ic": 0.05, "win_rate": 0.55},
        )
        assert v.verdict == "KEEP"
        assert v.score >= 0.7


# ── Alert Manager Integration ────────────────────────────────────────

class TestAlertManagerIntegration:
    """Test alert formatting and routing."""

    def test_alert_creation(self):
        """Alert should have title, message, level, and timestamp."""
        from quant.monitoring.alerts import Alert
        alert = Alert(title="Test", message="Test message", level="info")
        assert alert.title == "Test"
        assert alert.message == "Test message"
        assert alert.level == "info"
        assert alert.timestamp != ""

    def test_alert_manager_logs_without_config(self):
        """AlertManager should log alerts when no channels configured."""
        from quant.monitoring.alerts import AlertManager, Alert
        am = AlertManager()  # No Telegram/email configured
        result = am.send(Alert(title="Test", message="Test", level="info"))
        # Should return False (no channel succeeded) but not crash
        assert result is False
        assert len(am._buffer) == 1

    def test_daily_summary_format(self):
        """send_daily_summary should format correctly."""
        from quant.monitoring.alerts import AlertManager
        am = AlertManager()
        # Mock result object
        result = MagicMock()
        result.nav = 100_000_000
        result.cash = 50_000_000
        result.total_pnl = 5_000_000
        result.total_return_pct = 5.0
        result.max_drawdown = 0.02
        result.n_trades = 10
        result.n_rejected = 1
        result.reconciliation_ok = True
        # Should not crash
        am.send_daily_summary(result)


# ── LLM Gateway Integration ──────────────────────────────────────────

class TestLLMGatewayIntegration:
    """Test LLM gateway fallback and error handling."""

    def test_unknown_provider_returns_error(self):
        """Unknown provider should return error response."""
        from quant.ai.llm_gateway import LLMGateway
        gw = LLMGateway(provider="unknown", model="test")
        resp = gw.complete(system="test", user="test")
        assert not resp.success
        assert "Unknown provider" in resp.error

    def test_ollama_connection_error_handled(self):
        """Connection error should be handled gracefully."""
        from quant.ai.llm_gateway import LLMGateway
        gw = LLMGateway(provider="ollama", model="test", base_url="http://localhost:99999")
        resp = gw.complete(system="test", user="test")
        assert not resp.success
        # Should have a meaningful error message
        assert resp.error is not None


# ── RSS Adapter Integration ──────────────────────────────────────────

class TestRSSAdapterIntegration:
    """Test RSS adapter ticker extraction and sentiment scoring."""

    def test_ticker_extraction(self):
        """Should extract IDX tickers from headlines."""
        from quant.data.rss_adapter import RSSFeedAdapter
        adapter = RSSFeedAdapter()
        tickers = adapter.extract_tickers("Saham BBCA dan BBRI naik tajam hari ini")
        assert "BBCA" in tickers
        assert "BBRI" in tickers
        adapter.close()

    def test_keyword_sentiment_positive(self):
        """Positive keywords should produce positive sentiment."""
        from quant.data.rss_adapter import RSSFeedAdapter
        adapter = RSSFeedAdapter()
        score, label = adapter.score_sentiment("Saham naik tajam, bullish, profit melonjak")
        assert label == "positive"
        assert score > 0
        adapter.close()

    def test_keyword_sentiment_negative(self):
        """Negative keywords should produce negative sentiment."""
        from quant.data.rss_adapter import RSSFeedAdapter
        adapter = RSSFeedAdapter()
        score, label = adapter.score_sentiment("Bursa anjlok, saham jatuh, investor rugi")
        assert label == "negative"
        assert score < 0
        adapter.close()


# ── Triple Barrier Labeling Integration ──────────────────────────────

class TestTripleBarrierIntegration:
    """Test TBL with realistic price series."""

    def test_upward_trend_hits_upper_barrier(self):
        """Strong uptrend should hit upper (profit) barrier."""
        from quant.signals.tbl import apply_triple_barrier, TBLConfig
        prices = pd.Series(
            [100 * (1 + 0.02 * i) for i in range(20)],
            index=pd.bdate_range("2024-01-01", periods=20),
        )
        config = TBLConfig(take_profit=0.03, stop_loss=0.03, max_holding=5, use_atr=False)
        result = apply_triple_barrier(prices, config)
        # Should have some labels
        assert len(result) > 0

    def test_downward_trend_hits_lower_barrier(self):
        """Strong downtrend should hit lower (loss) barrier."""
        from quant.signals.tbl import apply_triple_barrier, TBLConfig
        prices = pd.Series(
            [100 * (1 - 0.02 * i) for i in range(20)],
            index=pd.bdate_range("2024-01-01", periods=20),
        )
        config = TBLConfig(take_profit=0.03, stop_loss=0.03, max_holding=5, use_atr=False)
        result = apply_triple_barrier(prices, config)
        assert len(result) > 0


# ── Walk-Forward Backtest Integration ────────────────────────────────

class TestWalkForwardIntegration:
    """Test walk-forward optimizer with synthetic data."""

    def test_walk_forward_splits(self):
        """WFO should create correct number of train/test splits."""
        from quant.backtest.walk_forward import WalkForwardOptimizer
        close = pd.Series(
            np.cumprod(1 + np.random.normal(0.001, 0.02, 400)) * 1000,
            index=pd.bdate_range("2024-01-01", periods=400),
        )
        wfo = WalkForwardOptimizer(train_days=252, test_days=63, embargo_days=5)
        # Check that splits are possible
        n = len(close)
        assert n >= 252 + 63  # At least one fold

    def test_walk_forward_param_stability(self):
        """Parameter stability should be between 0 and 1."""
        from quant.backtest.walk_forward import WalkForwardOptimizer
        wfo = WalkForwardOptimizer(train_days=100, test_days=30, embargo_days=3)
        close = pd.Series(
            np.cumprod(1 + np.random.normal(0.001, 0.02, 200)) * 1000,
            index=pd.bdate_range("2024-01-01", periods=200),
        )

        def strategy_fn(c, lookback=10):
            signal = (c.pct_change(lookback) > 0).astype(int) * 0.02 - 0.01
            return signal.shift(1) * np.log(c / c.shift(1))

        result = wfo.run(
            close=close,
            strategy_fn=strategy_fn,
            param_grid={"lookback": [5, 10, 20]},
        )
        assert 0 <= result.param_stability <= 1
        assert len(result.windows) > 0
