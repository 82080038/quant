"""Tests for multi-asset routing and asset_classes normalization.

Tests cover:
  - AssetRouter ticker inference (crypto, forex, commodity, equity, index)
  - AssetRouter should_fetch logic per asset class
  - AssetRouter holiday/weekend skipping
  - AssetRouter delisted instrument filtering
  - AssetClassConfig defaults
  - FetchRegistry integration with AssetRouter (mock)
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from quant.data.asset_router import (
    ASSET_CLASS_DEFAULTS,
    AssetClassConfig,
    AssetRouter,
    FetchAction,
    FetchDecision,
)


class TestAssetRouterInference:
    """Test static ticker → asset_class inference."""

    @pytest.mark.parametrize(
        "ticker,expected",
        [
            ("BTCUSDT", "crypto"),
            ("ETHUSDT", "crypto"),
            ("BTC-USD", "crypto"),
            ("SOL-USD", "crypto"),
            ("EURUSD=X", "forex"),
            ("USDIDR=X", "forex"),
            ("EURUSD", "forex"),
            ("USDJPY", "forex"),
            ("GBPUSD", "forex"),
            ("^GSPC", "index"),
            ("^JKSE", "index"),
            ("^N225", "index"),
            ("GC=F", "commodity"),
            ("CL=F", "commodity"),
            ("BZ=F", "commodity"),
            ("DGS10", "macro_rate"),
            ("FEDFUNDS", "macro_rate"),
            ("T10YIE", "macro_rate"),
            ("AAPL", "equity"),
            ("BBCA.JK", "equity"),
            ("TLKM.JK", "equity"),
        ],
    )
    def test_infer_asset_class(self, ticker: str, expected: str):
        result = AssetRouter._infer_asset_class(ticker)
        assert result == expected, f"{ticker} should be {expected}, got {result}"


class TestAssetRouterShouldFetch:
    """Test should_fetch routing logic without DB."""

    @pytest.fixture
    def router(self) -> AssetRouter:
        return AssetRouter(session=None)

    def test_crypto_always_fetch(self, router: AssetRouter):
        # Saturday
        d = date(2026, 8, 22)  # Saturday
        decision = router.should_fetch("BTCUSDT", d)
        assert decision.action == FetchAction.FETCH
        assert "24/7" in decision.reason or "Crypto" in decision.reason

    def test_forex_skip_weekend(self, router: AssetRouter):
        d = date(2026, 8, 22)  # Saturday
        decision = router.should_fetch("EURUSD=X", d)
        assert decision.action == FetchAction.SKIP
        assert "weekend" in decision.reason.lower()

    def test_forex_fetch_weekday(self, router: AssetRouter):
        d = date(2026, 8, 19)  # Wednesday
        decision = router.should_fetch("EURUSD=X", d)
        assert decision.action == FetchAction.FETCH

    def test_equity_skip_weekend(self, router: AssetRouter):
        d = date(2026, 8, 23)  # Sunday
        decision = router.should_fetch("AAPL", d)
        assert decision.action == FetchAction.SKIP
        assert "weekend" in decision.reason.lower()

    def test_equity_fetch_weekday_no_db(self, router: AssetRouter):
        d = date(2026, 8, 19)  # Wednesday
        decision = router.should_fetch("AAPL", d)
        assert decision.action == FetchAction.FETCH

    def test_macro_rate_weekly_monday(self, router: AssetRouter):
        d = date(2026, 8, 24)  # Monday
        decision = router.should_fetch("DGS10", d)
        assert decision.action == FetchAction.FETCH

    def test_macro_rate_skip_non_monday(self, router: AssetRouter):
        d = date(2026, 8, 19)  # Wednesday
        decision = router.should_fetch("DGS10", d)
        assert decision.action == FetchAction.SKIP

    def test_commodity_skip_weekend(self, router: AssetRouter):
        d = date(2026, 8, 23)  # Sunday
        decision = router.should_fetch("GC=F", d)
        assert decision.action == FetchAction.SKIP

    def test_commodity_fetch_weekday(self, router: AssetRouter):
        d = date(2026, 8, 19)  # Wednesday
        decision = router.should_fetch("GC=F", d)
        assert decision.action == FetchAction.FETCH


class TestAssetRouterConfig:
    """Test AssetClassConfig defaults."""

    def test_defaults_loaded(self):
        assert "equity" in ASSET_CLASS_DEFAULTS
        assert "forex" in ASSET_CLASS_DEFAULTS
        assert "crypto" in ASSET_CLASS_DEFAULTS
        assert "commodity" in ASSET_CLASS_DEFAULTS
        assert "index" in ASSET_CLASS_DEFAULTS
        assert "bond" in ASSET_CLASS_DEFAULTS
        assert "macro_rate" in ASSET_CLASS_DEFAULTS

    def test_crypto_config_24h(self):
        cfg = ASSET_CLASS_DEFAULTS["crypto"]
        assert cfg.market_hours_24h is True
        assert cfg.holiday_calendar_source == "none"
        assert cfg.is_tradeable is True

    def test_equity_config_not_24h(self):
        cfg = ASSET_CLASS_DEFAULTS["equity"]
        assert cfg.market_hours_24h is False
        assert cfg.holiday_calendar_source == "exchange"

    def test_forex_config_24h(self):
        cfg = ASSET_CLASS_DEFAULTS["forex"]
        assert cfg.market_hours_24h is True
        assert cfg.holiday_calendar_source == "central_bank"

    def test_index_not_tradeable(self):
        cfg = ASSET_CLASS_DEFAULTS["index"]
        assert cfg.is_tradeable is False

    def test_macro_rate_not_tradeable(self):
        cfg = ASSET_CLASS_DEFAULTS["macro_rate"]
        assert cfg.is_tradeable is False

    def test_get_config_unknown_returns_equity(self):
        router = AssetRouter(session=None)
        cfg = router.get_config("unknown_class")
        assert cfg.code == "equity"

    def test_get_tradeable_asset_classes(self):
        router = AssetRouter(session=None)
        tradeable = router.get_tradeable_asset_classes()
        assert "equity" in tradeable
        assert "forex" in tradeable
        assert "crypto" in tradeable
        assert "commodity" in tradeable
        assert "index" not in tradeable
        assert "macro_rate" not in tradeable


class TestAssetRouterShouldRunPipeline:
    """Test should_run_pipeline logic."""

    @pytest.fixture
    def router(self) -> AssetRouter:
        return AssetRouter(session=None)

    def test_index_not_tradeable(self, router: AssetRouter):
        d = date(2026, 8, 19)  # Wednesday
        decision = router.should_run_pipeline("^GSPC", d)
        assert decision.action == FetchAction.SKIP
        assert "not tradeable" in decision.reason

    def test_macro_rate_not_tradeable(self, router: AssetRouter):
        d = date(2026, 8, 24)  # Monday
        decision = router.should_run_pipeline("DGS10", d)
        assert decision.action == FetchAction.SKIP
        assert "not tradeable" in decision.reason

    def test_equity_tradeable(self, router: AssetRouter):
        d = date(2026, 8, 19)  # Wednesday
        decision = router.should_run_pipeline("AAPL", d)
        assert decision.action == FetchAction.FETCH

    def test_crypto_tradeable_weekend(self, router: AssetRouter):
        d = date(2026, 8, 23)  # Sunday
        decision = router.should_run_pipeline("BTCUSDT", d)
        assert decision.action == FetchAction.FETCH


class TestAssetRouterWithMockDB:
    """Test AssetRouter with mocked DB session."""

    def test_get_asset_class_from_db(self):
        session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = ("forex",)
        session.execute.return_value = mock_result

        router = AssetRouter(session=session)
        result = router.get_asset_class_for_ticker("EURUSD=X", session)
        assert result == "forex"

    def test_get_asset_class_db_fallback_to_inference(self):
        session = MagicMock()
        session.execute.side_effect = Exception("Table not found")

        router = AssetRouter(session=session)
        result = router.get_asset_class_for_ticker("BTCUSDT", session)
        assert result == "crypto"

    def test_exchange_holiday_skip(self):
        session = MagicMock()
        # get_asset_class_for_ticker: SELECT asset_class FROM instruments → equity
        # _check_exchange_holiday: SELECT EXISTS(...) → True
        mock_class_result = MagicMock()
        mock_class_result.fetchone.return_value = ("equity",)
        mock_holiday_result = MagicMock()
        mock_holiday_result.scalar.return_value = True
        session.execute.side_effect = [mock_class_result, mock_holiday_result]

        router = AssetRouter(session=session)
        router._loaded = True  # skip _load_configs DB call
        d = date(2026, 8, 20)  # Thursday
        decision = router.should_fetch("AAPL", d, session)
        assert decision.action == FetchAction.SKIP
        assert "holiday" in decision.reason.lower()

    def test_delisted_skip(self):
        session = MagicMock()
        # get_asset_class_for_ticker → equity
        # _check_exchange_holiday → False (not holiday)
        # _check_delisted → True
        mock_class_result = MagicMock()
        mock_class_result.fetchone.return_value = ("equity",)
        mock_holiday_result = MagicMock()
        mock_holiday_result.scalar.return_value = False
        mock_delisted_result = MagicMock()
        mock_delisted_result.fetchone.return_value = (True,)
        session.execute.side_effect = [
            mock_class_result, mock_holiday_result, mock_delisted_result
        ]

        router = AssetRouter(session=session)
        router._loaded = True  # skip _load_configs DB call
        d = date(2026, 8, 20)  # Thursday
        decision = router.should_fetch("OLDSTOCK", d, session)
        assert decision.action == FetchAction.SKIP
        assert "delisted" in decision.reason.lower()
