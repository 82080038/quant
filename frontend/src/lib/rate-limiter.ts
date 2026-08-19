/**
 * Adaptive Rate Limiters for Frontend — UI throttling & data-fetch backoff.
 *
 * Combines:
 *   1. Token Bucket — controls burst capacity for UI updates
 *   2. Exponential Backoff with Jitter — reacts to HTTP 429 / network errors
 *   3. AIMD — adapts polling interval based on response latency
 *
 * Cross-platform: works in any browser (Chrome, Firefox, Edge, Safari).
 */

// ── Types ──────────────────────────────────────────────────────────────

interface LimiterStats {
  name: string;
  currentRate: number;
  consecutiveErrors: number;
  totalRequests: number;
  totalErrors: number;
  total429: number;
  avgLatencyMs: number;
  lastBackoff: number;
}

// ── Constants ──────────────────────────────────────────────────────────

const MIN_RATE = 0.1;
const MAX_RATE = 10;
const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;
const BACKOFF_FACTOR = 2;
const JITTER_RATIO = 0.25;
const LATENCY_WARN_MS = 3000;
const LATENCY_GOOD_MS = 500;
const AIMD_ADD = 0.1;
const AIMD_MULT = 0.5;

// ── Adaptive Rate Limiter (Token Bucket + Backoff + AIMD) ──────────────

export class AdaptiveRateLimiter {
  private rate: number;
  private tokens: number;
  private burst: number;
  private lastRefill: number;
  private backoff: number = 0;
  private consecutiveErrors: number = 0;
  private emaLatencyMs: number = 0;
  private alpha = 0.3;
  private totalRequests = 0;
  private totalErrors = 0;
  private total429 = 0;

  constructor(
    public name: string = "default",
    baseRate: number = 1,
    burst: number = 5,
  ) {
    this.rate = Math.max(MIN_RATE, Math.min(baseRate, MAX_RATE));
    this.burst = burst;
    this.tokens = burst;
    this.lastRefill = Date.now();
  }

  /** Wait until a token is available (token bucket throttle). */
  async acquire(): Promise<void> {
    this._refill();
    while (this.tokens < 1) {
      const deficit = 1 - this.tokens;
      const waitMs = (deficit / this.rate) * 1000;
      await this._sleep(waitMs);
      this._refill();
    }
    this.tokens -= 1;

    if (this.backoff > 0) {
      await this._sleep(this.backoff);
    }
  }

  /** Report a successful response for adaptive adjustment. */
  reportSuccess(latencyMs: number): void {
    this.totalRequests++;
    this._updateLatency(latencyMs);
    this._resetBackoff();

    if (latencyMs > LATENCY_WARN_MS) {
      this._decreaseRate(0.75);
    } else if (latencyMs < LATENCY_GOOD_MS) {
      this._increaseRate();
    }
  }

  /** Report an error (HTTP 429, 5xx, timeout, network error). */
  reportError(status?: number): void {
    this.totalErrors++;
    if (status === 429) {
      this.total429++;
      this._applyBackoff();
      this._decreaseRate(0.5);
    } else if (status && status >= 500) {
      this._applyBackoff();
      this._decreaseRate(0.75);
    } else {
      this._applyBackoff();
      this._decreaseRate(0.5);
    }
  }

  /** Fetch with adaptive rate limiting and retry. */
  async fetch(
    input: string | URL,
    init?: RequestInit,
    retries = 3,
  ): Promise<Response> {
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= retries; attempt++) {
      await this.acquire();

      const start = Date.now();
      try {
        const resp = await globalThis.fetch(input, init);
        const latency = Date.now() - start;
        this.reportSuccess(latency);

        if (resp.status === 429) {
          this.reportError(429);
          lastError = new Error(`HTTP 429: ${input}`);
          continue;
        }
        if (resp.status >= 500) {
          this.reportError(resp.status);
          lastError = new Error(`HTTP ${resp.status}: ${input}`);
          continue;
        }
        return resp;
      } catch (err) {
        const latency = Date.now() - start;
        this.reportSuccess(latency);
        this.reportError();
        lastError = err as Error;
      }
    }

