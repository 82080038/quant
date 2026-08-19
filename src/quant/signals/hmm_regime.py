"""HMM Volatility Regime Detector.

Uses Hidden Markov Model to detect market regimes (low/high volatility,
trending/ranging). Provides regime-aware signal adjustment.

Regimes:
  0: Low volatility / trending → momentum signals work
  1: High volatility / mean-reverting → reversal signals work
  2: Crisis / extreme volatility → reduce position size

The HMM is fitted on returns + volatility features using hmmlearn.

References:
  - Hamilton, J.D. (1989). "A New Approach to the Economic Analysis of
    Nonstationary Time Series." Econometrica, 57(2), 357-384.
  - Bulla, J. & Bulla, I. (2006). "Stylized facts of financial time
    series and hidden semi-Markov models."
  - Costa, M. & Gottardo, S. (2023). "HMM-based regime detection for
    portfolio management." Quantitative Finance, 23(7).

Note: If hmmlearn is not installed, falls back to a simple volatility
percentile-based regime classifier.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # suppress HMM convergence warnings

RegimeType = Literal["trending", "ranging", "crisis"]


@dataclass
class RegimeResult:
    """Regime detection result."""
    regime: int
    regime_name: str
    confidence: float
    volatility_pctile: float
    transition_prob: list[float]
    signal_adjustment: float  # multiplier for momentum signals


class HMMRegimeDetector:
    """HMM-based volatility regime detector.

    Fits a 3-state Gaussian HMM on returns and volatility to classify
    the current market regime. Provides signal adjustment recommendations.
    """

    def __init__(
        self,
        n_states: int = 3,
        lookback: int = 252,
        min_history: int = 60,
    ) -> None:
        self.n_states = n_states
        self.lookback = lookback
        self.min_history = min_history
        self._model = None
        self._is_fitted = False
        self._fit_attempted = False  # avoid re-fitting on every call

    def _prepare_features(self, close: pd.Series) -> np.ndarray:
        """Prepare feature matrix for HMM."""
        returns = close.pct_change().dropna()
        vol = returns.rolling(20).std()
        # Align
        features = pd.DataFrame({
            "returns": returns,
            "volatility": vol,
        }).dropna()
        if len(features) < self.min_history:
            return np.empty((0, 2))
        # Use recent lookback window
        features = features.iloc[-self.lookback:]
        return features.values

    def fit(self, close: pd.Series) -> bool:
        """Fit HMM on historical data.

        Args:
            close: Close price series.

        Returns:
            True if fitting succeeded.
        """
        X = self._prepare_features(close)
        if len(X) < self.min_history:
            logger.warning("HMM: insufficient data (%d < %d)", len(X), self.min_history)
            return False

        try:
            import warnings as _w
            _w.filterwarnings("ignore", message=".*not converging.*")
            _w.filterwarnings("ignore", category=DeprecationWarning)
            from hmmlearn.hmm import GaussianHMM
            import warnings as _warn
            self._model = GaussianHMM(
                n_components=self.n_states,
                covariance_type="diag",  # more stable than "full"
                n_iter=50,
                random_state=42,
                tol=1e-3,
            )
            with _warn.catch_warnings():
                _warn.simplefilter("ignore")
                self._model.fit(X)
            self._is_fitted = True
            logger.info("HMM fitted with %d samples, %d states", len(X), self.n_states)
            return True
        except ImportError:
            logger.warning("hmmlearn not installed, using fallback regime detection")
            self._model = None
            self._is_fitted = False
            return False
        except Exception as exc:
            logger.warning("HMM fitting failed: %s", exc)
            self._model = None
            self._is_fitted = False
            return False

    def detect(self, close: pd.Series) -> RegimeResult:
        """Detect current market regime.

        Args:
            close: Close price series.

        Returns:
            RegimeResult with regime classification and signal adjustment.
        """
        returns = close.pct_change().dropna()
        vol = returns.rolling(20).std()
        current_vol = float(vol.iloc[-1]) if not vol.empty else 0.0

        # Volatility percentile (for fallback and confidence)
        vol_history = vol.dropna().iloc[-self.lookback:] if len(vol) > 0 else pd.Series()
        if len(vol_history) >= 20:
            vol_pctile = float(vol_history.rank(pct=True).iloc[-1])
        else:
            vol_pctile = 0.5

        if self._is_fitted and self._model is not None:
            try:
                X = self._prepare_features(close)
                if len(X) >= 2:
                    states = self._model.predict(X)
                    current_state = int(states[-1])
                    # Get transition probabilities
                    transmat = self._model.transmat_
                    transition_prob = list(transmat[current_state])

                    # Classify states by mean volatility
                    means = self._model.means_
                    vol_order = np.argsort(means[:, 1])  # sort by volatility mean
                    # State with lowest vol = trending, highest = crisis
                    regime_map = {
                        vol_order[0]: ("trending", 1.2),   # momentum works
                        vol_order[1]: ("ranging", 0.8),    # mean-reversion works
                        vol_order[2]: ("crisis", 0.3),     # reduce exposure
                    }
                    regime_name, signal_adj = regime_map.get(
                        current_state, ("ranging", 0.8)
                    )
                    confidence = float(max(transition_prob))

                    return RegimeResult(
                        regime=current_state,
                        regime_name=regime_name,
                        confidence=confidence,
                        volatility_pctile=vol_pctile,
                        transition_prob=transition_prob,
                        signal_adjustment=signal_adj,
                    )
            except Exception as exc:
                logger.debug("HMM predict failed: %s", exc)

        # Fallback: volatility percentile-based regime
        if vol_pctile > 0.8:
            regime_name = "crisis"
            signal_adj = 0.3
            regime_id = 2
        elif vol_pctile > 0.5:
            regime_name = "ranging"
            signal_adj = 0.8
            regime_id = 1
        else:
            regime_name = "trending"
            signal_adj = 1.2
            regime_id = 0

        return RegimeResult(
            regime=regime_id,
            regime_name=regime_name,
            confidence=0.5,
            volatility_pctile=vol_pctile,
            transition_prob=[0.33, 0.33, 0.34],
            signal_adjustment=signal_adj,
        )

    def compute_signal(self, close: pd.Series) -> tuple[float, float, str]:
        """Compute regime-based signal adjustment.

        Returns:
            (signal_value [-1, +1], confidence [0, 1], rationale)
        """
        if not self._is_fitted and not self._fit_attempted:
            self._fit_attempted = True
            self.fit(close)
        result = self.detect(close)

        # Signal: positive in trending (momentum), negative in crisis
        if result.regime_name == "trending":
            sig = 0.3 * result.signal_adjustment
        elif result.regime_name == "ranging":
            sig = -0.1  # slight bearish for momentum
        else:  # crisis
            sig = -0.5

        sig = max(-1.0, min(1.0, sig))
        direction = "UP" if sig > 0.05 else "DOWN" if sig < -0.05 else "FLAT"
        rationale = f"regime={result.regime_name}, vol_pctile={result.volatility_pctile:.2f}"

        return sig, result.confidence, rationale
