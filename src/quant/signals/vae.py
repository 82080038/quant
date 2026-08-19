"""VAE feature extractor for dimensionality reduction.

Variational Autoencoder that learns compressed representations of
technical indicators and price features for downstream models.
"""

import torch
import torch.nn as nn
import numpy as np
import pandas as pd
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class VAEConfig:
    """VAE configuration."""
    input_dim: int = 60         # Number of features
    hidden_dim: int = 128
    latent_dim: int = 32
    learning_rate: float = 1e-3
    n_epochs: int = 100
    batch_size: int = 64
    dropout: float = 0.1


class VAE(nn.Module):
    """Variational Autoencoder for feature extraction.

    Encoder: input → hidden → (mu, logvar) → latent
    Decoder: latent → hidden → reconstructed
    """

    def __init__(self, config: VAEConfig = None):
        super().__init__()
        self.config = config or VAEConfig()

        # Encoder
        self.encoder = nn.Sequential(
            nn.Linear(self.config.input_dim, self.config.hidden_dim),
            nn.LayerNorm(self.config.hidden_dim),
            nn.ReLU(),
            nn.Dropout(self.config.dropout),
        )
        self.fc_mu = nn.Linear(self.config.hidden_dim, self.config.latent_dim)
        self.fc_logvar = nn.Linear(self.config.hidden_dim, self.config.latent_dim)

        # Decoder
        self.decoder = nn.Sequential(
            nn.Linear(self.config.latent_dim, self.config.hidden_dim),
            nn.LayerNorm(self.config.hidden_dim),
            nn.ReLU(),
            nn.Dropout(self.config.dropout),
            nn.Linear(self.config.hidden_dim, self.config.input_dim),
        )

    def encode(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Encode input to latent space."""
        h = self.encoder(x)
        mu = self.fc_mu(h)
        logvar = self.fc_logvar(h)
        return mu, logvar

    def reparameterize(self, mu: torch.Tensor, logvar: torch.Tensor) -> torch.Tensor:
        """Reparameterization trick: z = mu + std * eps."""
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std

    def decode(self, z: torch.Tensor) -> torch.Tensor:
        """Decode latent to reconstructed input."""
        return self.decoder(z)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Forward pass: returns reconstruction, mu, logvar."""
        mu, logvar = self.encode(x)
        z = self.reparameterize(mu, logvar)
        recon = self.decode(z)
        return recon, mu, logvar

    def get_latent(self, x: torch.Tensor) -> torch.Tensor:
        """Get latent representation (for feature extraction)."""
        mu, _ = self.encode(x)
        return mu


def vae_loss(recon: torch.Tensor, x: torch.Tensor,
             mu: torch.Tensor, logvar: torch.Tensor,
             beta: float = 1.0) -> torch.Tensor:
    """VAE loss = Reconstruction loss + KL divergence."""
    recon_loss = nn.functional.mse_loss(recon, x, reduction='sum')
    kld = -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp())
    return recon_loss + beta * kld


class VAEFeatureExtractor:
    """Wrapper for VAE-based feature extraction.

    Usage:
        extractor = VAEFeatureExtractor()
        extractor.fit(train_features)
        latent = extractor.transform(test_features)
    """

    def __init__(self, config: VAEConfig = None, device: str = None):
        self.config = config or VAEConfig()
        self.device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        self.model: Optional[VAE] = None
        self.is_fitted = False

    def fit(self, features: np.ndarray, verbose: bool = False) -> "VAEFeatureExtractor":
        """Train VAE on features.

        Args:
            features: Shape (n_samples, n_features)
            verbose: Print training progress

        Returns:
            self
        """
        n_samples, n_features = features.shape
        self.config.input_dim = n_features

        self.model = VAE(self.config).to(self.device)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=self.config.learning_rate)

        # Normalize features
        self.mean = features.mean(axis=0)
        self.std = features.std(axis=0) + 1e-8
        features_norm = (features - self.mean) / self.std

        dataset = torch.FloatTensor(features_norm).to(self.device)
        n_batches = (len(dataset) + self.config.batch_size - 1) // self.config.batch_size

        for epoch in range(self.config.n_epochs):
            total_loss = 0
            perm = torch.randperm(len(dataset))
            for i in range(n_batches):
                batch = dataset[perm[i * self.config.batch_size:(i + 1) * self.config.batch_size]]
                recon, mu, logvar = self.model(batch)
                loss = vae_loss(recon, batch, mu, logvar)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                total_loss += loss.item()

            if verbose and (epoch + 1) % 10 == 0:
                print(f"  VAE Epoch {epoch+1}/{self.config.n_epochs}, Loss: {total_loss/len(dataset):.4f}")

        self.is_fitted = True
        return self

    def transform(self, features: np.ndarray) -> np.ndarray:
        """Transform features to latent space."""
        if not self.is_fitted or self.model is None:
            raise RuntimeError("VAE not fitted. Call fit() first.")

        features_norm = (features - self.mean) / self.std
        with torch.no_grad():
            x = torch.FloatTensor(features_norm).to(self.device)
            latent = self.model.get_latent(x)
        return latent.cpu().numpy()

    def fit_transform(self, features: np.ndarray, verbose: bool = False) -> np.ndarray:
        """Fit and transform in one step."""
        self.fit(features, verbose=verbose)
        return self.transform(features)
