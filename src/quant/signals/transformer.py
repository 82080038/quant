"""Transformer model for time series prediction.

Uses multi-head self-attention to capture long-range dependencies
in price sequences. Designed for daily OHLCV + technical features.
"""

import torch
import torch.nn as nn
import numpy as np
import pandas as pd
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class TransformerConfig:
    """Transformer model configuration."""
    input_dim: int = 10          # Features per timestep
    d_model: int = 64            # Model dimension
    n_heads: int = 4             # Attention heads
    n_layers: int = 2            # Transformer layers
    ff_dim: int = 256            # Feedforward dimension
    seq_len: int = 20            # Lookback window
    dropout: float = 0.1
    learning_rate: float = 1e-4
    n_epochs: int = 50
    batch_size: int = 32


class PositionalEncoding(nn.Module):
    """Sinusoidal positional encoding."""

    def __init__(self, d_model: int, max_len: int = 500):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-np.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer('pe', pe.unsqueeze(0))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, :x.size(1)]


class TimeSeriesTransformer(nn.Module):
    """Transformer for time series prediction.

    Input: (batch, seq_len, input_dim)
    Output: (batch, 1) — predicted next-day return probability
    """

    def __init__(self, config: TransformerConfig = None):
        super().__init__()
        self.config = config or TransformerConfig()

        # Input projection
        self.input_proj = nn.Linear(self.config.input_dim, self.config.d_model)
        self.pos_enc = PositionalEncoding(self.config.d_model, self.config.seq_len + 10)

        # Transformer encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=self.config.d_model,
            nhead=self.config.n_heads,
            dim_feedforward=self.config.ff_dim,
            dropout=self.config.dropout,
            batch_first=True,
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, self.config.n_layers)

        # Output head
        self.output_head = nn.Sequential(
            nn.Linear(self.config.d_model, self.config.d_model // 2),
            nn.ReLU(),
            nn.Dropout(self.config.dropout),
            nn.Linear(self.config.d_model // 2, 1),
            nn.Tanh(),  # Output in [-1, 1]
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Args:
            x: (batch, seq_len, input_dim)

        Returns:
            (batch, 1) — predicted signal [-1, 1]
        """
        x = self.input_proj(x)
        x = self.pos_enc(x)
        x = self.encoder(x)
        # Use last timestep for prediction
        x = x[:, -1, :]
        return self.output_head(x)


class TransformerPredictor:
    """Wrapper for Transformer-based prediction.

    Usage:
        predictor = TransformerPredictor()
        predictor.fit(X_train, y_train)
        signals = predictor.predict(X_test)
    """

    def __init__(self, config: TransformerConfig = None, device: str = None):
        self.config = config or TransformerConfig()
        self.device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        self.model: Optional[TimeSeriesTransformer] = None
        self.is_fitted = False

    def _create_sequences(self, data: np.ndarray, seq_len: int) -> np.ndarray:
        """Create sliding window sequences from data.

        Args:
            data: (n_samples, n_features)
            seq_len: Sequence length

        Returns:
            (n_samples - seq_len, seq_len, n_features)
        """
        sequences = []
        for i in range(len(data) - seq_len):
            sequences.append(data[i:i + seq_len])
        return np.array(sequences)

    def fit(self, features: np.ndarray, labels: np.ndarray, verbose: bool = False) -> "TransformerPredictor":
        """Train transformer on sequential data.

        Args:
            features: (n_samples, n_features) — chronological features
            labels: (n_samples,) — target labels [-1, 1]
            verbose: Print progress

        Returns:
            self
        """
        n_samples, n_features = features.shape
        self.config.input_dim = n_features

        # Create sequences
        X = self._create_sequences(features, self.config.seq_len)
        y = labels[self.config.seq_len:]

        # Normalize features
        self.mean = features.mean(axis=0)
        self.std = features.std(axis=0) + 1e-8
        X_norm = (X - self.mean) / self.std

        self.model = TimeSeriesTransformer(self.config).to(self.device)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=self.config.learning_rate)
        criterion = nn.MSELoss()

        X_tensor = torch.FloatTensor(X_norm).to(self.device)
        y_tensor = torch.FloatTensor(y).unsqueeze(1).to(self.device)

        n_batches = (len(X_tensor) + self.config.batch_size - 1) // self.config.batch_size

        for epoch in range(self.config.n_epochs):
            total_loss = 0
            perm = torch.randperm(len(X_tensor))
            for i in range(n_batches):
                idx = perm[i * self.config.batch_size:(i + 1) * self.config.batch_size]
                batch_x = X_tensor[idx]
                batch_y = y_tensor[idx]
                pred = self.model(batch_x)
                loss = criterion(pred, batch_y)
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()
                total_loss += loss.item()

            if verbose and (epoch + 1) % 10 == 0:
                print(f"  Transformer Epoch {epoch+1}/{self.config.n_epochs}, Loss: {total_loss/n_batches:.6f}")

        self.is_fitted = True
        return self

    def predict(self, features: np.ndarray) -> np.ndarray:
        """Generate predictions for latest sequences.

        Args:
            features: (n_samples, n_features) — chronological features

        Returns:
            (n_samples - seq_len,) — predicted signals [-1, 1]
        """
        if not self.is_fitted or self.model is None:
            raise RuntimeError("Transformer not fitted. Call fit() first.")

        X = self._create_sequences(features, self.config.seq_len)
        X_norm = (X - self.mean) / self.std

        with torch.no_grad():
            x_tensor = torch.FloatTensor(X_norm).to(self.device)
            preds = self.model(x_tensor)

        return preds.cpu().numpy().flatten()

    def predict_latest(self, features: np.ndarray) -> float:
        """Predict signal for the latest available sequence.

        Args:
            features: (n_samples, n_features) — chronological features

        Returns:
            Signal value [-1, 1]
        """
        if len(features) < self.config.seq_len:
            return 0.0
        latest = features[-self.config.seq_len:]
        latest_norm = (latest - self.mean) / self.std
        with torch.no_grad():
            x = torch.FloatTensor(latest_norm).unsqueeze(0).to(self.device)
            pred = self.model(x)
        return float(pred.cpu().numpy()[0, 0])