    throw lastError ?? new Error(`Max retries (${retries}) exhausted`);
  }

  /** Get current limiter stats. */
  stats(): LimiterStats {
    return {
      name: this.name,
      currentRate: this.rate,
      consecutiveErrors: this.consecutiveErrors,
      totalRequests: this.totalRequests,
      totalErrors: this.totalErrors,
      total429: this.total429,
      avgLatencyMs: Math.round(this.emaLatencyMs),
      lastBackoff: Math.round(this.backoff),
    };
  }

  // ── Private Methods ──────────────────────────────────────────────────

  private _refill(): void {
    const now = Date.now();
    const elapsedSec = (now - this.lastRefill) / 1000;
    this.lastRefill = now;
    this.tokens = Math.min(this.burst, this.tokens + elapsedSec * this.rate);
  }

  private _increaseRate(): void {
    this.rate = Math.min(MAX_RATE, this.rate + AIMD_ADD);
  }

  private _decreaseRate(factor: number = AIMD_MULT): void {
    this.rate = Math.max(MIN_RATE, this.rate * factor);
  }

  private _applyBackoff(): void {
    this.consecutiveErrors++;
    const base = Math.min(
      INITIAL_BACKOFF_MS * BACKOFF_FACTOR ** (this.consecutiveErrors - 1),
      MAX_BACKOFF_MS,
    );
    const jitter = base * JITTER_RATIO * (Math.random() * 2 - 1);
    this.backoff = Math.max(0, base + jitter);
  }

  private _resetBackoff(): void {
    if (this.consecutiveErrors > 0) {
      this.consecutiveErrors = 0;
      this.backoff = 0;
    }
  }

  private _updateLatency(latencyMs: number): void {
    if (this.emaLatencyMs === 0) {
      this.emaLatencyMs = latencyMs;
    } else {
      this.emaLatencyMs =
        this.alpha * latencyMs + (1 - this.alpha) * this.emaLatencyMs;
    }
  }

  private _sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

// ── Throttle — limit function call frequency (UI rendering) ────────────

export function throttle<T extends (...args: any[]) => any>(
  fn: T,
  intervalMs: number,
): (...args: Parameters<T>) => void {
  let lastCall = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let lastArgs: Parameters<T> | null = null;

  return (...args: Parameters<T>) => {
    const now = Date.now();
    const remaining = intervalMs - (now - lastCall);

    if (remaining <= 0) {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      lastCall = now;
      fn(...args);
    } else {
      lastArgs = args;
      if (!timer) {
        timer = setTimeout(() => {
          lastCall = Date.now();
          timer = null;
          if (lastArgs) {
            fn(...lastArgs);
            lastArgs = null;
          }
        }, remaining);
      }
    }
  };
}

// ── Debounce — delay function call until burst settles (UI rendering) ──

export function debounce<T extends (...args: any[]) => any>(
  fn: T,
  delayMs: number,
): (...args: Parameters<T>) => void {
  let timer: ReturnType<typeof setTimeout> | null = null;

  return (...args: Parameters<T>) => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      fn(...args);
    }, delayMs);
  };
}

// ── Adaptive Poller — auto-adjusting interval based on response ────────

export class AdaptivePoller {
  private intervalMs: number;
  private minIntervalMs: number;
  private maxIntervalMs: number;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private consecutiveErrors = 0;

  constructor(
    private callback: () => Promise<void>,
    initialIntervalMs: number = 5000,
    minIntervalMs: number = 1000,
    maxIntervalMs: number = 60000,
  ) {
    this.intervalMs = initialIntervalMs;
    this.minIntervalMs = minIntervalMs;
    this.maxIntervalMs = maxIntervalMs;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this._tick();
  }

  stop(): void {
    this.running = false;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  /** Report success — decrease interval (poll faster). */
  reportSuccess(): void {
    this.consecutiveErrors = 0;
    this.intervalMs = Math.max(
      this.minIntervalMs,
      this.intervalMs * 0.9,
    );
  }

  /** Report error — increase interval (poll slower) with backoff. */
  reportError(): void {
    this.consecutiveErrors++;
    const backoff = Math.min(
      this.intervalMs * 2 ** this.consecutiveErrors,
      this.maxIntervalMs,
    );
    this.intervalMs = backoff;
  }

  get currentIntervalMs(): number {
    return Math.round(this.intervalMs);
  }

  private async _tick(): Promise<void> {
    if (!this.running) return;

    try {
      await this.callback();
      this.reportSuccess();
    } catch {
      this.reportError();
    }

    if (this.running) {
      this.timer = setTimeout(() => this._tick(), this.intervalMs);
    }
  }
}

// ── Pre-built Limiter Registry (singleton per name) ────────────────────

const _limiters = new Map<string, AdaptiveRateLimiter>();

export function getLimiter(
  name: string,
  baseRate?: number,
  burst?: number,
): AdaptiveRateLimiter {
  if (!_limiters.has(name)) {
    const defaults: Record<string, { baseRate: number; burst: number }> = {
      api: { baseRate: 5, burst: 10 },
      data: { baseRate: 2, burst: 5 },
      scheduler: { baseRate: 1, burst: 3 },
    };
    const config = defaults[name] ?? { baseRate: 1, burst: 5 };
    _limiters.set(
      name,
      new AdaptiveRateLimiter(
        name,
        baseRate ?? config.baseRate,
        burst ?? config.burst,
      ),
    );
  }
  return _limiters.get(name)!;
}
