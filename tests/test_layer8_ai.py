"""Layer 8: AI agent tests.

Tests:
- llm_gateway: LLM gateway (mock, no actual LLM calls)
- orchestrator: Pipeline coordination
- agent data structures

Known bugs found:
- sentiment.py: _analyze_news imports `quant.analysis.news_sentiment` which
  does not exist. News NLP functionality is broken.
"""

import pytest
from unittest.mock import patch, MagicMock


# ── LLM Gateway ──────────────────────────────────────────────────────────────

class TestLLMGateway:
    """Test LLM gateway (no actual LLM calls)."""

    def test_gateway_creation(self):
        from quant.ai.llm_gateway import LLMGateway
        gw = LLMGateway(provider="ollama", model="test-model", base_url="http://localhost:11434")
        assert gw.provider == "ollama"
        assert gw.model == "test-model"

    def test_unknown_provider(self):
        from quant.ai.llm_gateway import LLMGateway
        gw = LLMGateway(provider="unknown", model="test")
        resp = gw.complete(system="test", user="test")
        assert not resp.success
        assert "Unknown provider" in resp.error

    def test_ollama_not_running(self):
        from quant.ai.llm_gateway import LLMGateway
        gw = LLMGateway(provider="ollama", model="test", base_url="http://localhost:99999")
        resp = gw.complete(system="test", user="test")
        assert not resp.success

    def test_llm_response_dataclass(self):
        from quant.ai.llm_gateway import LLMResponse
        resp = LLMResponse(text="hello", model="test", latency_ms=100, success=True)
        assert resp.text == "hello"
        assert resp.success
        assert resp.parsed is None


# ── Agent Data Structures ────────────────────────────────────────────────────

class TestAgentStructures:
    """Test AI agent data structures (no LLM calls).

    Actual field names verified from source code:
    - FactorProposal: name, description, category, formula_text, code, dependencies, hypothesis, expected_ic
    - ScreeningResult: regime, selected_tickers, scores, factor_weights, regime_confidence, llm_rationale
    - TradingDecision: weights, timing_adjusted, regime, method, confidence, llm_rationale, rejected
    - RiskState: nav, positions, sector_exposure, current_drawdown, peak_nav, is_halted, halt_reason
    - GiganticAIResult: discovery, screening, trading, risk_check, final_weights, sentiment_signals, pipeline_success, errors
    - SentimentSummary: ticker, avg_sentiment, sentiment_momentum, news_count, positive_pct, negative_pct, signal_value, confidence
    """

    def test_factor_proposal(self):
        from quant.ai.miner_agent import FactorProposal
        proposal = FactorProposal(
            name="custom_momentum",
            description="20-day momentum smoothed over 5 days",
            category="alpha",
            formula_text="close.pct_change(20).rolling(5).mean()",
            code="df['close'].pct_change(20).rolling(5).mean()",
            dependencies=["close"],
            hypothesis="Higher momentum predicts positive returns",
            expected_ic=0.05,
        )
        assert proposal.name == "custom_momentum"
        assert proposal.category == "alpha"
        assert proposal.expected_ic == 0.05

    def test_screening_result(self):
        from quant.ai.screener_agent import ScreeningResult
        result = ScreeningResult(
            regime="bull",
            selected_tickers=["BBCA.JK", "BBRI.JK"],
            scores={"BBCA.JK": 0.8, "BBRI.JK": 0.6},
            factor_weights={"momentum": 0.4, "value": 0.3},
            regime_confidence=0.85,
            llm_rationale="Bull regime detected",
        )
        assert result.regime == "bull"
        assert len(result.selected_tickers) == 2
        assert result.regime_confidence == 0.85

    def test_trading_decision(self):
        from quant.ai.trader_agent import TradingDecision
        decision = TradingDecision(
            weights={"BBCA.JK": 0.15, "BBRI.JK": 0.10},
            timing_adjusted={"BBCA.JK": 0.0},
            regime="bull",
            method="hrp_mu",
            confidence=0.75,
            llm_rationale="Bull regime, allocate to strong fundamentals",
        )
        assert decision.method == "hrp_mu"
        assert len(decision.weights) == 2
        assert decision.rejected == []  # Default is empty list

    def test_risk_check_result(self):
        from quant.ai.risk_agent import RiskCheckResult
        result = RiskCheckResult(
            passed=True,
            violations=[],
            var_95=0.02,
            es_95=0.03,
        )
        assert result.passed
        assert result.var_95 == 0.02

    def test_risk_state(self):
        from quant.ai.risk_agent import RiskState
        state = RiskState(
            nav=100_000_000,
            positions={"BBCA.JK": 15_000_000},
            sector_exposure={"Finance": 0.15},
            current_drawdown=0.05,
            peak_nav=105_000_000,
            is_halted=False,
        )
        assert state.nav == 100_000_000
        assert not state.is_halted
        assert state.peak_nav == 105_000_000

    def test_gigantic_ai_result(self):
        from quant.ai.orchestrator import GiganticAIResult
        result = GiganticAIResult(
            discovery=None,
            screening=None,
            trading=None,
            risk_check=None,
            final_weights={"BBCA.JK": 0.15},
            sentiment_signals={},
            pipeline_success=True,
            errors=[],
        )
        assert result.final_weights["BBCA.JK"] == 0.15
        assert result.pipeline_success == True
        assert result.errors == []

    def test_sentiment_summary(self):
        from quant.ai.sentiment_agent import SentimentSummary
        summary = SentimentSummary(
            ticker="BBCA.JK",
            avg_sentiment=0.5,
            sentiment_momentum=0.1,
            news_count=10,
            positive_pct=0.7,
            negative_pct=0.2,
            signal_value=0.5,
            confidence=0.8,
        )
        assert summary.ticker == "BBCA.JK"
        assert summary.avg_sentiment == 0.5
        assert summary.news_count == 10


# ── Orchestrator ─────────────────────────────────────────────────────────────

class TestOrchestrator:
    """Test orchestrator structure (no actual pipeline run)."""

    def test_orchestrator_creation(self):
        from quant.ai.orchestrator import GiganticAI
        orch = GiganticAI()
        assert orch is not None

    def test_regime_factor_weights_exist(self):
        from quant.ai.screener_agent import ScreenerAgent
        assert hasattr(ScreenerAgent, 'REGIME_FACTOR_WEIGHTS')
        weights = ScreenerAgent.REGIME_FACTOR_WEIGHTS
        assert "bull" in weights
        assert "bear" in weights
        assert "sideways" in weights
        assert "crisis" in weights
