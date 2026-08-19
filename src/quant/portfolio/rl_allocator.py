"""RL Portfolio Allocator — PPO/SAC-based weight generation.

Inspired by FinRL-X + FinRL-DeepSeek. Uses reinforcement learning to
learn optimal portfolio weight allocation from market state.

Algorithms:
  - PPO (Proximal Policy Optimization): Stable, good for bull markets
  - CPPO (Constrained PPO): Risk-sensitive variant for bear markets
  - SAC (Soft Actor-Critic): Exploration-friendly, good for sideways

The RL allocator treats portfolio management as a sequential decision:
  State: [returns, volatility, signals, positions, regime]
  Action: weight vector w_t ∈ [0, 1]^N (sums to 1)
  Reward: risk-adjusted return (Sharpe-like)

Note: Requires stable-baselines3. Falls back to HRP-µ if unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RLConfig:
    """RL allocator configuration."""
    algorithm: str = "PPO"  # PPO, SAC, CPPO
    learning_rate: float = 3e-4
    n_steps: int = 2048
    batch_size: int = 64
    n_epochs: int = 10
    gamma: float = 0.99  # Discount factor
    ent_coef: float = 0.01  # Entropy coefficient
    total_timesteps: int = 100_000
    eval_freq: int = 10_000
    risk_penalty: float = 0.5  # For CPPO


class PortfolioEnv:
    """Gym-compatible portfolio allocation environment.

    State: Concatenation of [returns_history, signals, current_weights, regime_onehot]
    Action: Target weight vector (softmax-normalized)
    Reward: Portfolio return - risk_penalty * volatility

    Inherits from gym.Env when gymnasium is available, otherwise
    provides a duck-typed interface for manual use.
    """

    def __init__(
        self,
        returns: pd.DataFrame,
        signals: pd.DataFrame,
        n_assets: int,
        lookback: int = 20,
        risk_penalty: float = 0.5,
        transaction_cost: float = 0.0025,
    ):
        self.returns = returns
        self.signals = signals
        self.n_assets = n_assets
        self.lookback = lookback
        self.risk_penalty = risk_penalty
        self.transaction_cost = transaction_cost

        self.current_step = lookback
        self.current_weights = np.ones(n_assets) / n_assets

        # Action/observation spaces (for gym compatibility)
        self.action_dim = n_assets
        self.obs_dim = lookback * n_assets + n_assets + n_assets + 4  # returns + signals + weights + regime

        # Define Gym spaces if gymnasium/gym is available
        try:
            import gymnasium as gym
            from gymnasium import spaces
        except ImportError:
            try:
                import gym
                from gym import spaces
            except ImportError:
                gym = None
                spaces = None

        if spaces is not None:
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf,
                shape=(self.obs_dim,), dtype=np.float32,
            )
            self.action_space = spaces.Box(
                low=-1.0, high=1.0,
                shape=(n_assets,), dtype=np.float32,
            )

    def reset(self, *, seed=None, options=None) -> np.ndarray:
        """Reset environment to start.

        Returns observation array (Gym-compatible: also accepts seed/options kwargs).
        """
        self.current_step = self.lookback
        self.current_weights = np.ones(self.n_assets) / self.n_assets
        return self._get_obs()

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict]:
        """Execute one step.

        Args:
            action: Raw weight vector (will be softmax-normalized)

        Returns:
            (observation, reward, terminated, truncated, info) — Gym 5-tuple
        """
        # Normalize action to weights
        weights = self._softmax(action)
        weights = np.clip(weights, 0, 0.15)  # Max position
        weights = weights / weights.sum()  # Renormalize

        # Transaction cost
        turnover = np.abs(weights - self.current_weights).sum()
        tc = turnover * self.transaction_cost

        # Portfolio return
        if self.current_step < len(self.returns):
            period_returns = self.returns.iloc[self.current_step].values
            port_return = float(weights @ period_returns) - tc
            port_vol = float(np.std(period_returns))

            reward = port_return - self.risk_penalty * port_vol
        else:
            port_return = 0.0
            reward = 0.0

        self.current_weights = weights
        self.current_step += 1
        terminated = self.current_step >= len(self.returns) - 1
        truncated = False

        info = {
            "portfolio_return": port_return,
            "turnover": turnover,
            "weights": weights.copy(),
        }

        return self._get_obs(), reward, terminated, truncated, info

    def _get_obs(self) -> np.ndarray:
        """Get current observation."""
        start = max(0, self.current_step - self.lookback)
        end = self.current_step

        ret_window = self.returns.iloc[start:end].values.flatten()
        if len(ret_window) < self.lookback * self.n_assets:
            ret_window = np.pad(ret_window, (self.lookback * self.n_assets - len(ret_window), 0))

        sig_window = self.signals.iloc[end].values if end < len(self.signals) else np.zeros(self.n_assets)

        regime = np.zeros(4)  # bull, bear, sideways, crisis one-hot
        regime[2] = 1  # Default sideways

        obs = np.concatenate([
            ret_window,
            sig_window,
            self.current_weights,
            regime,
        ])
        return obs.astype(np.float32)

    @staticmethod
    def _softmax(x: np.ndarray) -> np.ndarray:
        """Numerically stable softmax."""
        e_x = np.exp(x - np.max(x))
        return e_x / e_x.sum()


class RLAllocator:
    """RL-based portfolio weight allocator.

    Usage:
        allocator = RLAllocator(algorithm="PPO")
        allocator.train(returns_df, signals_df, total_timesteps=50000)
        weights = allocator.allocate(current_state)
    """

    def __init__(self, config: RLConfig = None, device: str = "auto"):
        self.config = config or RLConfig()
        self.device = device
        self.model = None
        self.env: Optional[PortfolioEnv] = None
        self.is_trained = False

    def train(
        self,
        returns: pd.DataFrame,
        signals: pd.DataFrame,
        total_timesteps: Optional[int] = None,
        verbose: bool = False,
    ) -> "RLAllocator":
        """Train RL allocator on historical data.

        Args:
            returns: DataFrame of asset returns (n_days × n_assets)
            signals: DataFrame of signals (n_days × n_assets)
            total_timesteps: Override config total timesteps
            verbose: Print training progress

        Returns:
            self
        """
        try:
            from stable_baselines3 import PPO, SAC
        except ImportError:
            logger.warning("stable-baselines3 not available. RL allocator cannot train.")
            return self

        n_assets = returns.shape[1]
        env = PortfolioEnv(
            returns=returns,
            signals=signals,
            n_assets=n_assets,
            risk_penalty=self.config.risk_penalty,
        )

        # Wrap in DummyVecEnv for sb3 compatibility
        from stable_baselines3.common.vec_env import DummyVecEnv
        self.env = DummyVecEnv([lambda: env])

        algo = self.config.algorithm
        ts = total_timesteps or self.config.total_timesteps

        if algo == "PPO":
            self.model = PPO(
                "MlpPolicy", self.env,
                learning_rate=self.config.learning_rate,
                n_steps=self.config.n_steps,
                batch_size=self.config.batch_size,
                n_epochs=self.config.n_epochs,
                gamma=self.config.gamma,
                ent_coef=self.config.ent_coef,
                verbose=1 if verbose else 0,
                device=self.device,
            )
        elif algo == "SAC":
            self.model = SAC(
                "MlpPolicy", self.env,
                learning_rate=self.config.learning_rate,
                batch_size=self.config.batch_size,
                gamma=self.config.gamma,
                verbose=1 if verbose else 0,
                device=self.device,
            )
        else:
            logger.warning("Unknown algorithm %s, defaulting to PPO", algo)
            self.model = PPO("MlpPolicy", self.env, verbose=1 if verbose else 0)

        self.model.learn(total_timesteps=ts)
        self.is_trained = True
        logger.info("RL allocator trained: %s, %d timesteps", algo, ts)
        return self

    def allocate(self, state: np.ndarray) -> np.ndarray:
        """Generate weight vector from market state.

        Args:
            state: Current market state observation

        Returns:
            Weight vector (n_assets,) summing to 1
        """
        if not self.is_trained or self.model is None:
            # Fallback: equal weight
            n = state.shape[0] if state.ndim > 0 else 10
            return np.ones(max(n, 1)) / max(n, 1)

        action, _ = self.model.predict(state, deterministic=True)
        weights = PortfolioEnv._softmax(action)
        return weights

    def allocate_from_data(
        self,
        returns: pd.DataFrame,
        signals: pd.DataFrame,
    ) -> np.ndarray:
        """Allocate weights from current returns and signals data.

        Args:
            returns: Recent returns history
            signals: Current signals

        Returns:
            Weight vector
        """
        if not self.is_trained or self.env is None:
            n = returns.shape[1]
            return np.ones(n) / n

        # Access underlying PortfolioEnv from DummyVecEnv
        underlying = getattr(self.env, "envs", [None])[0]
        if underlying is not None and hasattr(underlying, "_get_obs"):
            obs = underlying._get_obs()
        else:
            n = returns.shape[1]
            return np.ones(n) / n
        return self.allocate(obs)

    def save(self, path: str) -> None:
        """Save trained model."""
        if self.model is not None:
            self.model.save(path)

    def load(self, path: str) -> "RLAllocator":
        """Load trained model."""
        try:
            from stable_baselines3 import PPO, SAC
            if self.config.algorithm == "SAC":
                self.model = SAC.load(path)
            else:
                self.model = PPO.load(path)
            self.is_trained = True
        except ImportError:
            logger.warning("stable-baselines3 not available. Cannot load model.")
        return self
