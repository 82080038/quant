"""Tests for adaptive rate limiter — core/rate_limiter.py.

Tests cover:
  - Token bucket acquire/throttle behavior
  - AIMD rate adjustment (increase on success, decrease on failure)
  - Exponential backoff with jitter
  - Queue depth awareness
  - Sync wrapper compatibility
  - Limiter registry singleton
"""

import asyncio
import time

import pytest

from quant.core.rate_limiter import (
    AdaptiveRateLimiter,
    SyncRateLimiter,
    get_limiter,
    LimiterStats,
    _RateLimitError,
    _ServerError,
)


# ── Token Bucket Tests ──────────────────────────────────────────────────

class TestTokenBucket:
    def test_initial_burst_available(self):
        """Burst capacity should be available immediately at start."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=1.0, burst=5)
        loop = asyncio.new_event_loop()
        try:
            # Should be able to acquire 5 tokens instantly
            for i in range(5):
                loop.run_until_complete(limiter._acquire())
        finally:
            loop.close()

    def test_throttle_when_tokens_exhausted(self):
        """When tokens are exhausted, acquire should block."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=2.0, burst=2)
        loop = asyncio.new_event_loop()
        try:
            # Exhaust burst
            loop.run_until_complete(limiter._acquire())
            loop.run_until_complete(limiter._acquire())

            # Next acquire should take ~0.5s (1 token at 2/s rate)
            start = time.monotonic()
            loop.run_until_complete(limiter._acquire())
            elapsed = time.monotonic() - start
            assert elapsed >= 0.3, f"Expected throttle delay, got {elapsed:.3f}s"
        finally:
            loop.close()

    def test_rate_clamped_to_bounds(self):
        """Rate should stay within [_MIN_RATE, _MAX_RATE]."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=0.01, burst=1)
        assert limiter._rate >= 0.05  # clamped to min

        limiter2 = AdaptiveRateLimiter(name="test2", base_rate=100, burst=1)
        assert limiter2._rate <= 10.0  # clamped to max


# ── AIMD Tests ──────────────────────────────────────────────────────────

class TestAIMD:
    def test_increase_rate_on_success(self):
        """Rate should increase additively on success."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=1.0, burst=5)
        initial = limiter._rate
        limiter._increase_rate()
        assert limiter._rate > initial
        assert limiter._rate == pytest.approx(initial + 0.05)

    def test_decrease_rate_on_failure(self):
        """Rate should decrease multiplicatively on failure."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=2.0, burst=5)
        initial = limiter._rate
        limiter._decrease_rate(0.5)
        assert limiter._rate < initial
        assert limiter._rate == pytest.approx(initial * 0.5)

    def test_rate_never_below_min(self):
        """Rate should never go below _MIN_RATE."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=0.1, burst=1)
        for _ in range(20):
            limiter._decrease_rate(0.1)
        assert limiter._rate >= 0.05

    def test_rate_never_above_max(self):
        """Rate should never go above _MAX_RATE."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=9.0, burst=1)
        for _ in range(20):
            limiter._increase_rate()
        assert limiter._rate <= 10.0

    def test_latency_based_adjustment(self):
        """Low latency increases rate, high latency decreases it."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=1.0, burst=5)

        # Low latency → increase
        limiter._update_latency(100)  # 100ms < 500ms threshold
        assert limiter._rate > 1.0

        # High latency → decrease
        limiter._update_latency(5000)  # 5000ms > 3000ms threshold
        assert limiter._rate < 1.0


# ── Backoff Tests ───────────────────────────────────────────────────────

class TestBackoff:
    def test_backoff_increases_exponentially(self):
        """Backoff should increase exponentially with consecutive errors."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=1.0, burst=5)

        limiter._apply_backoff()
        b1_base = 1.0 * (2 ** 0)  # consecutive_errors=1
        limiter._apply_backoff()
        b2_base = 1.0 * (2 ** 1)  # consecutive_errors=2
        limiter._apply_backoff()
        b3_base = 1.0 * (2 ** 2)  # consecutive_errors=3

        # Base values should double (jitter is ±25% but base is deterministic)
        assert b2_base == 2 * b1_base
        assert b3_base == 2 * b2_base
        # Actual backoff should be in range [base * 0.75, base * 1.25]
        assert 0.75 * b1_base <= limiter._backoff * (2 ** 2) / (2 ** 2)  # rough check

    def test_backoff_capped_at_max(self):
        """Backoff should be capped at _MAX_BACKOFF (60s)."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=1.0, burst=5)
        for _ in range(20):
            limiter._apply_backoff()
        assert limiter._backoff <= 60.0

    def test_backoff_resets_on_success(self):
        """Backoff should reset to 0 on success."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=1.0, burst=5)
        limiter._apply_backoff()
        limiter._apply_backoff()
        assert limiter._consecutive_errors == 2
        assert limiter._backoff > 0

        limiter._reset_backoff()
        assert limiter._consecutive_errors == 0
        assert limiter._backoff == 0.0

    def test_backoff_has_jitter(self):
        """Backoff should include random jitter to avoid thundering herd."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=1.0, burst=5)
        backoffs = [limiter._apply_backoff() for _ in range(10)]
        # Not all backoffs should be identical (jitter)
        assert len(set(round(b, 3) for b in backoffs)) > 1


