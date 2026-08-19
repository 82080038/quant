/**
 * Server-Sent Events client for the BE observability stream
 * (`/api/observability/stream`). Emits typed `log` and `metric` events.
 *
 * Why SSE (not WS) for observability:
 *   - Server→client only (logs/metrics are one-way).
 *   - Native auto-reconnect via the browser `EventSource` API.
 *   - Keeps the WS connection free for high-frequency market ticks.
 *
 * Replays the recent log ring on (re)connect (handled BE-side).
 */

// ── Types ──────────────────────────────────────────────────────────────

export interface ObsLogEntry {
  ts: number;
  level: string;
  src: string;
  msg: string;
}

export interface ObsMetric {
  ts: number;
  db?: { connected: boolean; error?: string };
  rate_limiters?: Record<string, unknown>;
  ws?: { conns: number; channels: Record<string, number>; sent: number; recv: number; throttle_rate: number | null };
  log_ring_size?: number;
  error?: string;
  [k: string]: unknown;
}

export type SseStatus = "idle" | "connecting" | "open" | "closed" | "error";

type LogListener = (entry: ObsLogEntry) => void;
type MetricListener = (metric: ObsMetric) => void;
type StatusListener = (status: SseStatus) => void;

// ── Client ─────────────────────────────────────────────────────────────

class SseClient {
  private url: string;
  private es: EventSource | null = null;
  private status: SseStatus = "idle";
  private closedByUser = false;

  private logListeners: Set<LogListener> = new Set();
  private metricListeners: Set<MetricListener> = new Set();
  private statusListeners: Set<StatusListener> = new Set();

  // Counters for observability self-monitoring.
  logEvents = 0;
  metricEvents = 0;

  constructor(url: string) {
    this.url = url;
  }

  // ── Lifecycle ────────────────────────────────────────────────────────

  connect(): void {
    if (typeof window === "undefined") return;
    if (this.es) return;
    this.closedByUser = false;
    this.status = "connecting";
    this._emitStatus();

    try {
      this.es = new EventSource(this.url, { withCredentials: true });
    } catch {
      this.status = "error";
      this._emitStatus();
      return;
    }

    this.es.onopen = () => {
      this.status = "open";
      this._emitStatus();
    };

    this.es.addEventListener("log", (ev) => {
      this.logEvents++;
      try {
        const entry = JSON.parse((ev as MessageEvent).data) as ObsLogEntry;
        for (const l of this.logListeners) {
          try {
            l(entry);
          } catch {
            /* ignore */
          }
        }
      } catch {
        /* ignore malformed */
      }
    });

    this.es.addEventListener("metric", (ev) => {
      this.metricEvents++;
      try {
        const metric = JSON.parse((ev as MessageEvent).data) as ObsMetric;
        for (const l of this.metricListeners) {
          try {
            l(metric);
          } catch {
            /* ignore */
          }
        }
      } catch {
        /* ignore malformed */
      }
    });

    this.es.onerror = () => {
      // EventSource auto-reconnects; surface a transient error status.
      if (this.status !== "closed") {
        this.status = "error";
        this._emitStatus();
      }
    };
  }

  disconnect(): void {
    this.closedByUser = true;
    if (this.es) {
      try {
        this.es.close();
      } catch {
        /* ignore */
      }
      this.es = null;
    }
    this.status = "closed";
    this._emitStatus();
  }

  // ── Subscribe API ────────────────────────────────────────────────────

  onLog(listener: LogListener): () => void {
    this.logListeners.add(listener);
    return () => this.logListeners.delete(listener);
  }

  onMetric(listener: MetricListener): () => void {
    this.metricListeners.add(listener);
    return () => this.metricListeners.delete(listener);
  }

  onStatus(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => this.statusListeners.delete(listener);
  }

  getStatus(): SseStatus {
    return this.status;
  }

  getStats(): { logEvents: number; metricEvents: number; status: SseStatus } {
    return { logEvents: this.logEvents, metricEvents: this.metricEvents, status: this.status };
  }

  // ── Internals ────────────────────────────────────────────────────────

  private _emitStatus(): void {
    for (const l of this.statusListeners) {
      try {
        l(this.status);
      } catch {
        /* ignore */
      }
    }
  }
}

// ── Singleton ──────────────────────────────────────────────────────────

let _client: SseClient | null = null;

/**
 * SSE URL — uses the Next.js `/api` rewrite (same origin as the FE),
 * so no direct BE port needed. `EventSource` honors the rewrite.
 */
function resolveSseUrl(): string {
  if (typeof window === "undefined") return "";
  return "/api/observability/stream";
}

export function getSseClient(): SseClient {
  if (!_client) {
    _client = new SseClient(resolveSseUrl());
  }
  return _client;
}
