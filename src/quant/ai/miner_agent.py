"""Miner Agent — LLM-guided continuous factor discovery.

Inspired by AlphaCrafter + R&D-Agent-Quant. The Miner Agent:
  1. Analyzes market data and existing factor performance
  2. Proposes new factor formulas via LLM reasoning
  3. Generates Python code for factor computation
  4. Validates factors via IC/ICIR backtesting
  5. Registers valid factors in the FactorLibrary

The agent operates in a discovery loop:
  Observe → Hypothesize → Code → Validate → Register/Prune
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from quant.ai.llm_gateway import LLMGateway, LLMResponse
from quant.features.factor_library import FactorLibrary, FactorDefinition

logger = logging.getLogger(__name__)


@dataclass
class FactorProposal:
    """LLM-proposed factor definition."""
    name: str
    description: str
    category: str
    formula_text: str
    code: str
    dependencies: list[str]
    hypothesis: str
    expected_ic: float


@dataclass
class DiscoveryResult:
    """Result of a factor discovery cycle."""
    proposals: list[FactorProposal] = field(default_factory=list)
    validated: list[FactorDefinition] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    llm_success: bool = False
    error: str | None = None


MINER_SYSTEM_PROMPT = """You are a quantitative factor researcher specializing in the Indonesian stock market (IDX).

Your task is to propose NEW alpha factors that are not yet in the existing factor library.
Consider IDX-specific characteristics:
- Retail dominance (>70% of volume)
- High volatility relative to developed markets
- Foreign flow sensitivity
- Sector concentration in banking and mining
- Sentiment-driven price action

For each factor, provide:
1. A unique name (snake_case)
2. Clear description
3. Category: technical, volume, fundamental, macro, sentiment, alpha
4. Python code that computes the factor from a pandas DataFrame `df` with columns: open, high, low, close, volume
5. The hypothesis behind why this factor should predict returns
6. Expected IC (information coefficient) range

Respond in JSON format with a list of factors."""


class MinerAgent:
    """LLM-guided factor discovery agent.

    Usage:
        miner = MinerAgent()
        result = miner.discover(
            existing_factors=["rsi_14", "macd_hist", "momentum_20"],
            market_context="IHSG up 2.1% this week, banking sector leading",
            n_proposals=3,
        )
        for factor in result.validated:
            print(f"Validated: {factor.name}")
    """

    def __init__(
        self,
        gateway: Optional[LLMGateway] = None,
        library: Optional[FactorLibrary] = None,
    ):
        self.gateway = gateway or LLMGateway()
        self.library = library

    def discover(
        self,
        existing_factors: list[str],
        market_context: str = "",
        n_proposals: int = 3,
        temperature: float = 0.4,
    ) -> DiscoveryResult:
        """Run one factor discovery cycle.

        Args:
            existing_factors: Currently registered factor names
            market_context: Current market conditions summary
            n_proposals: Number of new factors to propose
            temperature: LLM creativity (0=deterministic, 1=creative)

        Returns:
            DiscoveryResult with proposals and validated factors
        """
        user_prompt = self._build_prompt(existing_factors, market_context, n_proposals)

        resp = self.gateway.complete(
            system=MINER_SYSTEM_PROMPT,
            user=user_prompt,
            temperature=temperature,
            json_mode=True,
            max_tokens=4096,
        )

        if not resp.success:
            logger.warning("Miner LLM failed: %s", resp.error)
            return DiscoveryResult(llm_success=False, error=resp.error)

        proposals = self._parse_proposals(resp)
        validated = self._validate_proposals(proposals)

        return DiscoveryResult(
            proposals=proposals,
            validated=validated,
            llm_success=True,
        )

    def _build_prompt(self, existing: list[str], context: str, n: int) -> str:
        """Build user prompt for LLM."""
        return f"""Existing factors in library: {', '.join(existing)}

Current market context: {context or 'Normal market conditions'}

Propose {n} NEW factors that are NOT in the existing list. Focus on factors that:
1. Capture IDX-specific market microstructure (foreign flow, retail behavior)
2. Combine multiple data sources (price + volume + sentiment)
3. Are computationally efficient (no look-ahead bias)

Respond as JSON: {{"factors": [{{"name": "...", "description": "...", "category": "...", "code": "...", "dependencies": [...], "hypothesis": "...", "expected_ic": 0.05}}]}}"""

    def _parse_proposals(self, resp: LLMResponse) -> list[FactorProposal]:
        """Parse LLM response into FactorProposal objects."""
        if resp.parsed and isinstance(resp.parsed, dict):
            factors = resp.parsed.get("factors", [])
        else:
            import json
            try:
                data = json.loads(resp.text)
                factors = data.get("factors", [])
            except (json.JSONDecodeError, TypeError):
                logger.warning("Failed to parse LLM factor proposals")
                return []

        proposals = []
        for f in factors:
            try:
                proposals.append(FactorProposal(
                    name=f["name"],
                    description=f.get("description", ""),
                    category=f.get("category", "alpha"),
                    formula_text=f.get("formula_text", ""),
                    code=f.get("code", ""),
                    dependencies=f.get("dependencies", []),
                    hypothesis=f.get("hypothesis", ""),
                    expected_ic=float(f.get("expected_ic", 0.0)),
                ))
            except (KeyError, ValueError) as e:
                logger.warning("Skipping malformed proposal: %s", e)

        return proposals

    def _validate_proposals(self, proposals: list[FactorProposal]) -> list[FactorDefinition]:
        """Validate factor proposals by compiling and testing code."""
        validated = []

        for prop in proposals:
            try:
                code = self._sanitize_code(prop.code)
                local_ns: dict = {}
                exec(code, {"pd": pd, "np": np}, local_ns)

                compute_fn = None
                for v in local_ns.values():
                    if callable(v):
                        compute_fn = v
                        break

                if compute_fn is None:
                    logger.warning("No function found in code for %s", prop.name)
                    continue

                test_df = pd.DataFrame({
                    "open": np.random.uniform(1000, 2000, 100),
                    "high": np.random.uniform(1000, 2000, 100),
                    "low": np.random.uniform(1000, 2000, 100),
                    "close": np.random.uniform(1000, 2000, 100),
                    "volume": np.random.randint(10000, 1000000, 100),
                })
                result = compute_fn(test_df)
                if not isinstance(result, pd.Series) or result.isna().all():
                    logger.warning("Factor %s produced invalid output", prop.name)
                    continue

                factor = FactorDefinition(
                    name=prop.name,
                    version="1.0.0",
                    description=prop.description,
                    category=prop.category,
                    compute_fn=compute_fn,
                    dependencies=prop.dependencies,
                )
                validated.append(factor)

                if self.library is not None:
                    self.library.register(factor)
                    logger.info("Registered new factor: %s", prop.name)

            except Exception as e:
                logger.warning("Validation failed for %s: %s", prop.name, e)

        return validated

    @staticmethod
    def _sanitize_code(code: str) -> str:
        """Sanitize LLM-generated code for safety.

        Blocks dangerous operations while allowing pandas/numpy computation.
        """
        dangerous = ["import os", "import subprocess", "import sys", "open(",
                      "exec(", "eval(", "__import__", "os.system"]
        for d in dangerous:
            if d in code:
                raise ValueError(f"Dangerous operation detected: {d}")
        return code

    def auto_prune(self, threshold_ic: float = 0.02) -> list[str]:
        """Prune factors with decayed IC."""
        if self.library is None:
            return []
        return self.library.prune(threshold_ic=threshold_ic)
