"""Gigantic AI — multi-agent LLM system for quant trading.

Agents:
  - Miner: LLM-guided factor discovery
  - Screener: Regime-conditioned stock selection
  - Trader: Risk-constrained portfolio allocation
  - Risk Manager: Fail-closed risk gate
  - Sentiment: IndoBERT-based news sentiment
  - Orchestrator: Full pipeline coordinator
"""

from quant.ai.llm_gateway import LLMGateway, LLMResponse
from quant.ai.miner_agent import MinerAgent, FactorProposal, DiscoveryResult
from quant.ai.screener_agent import ScreenerAgent, ScreeningResult
from quant.ai.trader_agent import TraderAgent, TradingDecision
from quant.ai.risk_agent import RiskManagerAgent, RiskCheckResult, RiskState
from quant.ai.sentiment_agent import SentimentAnalystAgent, SentimentSummary
from quant.ai.orchestrator import GiganticAI, GiganticAIResult

__all__ = [
    "LLMGateway", "LLMResponse",
    "MinerAgent", "FactorProposal", "DiscoveryResult",
    "ScreenerAgent", "ScreeningResult",
    "TraderAgent", "TradingDecision",
    "RiskManagerAgent", "RiskCheckResult", "RiskState",
    "SentimentAnalystAgent", "SentimentSummary",
    "GiganticAI", "GiganticAIResult",
]