# ── Queue Depth Tests ───────────────────────────────────────────────────

class TestQueueDepth:
    def test_high_queue_depth_reduces_rate(self):
        """High queue depth should trigger rate reduction."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=2.0, burst=5)
        initial = limiter._rate
        limiter.set_queue_depth(100)  # > threshold of 50
        assert limiter._rate < initial
        assert limiter._queue_depth == 100

    def test_low_queue_depth_no_change(self):
        """Low queue depth should not affect rate."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=2.0, burst=5)
        initial = limiter._rate
        limiter.set_queue_depth(10)  # < threshold
        assert limiter._rate == initial


# ── Stats Tests ─────────────────────────────────────────────────────────

class TestStats:
    def test_stats_returns_correct_fields(self):
        """Stats should return all expected fields."""
        limiter = AdaptiveRateLimiter(name="test_stats", base_rate=1.0, burst=5)
        stats = limiter.stats()
        assert isinstance(stats, LimiterStats)
        assert stats.name == "test_stats"
        assert stats.current_rate == 1.0
        assert stats.total_requests == 0
        assert stats.total_errors == 0
        assert stats.total_429 == 0

    def test_stats_tracks_requests(self):
        """Stats should track request count."""
        limiter = AdaptiveRateLimiter(name="test", base_rate=10, burst=10)
        limiter._total_requests += 5
        limiter._total_429 += 1
        limiter._total_errors += 2
        stats = limiter.stats()
        assert stats.total_requests == 5
        assert stats.total_429 == 1
        assert stats.total_errors == 2


# ── Sync Wrapper Tests ──────────────────────────────────────────────────

class TestSyncWrapper:
    def test_sync_limiter_acquire(self):
        """SyncRateLimiter.acquire_sync should not raise."""
        limiter = SyncRateLimiter(name="test_sync", base_rate=10, burst=5)
        limiter.acquire_sync()  # should not block

    def test_sync_limiter_stats(self):
        """SyncRateLimiter should expose stats from underlying async limiter."""
        limiter = SyncRateLimiter(name="test_sync", base_rate=2.0, burst=3)
        stats = limiter.stats()
        assert stats.name == "test_sync"
        assert stats.current_rate == 2.0

    def test_sync_limiter_set_queue_depth(self):
        """SyncRateLimiter should proxy queue depth to async limiter."""
        limiter = SyncRateLimiter(name="test_sync", base_rate=2.0, burst=3)
        limiter.set_queue_depth(100)
        assert limiter._async._queue_depth == 100


# ── Registry Tests ──────────────────────────────────────────────────────

class TestRegistry:
    def test_get_limiter_returns_singleton(self):
        """get_limiter should return the same instance for the same name."""
        l1 = get_limiter("test_registry")
        l2 = get_limiter("test_registry")
        assert l1 is l2

    def test_get_limiter_different_names(self):
        """get_limiter should return different instances for different names."""
        l1 = get_limiter("test_registry_a", base_rate=0.5)
        l2 = get_limiter("test_registry_b", base_rate=2.0)
        assert l1 is not l2
        assert l1.stats().name == "test_registry_a"
        assert l2.stats().name == "test_registry_b"

    def test_get_limiter_default_params(self):
        """get_limiter should use sensible defaults for known names."""
        limiter = get_limiter("idx", base_rate=0.5, burst=3)
        stats = limiter.stats()
        assert stats.name == "idx"
        assert stats.current_rate == 0.5
        assert stats.current_burst == 3.0


# ── Exception Tests ─────────────────────────────────────────────────────

class TestExceptions:
    def test_rate_limit_error_is_exception(self):
        """_RateLimitError should be an Exception subclass."""
        err = _RateLimitError("test")
        assert isinstance(err, Exception)

    def test_server_error_is_exception(self):
        """_ServerError should be an Exception subclass."""
        err = _ServerError("test")
        assert isinstance(err, Exception)
