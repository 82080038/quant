"""LSTM predictor for sequential temporal dynamics.

Bidirectional LSTM with attention mechanism for stock price prediction.
Uses CUDA:1 when available.
"""

import torch
import torch.nn as nn
import numpy as np
from typing import Optional
from dataclasses import dataclass


@dataclass
class LSTMConfig:
    """LSTM model configuration."""
    input_dim: int = 10
    hidden_dim: int = 64
    n_layers: int = 2
    bidirectional: bool = True
    dropout: float = 0.2
    seq_len: int = 20
    learning_rate: float = 1e-3
    n_epochs: int = 50
    batch_size: int = 32


class AttentionLayer(nn.Module):
    """Simple attention layer for LSTM outputs."""

    def __init__(self, hidden_dim: int):
        super().__init__()
        self.attention = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.Tanh(),
            nn.Linear(hidden_dim // 2, 1),
        )

    def forward(self, lstm_output: torch.Tensor) -> torch.Tensor:
        """Apply attention over LSTM timesteps.

        Args:
            lstm_output: (batch, seq_len, hidden_dim)

        Returns:
            (batch, hidden_dim) — context vector
        """
        attention_weights = self.attention(lstm_output)  # (batch, seq_len, 1)
        attention_weights = torch.softmax(attention_weights, dim=1)
        context = torch.sum(attention_weights * lstm_output, dim=1)  # (batch, hidden_dim)
        return context


class LSTMPredictor(nn.Module):
    """LSTM with attention for time series prediction.

    Input: (batch, seq_len, input_dim)
    Output: (batch, 1) — predicted signal [-1, 1]
    """

    def __init__(self, config: LSTMConfig = None):
        super().__init__()
        self.config = config or LSTMConfig()

        self.lstm = nn.LSTM(
            input_size=self.config.input_dim,
            hidden_size=self.config.hidden_dim,
            num_layers=self.config.n_layers,
            batch_first=True,
            bidirectional=self.config.bidirectional,
            dropout=self.config.dropout if self.config.n_layers > 1 else 0,
        )

        lstm_out_dim = self.config.hidden_dim * (2 if self.config.bidirectional else 1)
        self.attention = AttentionLayer(lstm_out_dim)

        self.output_head = nn.Sequential(
            nn.Linear(lstm_out_dim, self.config.hidden_dim),
            nn.ReLU(),
            nn.Dropout(self.config.dropout),
            nn.Linear(self.config.hidden_dim, 1),
            nn.Tanh(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Args:
            x: (batch, seq_len, input_dim)

        Returns:
            (batch, 1) — predicted signal
        """
        lstm_out, _ = self.lstm(x)  # (batch, seq_len, hidden_dim * directions)
        context = self.attention(lstm_out)  # (batch, hidden_dim * directions)
        return self.output_head(context)


class LSTMSignalPredictor:
    """Wrapper for LSTM-based signal prediction.

    Usage:
        predictor = LSTMSignalPredictor()
        predictor.fit(X_train, y_train)
        signal = predictor.predict_latest(X_test)
    """

    def __init__(self, config: LSTMConfig = None, device: str = None):
        self.config = config or LSTMConfig()
        self.device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        self.model: Optional[LSTMPredictor] = None
        self.is_fitted = False

    def _create_sequences(self, data: np.ndarray, seq_len: int) -> np.ndarray:
        """Create sliding window sequences."""
        sequences = []
        for i in range(len(data) - seq_len):
            sequences.append(data[i:i + seq_len])
        return np.array(sequences)

    def fit(self, features: np.ndarray, labels: np.ndarray, verbose: bool = False) -> "LSTMSignalPredictor":
        """Train LSTM on sequential data.

        Args:
            features: (n_samples, n_features) chronological
            labels: (n_samples,) target [-1, 1]
            verbose: Print progress

        Returns:
            self
        """
        n_samples, n_features = features.shape
        self.config.input_dim = n_features

        X = self._create_sequences(features, self.config.seq_len)
        y = labels[self.config.seq_len:]

        # Normalize
        self.mean = features.mean(axis=0)
        self.std = features.std(axis=0) + 1e-8
        X_norm = (X - self.mean) / self.std

        self.model = LSTMPredictor(self.config).to(self.device)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=self.config.learning_rate)
        criterion = nn.MSELoss()

        X_tensor = torch.FloatTensor(X_norm).to(self.device)
        y_tensor = torch.FloatTensor(y).unsqueeze(1).to(self.device)

        n_batches = max(1, (len(X_tensor) + self.config.batch_size - 1) // self.config.batch_size)

        for epoch in range(self.config.n_epochs):
            total_loss = 0
            perm = torch.randperm(len(X_tensor))
            for i in range(n_batches):
                idx = perm[i * self.config.batch_size:(i + 1) * self.config.batch_size]
                if len(idx) == 0:
                    continue
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
                print(f"  LSTM Epoch {epoch+1}/{self.config.n_epochs}, Loss: {total_loss/n_batches:.6f}")

        self.is_fitted = True
        return self

    def predict(self, features: np.ndarray) -> np.ndarray:
        """Generate predictions for all sequences."""
        if not self.is_fitted or self.model is None:
            raise RuntimeError("LSTM not fitted. Call fit() first.")

        X = self._create_sequences(features, self.config.seq_len)
        X_norm = (X - self.mean) / self.std

        with torch.no_grad():
            x_tensor = torch.FloatTensor(X_norm).to(self.device)
            preds = self.model(x_tensor)

        return preds.cpu().numpy().flatten()

    def predict_latest(self, features: np.ndarray) -> float:
        """Predict signal for the latest sequence."""
        if len(features) < self.config.seq_len:
            return 0.0
        latest = features[-self.config.seq_len:]
        latest_norm = (latest - self.mean) / self.std
        with torch.no_grad():
            x = torch.FloatTensor(latest_norm).unsqueeze(0).to(self.device)
            pred = self.model(x)
        return float(pred.cpu().numpy()[0, 0])
