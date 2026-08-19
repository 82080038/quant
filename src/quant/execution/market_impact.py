"""Almgren-Chriss market impact model (Gap #40).

Implements the Almgren-Chriss optimal execution model for large orders
that would move the market if executed as a single block trade.

The model minimizes the combination of:
- Market impact cost (temporary + permanent)
- Risk (variance of execution cost)

Key concepts:
- Temporary impact: price moves against you during execution (recovers after)
- Permanent impact: price moves and stays (information leakage)
- Optimal trajectory: balance cost vs risk over execution horizon
- Efficient frontier: set of optimal strategies at different risk levels

Reference: Almgren & Chriss (2000), "Optimal Execution of Portfolio Transactions"

Note: For swing trading with daily OHLCV, this is most relevant for
large portfolio rebalancing or position building/liquidation over days.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class ImpactParams:
    """Almgren-Chriss model parameters.

    All parameters are per-share (or per-unit) values.
    """

    # Temporary impact parameters
    eta: float = 0.1  # Temporary impact coefficient (price impact per share per time)
    # Temporary impact = eta * v(t) where v(t) is rate of execution

    # Permanent impact parameters
    gamma: float = 0.05  # Permanent impact coefficient
    # Permanent impact = gamma * v(t)

    # Risk parameters
    sigma: float = 0.3  # Daily volatility (fraction, e.g. 0.3 = 30%)
    # Risk = sigma^2 * remaining shares

    # Risk aversion
    lam: float = 1e-6  # Risk aversion coefficient (lambda)
    # Higher lambda = more risk averse = faster execution


@dataclass
class ExecutionTrajectory:
    """Optimal execution trajectory from Almgren-Chriss.

    Describes how to split a large order over time.
    """

    time_points: np.ndarray  # t_0, t_1, ..., t_N
    shares_remaining: np.ndarray  # x(t) — shares yet to be executed
    execution_rate: np.ndarray  # v(t) — shares per time unit
    price_trajectory: np.ndarray  # Expected price at each point
    cumulative_cost: np.ndarray  # Expected cumulative cost

    @property
    def total_shares(self) -> float:
        return float(self.shares_remaining[0])

    @property
    def execution_time(self) -> float:
        return float(self.time_points[-1])

    @property
    def expected_total_cost(self) -> float:
        return float(self.cumulative_cost[-1])


@dataclass
class ImpactEstimate:
    """Estimated market impact for an order."""

    total_shares: float
    avg_price: float
    execution_horizon_days: int
    temporary_impact_bps: float  # In basis points
    permanent_impact_bps: float
    total_impact_bps: float
    expected_cost: float  # In currency
    optimal_strategy: str  # "twap", "vwap", "almgren_chriss"
    trajectory: ExecutionTrajectory | None = None


class AlmgrenChrissModel:
    """Almgren-Chriss optimal execution model (Gap #40).

    Computes the optimal execution trajectory for a large order
    that minimizes the combination of market impact cost and risk.

    Reference: Almgren & Chriss (2000), "Optimal Execution of Portfolio Transactions"
    """

    def __init__(self, params: ImpactParams | None = None) -> None:
        self.params = params or ImpactParams()

    def compute_trajectory(
        self,
        total_shares: float,
        horizon: int = 5,  # Number of time periods (days)
        time_step: float = 1.0,  # Time between periods (1 day)
        initial_price: float = 100.0,
    ) -> ExecutionTrajectory:
        """Compute optimal execution trajectory.

        Args:
            total_shares: Total shares to execute.
            horizon: Number of time periods.
            time_step: Time between periods.
            initial_price: Starting price.

        Returns:
            ExecutionTrajectory with optimal schedule.
        """
        N = horizon
        T = N * time_step
        tau = time_step  # Time step

        # Almgren-Chriss optimal trajectory:
        # x(t) = X * sinh(kappa * (T - t)) / sinh(kappa * T)
        # where kappa = sqrt(lam * sigma^2 / eta)

        sigma = self.params.sigma
        eta = self.params.eta
        gamma = self.params.gamma
        lam = self.params.lam

        kappa = np.sqrt(lam * sigma ** 2 / eta) if eta > 0 else 0.0

        # Time points
        t_points = np.linspace(0, T, N + 1)

        if kappa > 0 and kappa * T > 0:
            # Optimal trajectory
            shares_remaining = total_shares * np.sinh(kappa * (T - t_points)) / np.sinh(kappa * T)
        else:
            # Linear (TWAP) when kappa = 0
            shares_remaining = total_shares * (1 - t_points / T)

        # Execution rate: v(t) = -dx/dt
        # For discrete: v_i = (x_{i-1} - x_i) / tau
        execution_rate = np.zeros(N)
        for i in range(N):
            execution_rate[i] = (shares_remaining[i] - shares_remaining[i + 1]) / tau

        # Price trajectory with permanent impact
        # p(t) = p0 + gamma * (X - x(t))
        price_trajectory = initial_price + gamma * (total_shares - shares_remaining)

        # Cumulative cost
        # Cost_i = v_i * (p0 + gamma * (X - x_i) + eta * v_i)
        cumulative_cost = np.zeros(N + 1)
        for i in range(N):
            temp_impact = eta * execution_rate[i]
            perm_impact = gamma * (total_shares - shares_remaining[i])
            cost_i = execution_rate[i] * (initial_price + perm_impact + temp_impact) * tau
            cumulative_cost[i + 1] = cumulative_cost[i] + cost_i

        return ExecutionTrajectory(
            time_points=t_points,
            shares_remaining=shares_remaining,
            execution_rate=execution_rate,
            price_trajectory=price_trajectory,
            cumulative_cost=cumulative_cost,
        )

    def estimate_impact(
        self,
        total_shares: float,
        avg_price: float,
        horizon_days: int = 5,
        adv: float | None = None,  # Average Daily Volume
    ) -> ImpactEstimate:
        """Estimate market impact for an order.

        Args:
            total_shares: Total shares to execute.
            avg_price: Current average price.
            horizon_days: Execution horizon in days.
            adv: Average Daily Volume (for participation rate check).

        Returns:
            ImpactEstimate with impact estimates.
        """
        traj = self.compute_trajectory(
            total_shares=total_shares,
            horizon=horizon_days,
            initial_price=avg_price,
        )

        # Calculate impacts in basis points
        order_value = total_shares * avg_price
        if order_value <= 0:
            return ImpactEstimate(
                total_shares=total_shares,
                avg_price=avg_price,
                execution_horizon_days=horizon_days,
                temporary_impact_bps=0.0,
                permanent_impact_bps=0.0,
                total_impact_bps=0.0,
                expected_cost=0.0,
                optimal_strategy="almgren_chriss",
            )

        # Temporary impact: eta * average execution rate
        avg_rate = np.mean(traj.execution_rate) if len(traj.execution_rate) > 0 else 0
        temp_impact_price = self.params.eta * avg_rate
        temp_impact_bps = (temp_impact_price / avg_price) * 10000

        # Permanent impact: gamma * total_shares
        perm_impact_price = self.params.gamma * total_shares
        perm_impact_bps = (perm_impact_price / avg_price) * 10000

        total_impact_bps = temp_impact_bps + perm_impact_bps
        expected_cost = traj.expected_total_cost

        # Determine optimal strategy label
        participation_rate = (total_shares / adv) if adv and adv > 0 else 0
        if participation_rate > 0.10:  # > 10% of ADV
            strategy = "almgren_chriss"
        elif participation_rate > 0.05:
            strategy = "twap"
        else:
            strategy = "vwap"  # Small orders can use VWAP

        return ImpactEstimate(
            total_shares=total_shares,
            avg_price=avg_price,
            execution_horizon_days=horizon_days,
            temporary_impact_bps=round(temp_impact_bps, 2),
            permanent_impact_bps=round(perm_impact_bps, 2),
            total_impact_bps=round(total_impact_bps, 2),
            expected_cost=round(expected_cost, 2),
            optimal_strategy=strategy,
            trajectory=traj,
        )

    def efficient_frontier(
        self,
        total_shares: float,
        avg_price: float,
        horizon_days: int = 5,
        n_points: int = 10,
    ) -> list[dict[str, Any]]:
        """Compute efficient frontier of execution strategies.

        Varies risk aversion (lambda) to trace out the frontier
        of expected cost vs execution risk.

        Args:
            total_shares: Total shares.
            avg_price: Current price.
            horizon_days: Execution horizon.
            n_points: Number of points on frontier.

        Returns:
            List of dicts with cost, risk, and lambda for each point.
        """
        frontier: list[dict[str, Any]] = []
        lambdas = np.logspace(-8, -2, n_points)

        original_lambda = self.params.lam
        for lam in lambdas:
            self.params.lam = float(lam)
            traj = self.compute_trajectory(
                total_shares=total_shares,
                horizon=horizon_days,
                initial_price=avg_price,
            )

            # Cost = expected total cost
            cost = traj.expected_total_cost

            # Risk = sigma^2 * sum(x_i^2 * tau) — variance of cost
            sigma = self.params.sigma
            tau = 1.0
            risk = sigma ** 2 * np.sum(traj.shares_remaining[:-1] ** 2) * tau

            frontier.append({
                "lambda": float(lam),
                "expected_cost": round(cost, 2),
                "risk": round(float(risk), 2),
                "risk_sqrt": round(float(np.sqrt(risk)), 2),
            })

        self.params.lam = original_lambda  # Restore
        return frontier

    @staticmethod
    def participation_rate(order_shares: float, adv: float) -> float:
        """Calculate participation rate (order size / ADV).

        Args:
            order_shares: Order size in shares.
            adv: Average Daily Volume in shares.

        Returns:
            Participation rate as fraction (0-1).
        """
        if adv <= 0:
            return 0.0
        return order_shares / adv

    @staticmethod
    def kyle_lambda(
        price_change: float,
        order_flow: float,
    ) -> float:
        """Estimate Kyle's lambda (price impact per unit order flow).

        Lambda = |price_change| / |order_flow|

        Args:
            price_change: Observed price change.
            order_flow: Net order flow (shares).

        Returns:
            Kyle's lambda estimate.
        """
        if order_flow == 0:
            return 0.0
        return abs(price_change) / abs(order_flow)
