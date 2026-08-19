"""DL Ensemble combiner — stacks VAE + Transformer + LSTM + XGBoost.

Architecture:
  1. VAE extracts latent features from raw indicators
  2. Transformer captures long-range temporal patterns
  3. LSTM captures sequential dynamics with attention
  4. XGBoost/LightGBM on VAE latent features
  5. Meta-learner combines all predictions → final signal [-1, +1]
"""

import numpy as np
import pandas as pd
from typing import Optional
from dataclasses import dataclass, field

from quant.signals.vae import VAEFeatureExtractor, VAEConfig
from quant.signals.transformer import TransformerPredictor, TransformerConfig
from quant.signals.lstm import LSTMSignalPredictor, LSTMConfig


@dataclass
class EnsembleConfig:
    """Ensemble configuration."""
    vae_config: VAEConfig = field(default_factory=VAEConfig)
    transformer_config: TransformerConfig = field(default_factory=TransformerConfig)
    lstm_config: LSTMConfig = field(default_factory=LSTMConfig)
    use_vae: bool = True
    use_transformer: bool = True
    use_lstm: bool = True
    use_xgboost: bool = True
    # Meta-learner weights (learned or fixed)
    meta_weights: dict = field(default_factory=lambda: {
        "transformer": 0.35,
        "lstm": 0.35,
        "xgboost": 0.30,
    })


class DLEnsemble:
    """Deep Learning Ensemble for signal generation.

    Combines VAE feature extraction with Transformer, LSTM, and
    XGBoost/LightGBM predictions via a meta-learner.
    """

    def __init__(self, config: EnsembleConfig = None, device: str = None):
        self.config = config or EnsembleConfig()
        self.device = device or ("cuda:0" if _cuda_available() else "cpu")
        self.vae: Optional[VAEFeatureExtractor] = None
        self.transformer: Optional[TransformerPredictor] = None
        self.lstm: Optional[LSTMSignalPredictor] = None
        self.xgb_model = None
        self.is_fitted = False

    def fit(self, features: np.ndarray, labels: np.ndarray, verbose: bool = False) -> "DLEnsemble":
        """Train all ensemble components.

        Args:
            features: (n_samples, n_features) chronological
            labels: (n_samples,) target [-1, 1]
            verbose: Print progress

        Returns:
            self
        """
        # 1. VAE feature extraction
        if self.config.use_vae:
            if verbose:
                print("Training VAE...")
            self.vae = VAEFeatureExtractor(self.config.vae_config, device=self.device)
            latent = self.vae.fit_transform(features, verbose=verbose)
        else:
            latent = features

        # 2. Transformer
        if self.config.use_transformer:
            if verbose:
                print("Training Transformer...")
            self.transformer = TransformerPredictor(self.config.transformer_config, device=self.device)
            self.transformer.fit(features, labels, verbose=verbose)

        # 3. LSTM
        if self.config.use_lstm:
            if verbose:
                print("Training LSTM...")
            self.lstm = LSTMSignalPredictor(self.config.lstm_config, device=self.device)
            self.lstm.fit(features, labels, verbose=verbose)

        # 4. XGBoost on VAE latent features
        if self.config.use_xgboost:
            if verbose:
                print("Training XGBoost...")
            try:
                import xgboost as xgb
                self.xgb_model = xgb.XGBRegressor(
                    n_estimators=100,
                    max_depth=4,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    random_state=42,
                )
                # Use latent features for XGBoost
                xgb_labels = labels[self.config.vae_config.n_epochs:] if self.config.use_vae else labels
                # Align labels with latent features
                min_len = min(len(latent), len(labels))
                self.xgb_model.fit(latent[:min_len], labels[:min_len])
            except ImportError:
                if verbose:
                    print("  XGBoost not available, skipping")
                self.xgb_model = None

        self.is_fitted = True
        return self

    def predict(self, features: np.ndarray) -> dict[str, float]:
        """Generate ensemble predictions.

        Args:
            features: (n_samples, n_features) chronological

        Returns:
            Dict with individual model predictions and ensemble signal
        """
        if not self.is_fitted:
            raise RuntimeError("Ensemble not fitted. Call fit() first.")

        predictions = {}

        # Transformer
        if self.transformer is not None:
            try:
                predictions["transformer"] = float(self.transformer.predict_latest(features))
            except Exception:
                predictions["transformer"] = 0.0

        # LSTM
        if self.lstm is not None:
            try:
                predictions["lstm"] = float(self.lstm.predict_latest(features))
            except Exception:
                predictions["lstm"] = 0.0

        # XGBoost
        if self.xgb_model is not None and self.vae is not None:
            try:
                latest_latent = self.vae.transform(features[-1:].reshape(1, -1))
                predictions["xgboost"] = float(self.xgb_model.predict(latest_latent)[0])
            except Exception:
                predictions["xgboost"] = 0.0

        # Weighted ensemble
        weights = self.config.meta_weights
        ensemble_signal = sum(
            weights.get(name, 0) * pred
            for name, pred in predictions.items()
        )

        # Normalize by sum of used weights
        total_weight = sum(weights.get(name, 0) for name in predictions)
        if total_weight > 0:
            ensemble_signal /= total_weight

        predictions["ensemble"] = float(np.clip(ensemble_signal, -1, 1))
        return predictions

    def predict_signal(self, features: np.ndarray) -> float:
        """Get ensemble signal only.

        Returns:
            Signal value [-1, 1]
        """
        return self.predict(features)["ensemble"]


def _cuda_available() -> bool:
    """Check if CUDA is available."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False
