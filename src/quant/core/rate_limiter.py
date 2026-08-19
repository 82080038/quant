"""Adaptive Rate Limiter — dynamic throttle for outbound HTTP requests.

Combines three algorithms:
  1. Token Bucket — controls burst capacity and sustained rate
  2. Exponential Backoff with Jitter — reacts to HTTP 429 / 5xx
  3. AIMD (Additive Increase / Multiplicative Decrease) — adapts to latency

The limiter is fully async (asyncio) and cross-platform (Linux + Windows).

Usage (async):
    from quant.core.rate_limiter import AdaptiveRateLimiter

    limiter = AdaptiveRateLimiter(name="idx", base_rate=0.5, burst=3)

    async with limiter:
        resp = await limiter.fetch(session, "GET", url, params=...)

Usage (sync wrapper for existing sync code):
    from quant.core.rate_limiter import SyncRateLimiter

    limiter = SyncRateLimiter(name="idx", base_rate=0.5, burst=3)
    with limiter:
        resp = limiter.request("GET", url, params=...)

The limiter auto-adjusts:
  - On HTTP 429: exponential backoff + reduce rate by 50%
  - On HTTP 5xx: backoff + reduce rate by 25%
  - On timeout/connection error: backoff + reduce rate by 50%
  - On success with low latency: increase rate (AIMD additive)
  - On success with high latency: reduce rate slightly
  - Internal queue depth > threshold: temporarily reduce rate
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Algorithm Parameters ────────────────────────────────────────────────

_MIN_RATE: float = 0.05          # minimum 1 request per 20 seconds
_MAX_RATE: float = 10.0          # maximum 10 requests per second
_INITIAL_BACKOFF: float = 1.0    # initial backoff in seconds
_MAX_BACKOFF: float = 60.0       # maximum backoff
_BACKOFF_FACTOR: float = 2.0     # exponential backoff multiplier
_JITTER_RATIO: float = 0.25      # ±25% jitter on backoff
_LATENCY_WARN_MS: float = 3000.0 # latency threshold to trigger rate decrease
_LATENCY_GOOD_MS: float = 500.0  # latency threshold for rate increase
_QUEUE_DEPTH_THRESHOLD: int = 50 # internal queue depth to trigger throttle
_AIMD_ADD: float = 0.05          # additive increase per success
_AIMD_MULT: float = 0.5          # multiplicative decrease on failure


# ── Data Structures ─────────────────────────────────────────────────────

@dataclass
class LimiterStats:
    """Snapshot of rate-limiter state for monitoring."""
    name: str
    current_rate: float
    current_burst: float
    tokens: float
    consecutive_errors: int
    total_requests: int
    total_errors: int
    total_429: int
    total_timeouts: int
    avg_latency_ms: float
    last_backoff: float
    queue_depth: int


# ── Core Async Rate Limiter ─────────────────────────────────────────────

class AdaptiveRateLimiter:
    """Async adaptive rate limiter using Token Bucket + Exponential Backoff + AIMD.

    Args:
        name: Identifier for logging (e.g. "idx", "yfinance", "telegram").
        base_rate: Initial requests per second.
        burst: Maximum burst capacity (token bucket size).
        timeout: Default request timeout in seconds.
        max_retries: Maximum retry attempts on retryable errors.
    """

    def __init__(
        self,
        name: str = "default",
        base_rate: float = 1.0,
        burst: int = 5,
        timeout: float = 15.0,
        max_retries: int = 3,
    ) -> None:
        self.name = name
        self._rate = max(_MIN_RATE, min(base_rate, _MAX_RATE))
        self._burst = float(burst)
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._timeout = timeout
        self._max_retries = max_retries

        # Backoff state
        self._backoff: float = 0.0
        self._consecutive_errors: int = 0

        # Latency tracking (exponential moving average)
        self._ema_latency_ms: float = 0.0
        self._alpha: float = 0.3  # EMA smoothing factor

        # Counters
        self._total_requests: int = 0
        self._total_errors: int = 0
        self._total_429: int = 0
        self._total_timeouts: int = 0

        # Internal queue depth (set by caller)
        self._queue_depth: int = 0

    # ── Token Bucket ────────────────────────────────────────────────────

    async def _refill(self) -> None:
        """Refill tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)

    async def _acquire(self) -> None:
        """Wait until a token is available (token bucket throttle)."""
        async with self._lock:
            await self._refill()
            while self._tokens < 1.0:
                deficit = 1.0 - self._tokens
                wait = deficit / self._rate
                await asyncio.sleep(wait)
                await self._refill()
            self._tokens -= 1.0

    # ── Adaptive Rate Adjustment ────────────────────────────────────────

    def _increase_rate(self) -> None:
        """AIMD: additive increase on success."""
        old = self._rate
        self._rate = min(_MAX_RATE, self._rate + _AIMD_ADD)
        if self._rate != old:
            logger.debug("[%s] rate ↑ %.2f → %.2f", self.name, old, self._rate)

    def _decrease_rate(self, factor: float = _AIMD_MULT) -> None:
        """AIMD: multiplicative decrease on failure."""
        old = self._rate
        self._rate = max(_MIN_RATE, self._rate * factor)
        logger.debug("[%s] rate ↓ %.2f → %.2f", self.name, old, self._rate)

    def _apply_backoff(self) -> float:
        """Calculate exponential backoff with jitter."""
        self._consecutive_errors += 1
        base = min(
            _INITIAL_BACKOFF * (_BACKOFF_FACTOR ** (self._consecutive_errors - 1)),
            _MAX_BACKOFF,
        )
        jitter = base * _JITTER_RATIO * (random.random() * 2 - 1)
        self._backoff = max(0.0, min(base + jitter, _MAX_BACKOFF))
        return self._backoff

    def _reset_backoff(self) -> None:
        """Reset backoff on success."""
        if self._consecutive_errors > 0:
            self._consecutive_errors = 0
            self._backoff = 0.0

    def _update_latency(self, latency_ms: float) -> None:
        """Update EMA latency and adjust rate based on latency."""
        if self._ema_latency_ms == 0.0:
            self._ema_latency_ms = latency_ms
        else:
            self._ema_latency_ms = (
                self._alpha * latency_ms + (1 - self._alpha) * self._ema_latency_ms
            )

        if latency_ms > _LATENCY_WARN_MS:
            self._decrease_rate(0.75)
        elif latency_ms < _LATENCY_GOOD_MS:
            self._increase_rate()

    # ── Queue Depth Awareness ───────────────────────────────────────────

    def set_queue_depth(self, depth: int) -> None:
        """Set internal queue depth. High depth → temporary rate reduction."""
        self._queue_depth = depth
        if depth > _QUEUE_DEPTH_THRESHOLD:
            self._decrease_rate(0.8)
            logger.warning(
                "[%s] queue depth %d > threshold %d — throttling",
                self.name, depth, _QUEUE_DEPTH_THRESHOLD,
            )

    # ── Core Fetch with Retry ───────────────────────────────────────────

    async def fetch(
        self,
        session: Any,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        json: Any | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Perform an HTTP request with adaptive rate limiting and retry.

        Args:
            session: aiohttp.ClientSession or httpx.AsyncClient.
            method: HTTP method ("GET", "POST", etc.).
            url: Target URL.
            params: Query parameters.
            headers: Request headers.
            json: JSON body.
            timeout: Override default timeout.
            **kwargs: Passed to session.request.

        Returns:
            Response object from the session.

        Raises:
            Exception after max_retries exhausted.
        """
        timeout = timeout or self._timeout
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            await self._acquire()

            # Apply backoff if active
            if self._backoff > 0:
                logger.debug(
                    "[%s] backoff %.1fs (attempt %d/%d)",
                    self.name, self._backoff, attempt, self._max_retries,
                )
                await asyncio.sleep(self._backoff)

            start = time.monotonic()
            try:
                resp = await session.request(
                    method, url,
                    params=params, headers=headers, json=json,
                    timeout=timeout, **kwargs,
                )
                latency_ms = (time.monotonic() - start) * 1000
                self._total_requests += 1
                self._update_latency(latency_ms)

                status = getattr(resp, "status", getattr(resp, "status_code", 0))

                # Handle 429 Too Many Requests
                if status == 429:
                    self._total_429 += 1
                    self._total_errors += 1
                    backoff = self._apply_backoff()
                    retry_after = self._parse_retry_after(resp)
                    if retry_after:
                        self._backoff = max(self._backoff, retry_after)
                    logger.warning(
                        "[%s] HTTP 429 for %s — backoff %.1fs (attempt %d/%d)",
                        self.name, url, self._backoff, attempt, self._max_retries,
                    )
                    self._decrease_rate(0.5)
                    last_exc = _RateLimitError(f"HTTP 429: {url}")
                    continue

                # Handle 5xx server errors
                if 500 <= status < 600:
                    self._total_errors += 1
                    self._apply_backoff()
                    self._decrease_rate(0.75)
                    logger.warning(
                        "[%s] HTTP %d for %s — backoff %.1fs (attempt %d/%d)",
                        self.name, status, url, self._backoff, attempt, self._max_retries,
                    )
                    last_exc = _ServerError(f"HTTP {status}: {url}")
                    continue

                # Success
                self._reset_backoff()
                return resp

            except asyncio.TimeoutError:
                latency_ms = (time.monotonic() - start) * 1000
                self._update_latency(latency_ms)
                self._total_timeouts += 1
                self._total_errors += 1
                self._apply_backoff()
                self._decrease_rate(0.5)
                logger.warning(
                    "[%s] timeout for %s — backoff %.1fs (attempt %d/%d)",
                    self.name, url, self._backoff, attempt, self._max_retries,
                )
                last_exc = asyncio.TimeoutError(f"Request timed out: {url}")

            except (ConnectionError, OSError) as e:
                self._total_errors += 1
                self._apply_backoff()
                self._decrease_rate(0.5)
                logger.warning(
                    "[%s] connection error for %s: %s — backoff %.1fs (attempt %d/%d)",
                    self.name, url, e, self._backoff, attempt, self._max_retries,
                )
                last_exc = e

        # Exhausted retries
        raise last_exc or _RateLimitError(f"Max retries ({self._max_retries}) exhausted for {url}")

    @staticmethod
    def _parse_retry_after(resp: Any) -> float | None:
        """Parse Retry-After header (seconds or HTTP date)."""
        headers = getattr(resp, "headers", {})
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if not retry_after:
            return None
        try:
            return float(retry_after)
        except (ValueError, TypeError):
            return None

    # ── Context Manager ─────────────────────────────────────────────────

    async def __aenter__(self) -> AdaptiveRateLimiter:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    # ── Monitoring ──────────────────────────────────────────────────────

    def stats(self) -> LimiterStats:
        """Get current limiter statistics."""
        return LimiterStats(
            name=self.name,
            current_rate=self._rate,
            current_burst=self._burst,
            tokens=self._tokens,
            consecutive_errors=self._consecutive_errors,
            total_requests=self._total_requests,
            total_errors=self._total_errors,
            total_429=self._total_429,
            total_timeouts=self._total_timeouts,
            avg_latency_ms=self._ema_latency_ms,
            last_backoff=self._backoff,
            queue_depth=self._queue_depth,
        )


# ── Sync Wrapper for Existing Sync Code ─────────────────────────────────

class SyncRateLimiter:
    """Synchronous wrapper around AdaptiveRateLimiter for existing sync code.

    Uses a background event loop to run the async limiter.

    Usage:
        limiter = SyncRateLimiter(name="idx", base_rate=0.5, burst=3)
        resp = limiter.request("GET", url, params=...)
    """

    def __init__(
        self,
        name: str = "default",
        base_rate: float = 1.0,
        burst: int = 5,
        timeout: float = 15.0,
        max_retries: int = 3,
    ) -> None:
        self._async = AdaptiveRateLimiter(
            name=name, base_rate=base_rate, burst=burst,
            timeout=timeout, max_retries=max_retries,
        )
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Get or create a background event loop."""
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        json: Any | None = None,
        timeout: float | None = None,
        session: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        """Synchronous request with adaptive rate limiting.

        Uses requests.Session if no session provided.
        """
        loop = self._get_loop()

        if session is None:
            return loop.run_until_complete(
                self._sync_fetch(method, url, params=params, headers=headers,
                                 json=json, timeout=timeout, **kwargs)
            )
        else:
            return loop.run_until_complete(
                self._async.fetch(session, method, url, params=params,
                                  headers=headers, json=json, timeout=timeout, **kwargs)
            )

    async def _sync_fetch(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> Any:
        """Fetch using requests via asyncio.to_thread."""
        import requests as req_lib

        await self._async._acquire()

        if self._async._backoff > 0:
            await asyncio.sleep(self._async._backoff)

        start = time.monotonic()
        try:
            timeout = kwargs.pop("timeout", self._async._timeout)
            resp = await asyncio.to_thread(
                req_lib.request, method, url, timeout=timeout, **kwargs
            )
            latency_ms = (time.monotonic() - start) * 1000
            self._async._total_requests += 1
            self._async._update_latency(latency_ms)

            status = resp.status_code

            if status == 429:
                self._async._total_429 += 1
                self._async._total_errors += 1
                self._async._apply_backoff()
                self._async._decrease_rate(0.5)
                raise _RateLimitError(f"HTTP 429: {url}")

            if 500 <= status < 600:
                self._async._total_errors += 1
                self._async._apply_backoff()
                self._async._decrease_rate(0.75)
                raise _ServerError(f"HTTP {status}: {url}")

            self._async._reset_backoff()
            return resp

        except (req_lib.exceptions.Timeout, asyncio.TimeoutError):
            self._async._total_timeouts += 1
            self._async._total_errors += 1
            self._async._apply_backoff()
            self._async._decrease_rate(0.5)
            raise
        except (req_lib.exceptions.ConnectionError, OSError):
            self._async._total_errors += 1
            self._async._apply_backoff()
            self._async._decrease_rate(0.5)
            raise

    def set_queue_depth(self, depth: int) -> None:
        self._async.set_queue_depth(depth)

    def stats(self) -> LimiterStats:
        return self._async.stats()

    def acquire_sync(self) -> None:
        """Synchronously acquire a token (blocking wait)."""
        loop = self._get_loop()
        loop.run_until_complete(self._async._acquire())

    def sleep_backoff_sync(self) -> None:
        """Sleep for current backoff duration (blocking)."""
        if self._async._backoff > 0:
            time.sleep(self._async._backoff)


# ── Exceptions ──────────────────────────────────────────────────────────

class _RateLimitError(Exception):
    """Raised when HTTP 429 is received."""


class _ServerError(Exception):
    """Raised when HTTP 5xx is received."""


# ── Pre-built Limiter Registry ──────────────────────────────────────────

_limiters: dict[str, SyncRateLimiter] = {}


def get_limiter(name: str, **kwargs: Any) -> SyncRateLimiter:
    """Get or create a named sync rate limiter (singleton per name).

    Args:
        name: Limiter name (e.g. "idx", "yfinance", "telegram", "llm").
        **kwargs: Passed to SyncRateLimiter constructor if creating new.

    Returns:
        SyncRateLimiter instance.
    """
    if name not in _limiters:
        defaults = {
            "idx": {"base_rate": 0.5, "burst": 3, "timeout": 15},
            "yfinance": {"base_rate": 2.0, "burst": 10, "timeout": 30},
            "telegram": {"base_rate": 1.0, "burst": 5, "timeout": 10},
            "llm": {"base_rate": 0.5, "burst": 2, "timeout": 60},
        }
        params = defaults.get(name, {"base_rate": 1.0, "burst": 5})
        params.update(kwargs)
        _limiters[name] = SyncRateLimiter(name=name, **params)
        logger.info("Rate limiter '%s' created: %s", name, params)
    return _limiters[name]
