"""Minimal alpha rescue pipeline stubs."""

import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class ReformConfig:
    vol_target: float = 0.15
    max_position: float = 1.0
    meta_label_confidence: float = 0.6


def volatility_targeted_position_size(signal, returns, target_vol=0.15):
    """Size position based on volatility targeting."""
    vol = returns.rolling(63).std().fillna(0.01)
    raw = signal / (vol * np.sqrt(252))
    return raw.clip(-1, 1)


def build_volatility_features(prices, windows=(5, 10, 20, 60)):
    """Build volatility features."""
    features = {}
    for w in windows:
        features[f"vol_{w}"] = prices.pct_change().rolling(w).std()
    return pd.DataFrame(features)


def build_meta_label_features(prices, signals):
    """Build meta-labeling features."""
    features = build_volatility_features(prices)
    features["signal"] = signals
    features["momentum"] = prices.pct_change(20)
    return features


def generate_meta_labeled_signals(signals, meta_confidence, threshold=0.6):
    """Filter signals by meta-label confidence."""
    return signals * (meta_confidence > threshold).astype(float)


def detect_regime(returns, window=63):
    """Simple regime detection based on trend and volatility."""
    ma = returns.rolling(window).mean()
    vol = returns.rolling(window).std()
    regimes = pd.Series("sideways", index=returns.index)
    regimes[ma > vol] = "bull"
    regimes[ma < -vol] = "bear"
    return regimes


def _lgbm_device():
    return "cpu"
