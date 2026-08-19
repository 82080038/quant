/**
 * WebSocket client singleton for the Astronacci dashboard.
 *
 * Design (anti-freeze):
 *   - One shared WebSocket for all channels (prices/signals/portfolio).
 *   - Incoming messages mutate a ref-backed ring buffer; React is NOT
 *     notified per message. A `useSyncExternalStore`-compatible subscriber
 *     API lets widgets read the latest snapshot, and a single rAF coalesces
 *     notifications to at most one listener flush per animation frame.
 *   - Auto-reconnect with exponential backoff + jitter (reuses the existing
 *     `AdaptiveRateLimiter` backoff math via a lightweight local helper).
 *   - Bidirectional backpressure: `sendThrottle(maxRate)` / `sendThrottleOff()`
 *     tell the BE to reduce push rate when the FE is struggling.
 *   - Subscribe/unsubscribe per channel so the BE only pushes what we need.
 *
 * The client is transport-only; domain decoding lives in widgets/context.
 */

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

// ── Types ──────────────────────────────────────────────────────────────

export type WsStatus = "idle" | "connecting" | "open" | "closed" | "error";

export interface WsMessage {
  ch: string;
  t?: string;
  p?: number;
  ts?: number;
  sig?: unknown;
  [k: string]: unknown;
}

type Listener = () => void;
type ChannelListener = (msg: WsMessage) => void;

interface Sub {
  channels: Set<string>;
  onMessage: ChannelListener;
}

// ── Constants ──────────────────────────────────────────────────────────

const RING_MAX = 1024;            // keep last 1024 raw messages per channel-bucket
const BACKOFF_MIN_MS = 500;
const BACKOFF_MAX_MS = 15000;
const BACKOFF_FACTOR = 2;
const JITTER_RATIO = 0.25;
const COALESCE_FRAME_MS = 16;     // ~60fps; flush listeners at most once per frame

// ── Backoff helper (mirrors AdaptiveRateLimiter math, no async acquire) ──

function nextBackoff(attempt: number): number {
  const base = Math.min(
    BACKOFF_MIN_MS * BACKOFF_FACTOR ** (attempt - 1),
    BACKOFF_MAX_MS,
  );
  const jitter = base * JITTER_RATIO * (Math.random() * 2 - 1);
  return Math.max(BACKOFF_MIN_MS, base + jitter);
}

// ── Client ─────────────────────────────────────────────────────────────

class WsClient {
  private url: string;
  private ws: WebSocket | null = null;
  private status: WsStatus = "idle";
  private attempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByUser = false;

  // Per-channel latest snapshot (ref-backed, no React state).
  private latest: Map<string, WsMessage> = new Map();
  // Per-channel ring buffer (raw history for charts).
  private rings: Map<string, WsMessage[]> = new Map();

  // Subscribers (widgets) keyed by id.
  private subs: Map<number, Sub> = new Map();
  private nextSubId = 1;

  // External store listeners (useSyncExternalStore).
  private storeListeners: Set<Listener> = new Set();
  private flushScheduled = false;

  // Aggregate counters for observability.
  recv = 0;
  sent = 0;
  dropped = 0;

  constructor(url: string) {
    this.url = url;
    if (typeof window !== "undefined") {
      // Reconnect when tab becomes visible again (browser may have dropped).
      window.addEventListener("online", () => this.connect());
    }
  }

  // ── Lifecycle ────────────────────────────────────────────────────────

  connect(): void {
    if (typeof window === "undefined") return;
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
    this.closedByUser = false;
    this.status = "connecting";
    this._emitStatus();

    try {
      this.ws = new WebSocket(this.url);
    } catch (err) {
      this.status = "error";
      this._emitStatus();
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.attempt = 0;
      this.status = "open";
      this._emitStatus();
      // Re-subscribe all active channels after (re)connect.
      const all = new Set<string>();
      for (const s of this.subs.values()) for (const c of s.channels) all.add(c);
      if (all.size > 0) this._send({ cmd: "subscribe", channels: [...all] });
    };

    this.ws.onmessage = (ev) => {
      this.recv++;
      let msg: WsMessage;
      try {
        msg = JSON.parse(ev.data) as WsMessage;
      } catch {
        this.dropped++;
        return;
      }
      const ch = msg.ch;
      if (!ch) return;
      this.latest.set(ch, msg);
      const ring = this.rings.get(ch);
      if (ring) {
        if (ring.length >= RING_MAX) ring.shift();
        ring.push(msg);
      } else {
        this.rings.set(ch, [msg]);
      }
      // Dispatch to channel subscribers (synchronous, cheap).
      for (const s of this.subs.values()) {
        if (s.channels.has(ch)) {
          try {
            s.onMessage(msg);
          } catch {
            /* swallow widget errors */
          }
        }
      }
      // Coalesced store notification (max 1 flush/frame).
      this._scheduleFlush();
    };

    this.ws.onerror = () => {
      this.status = "error";
      this._emitStatus();
    };

    this.ws.onclose = () => {
      this.status = "closed";
      this._emitStatus();
      if (!this.closedByUser) this._scheduleReconnect();
    };
  }

  disconnect(): void {
    this.closedByUser = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        /* ignore */
      }
      this.ws = null;
    }
    this.status = "idle";
    this._emitStatus();
  }

  // ── Pub/sub API for widgets ──────────────────────────────────────────

  /**
   * Subscribe to one or more channels. Returns an unsubscribe function.
   * `onMessage` is invoked synchronously on each message — keep it cheap
   * (mutate a ref, do NOT setState directly; use the coalesced store API
   * for React re-renders).
   */
  subscribe(channels: string[], onMessage: ChannelListener): () => void {
    const id = this.nextSubId++;
    const chSet = new Set(channels);
    this.subs.set(id, { channels: chSet, onMessage });
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this._send({ cmd: "subscribe", channels });
    }
    return () => {
      this.subs.delete(id);
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this._send({ cmd: "unsubscribe", channels });
      }
    };
  }

  /** Latest message for a channel (or undefined). Ref-safe read. */
  latestOf(channel: string): WsMessage | undefined {
    return this.latest.get(channel);
  }

  /** Ring buffer snapshot (oldest→newest) for a channel. */
  ringOf(channel: string): WsMessage[] {
    return this.rings.get(channel) ?? [];
  }

  // ── External store API (useSyncExternalStore) ────────────────────────

  /**
   * Subscribe to coalesced store changes. The listener is called at most
   * once per animation frame regardless of message volume. Returns unsubscribe.
   */
  subscribeStore = (listener: Listener): (() => void) => {
    this.storeListeners.add(listener);
    return () => this.storeListeners.delete(listener);
  };

  /** Snapshot getter for `useSyncExternalStore` (must return stable ref). */
  getSnapshot = (): WsSnapshot => {
    return this._snapshotRef;
  };

  // ── Backpressure commands ────────────────────────────────────────────

  sendThrottle(maxRate: number): void {
    this._send({ cmd: "throttle", max_rate: maxRate });
  }

  sendThrottleOff(): void {
    this._send({ cmd: "throttle_off" });
  }

  // ── Status ───────────────────────────────────────────────────────────

  getStatus(): WsStatus {
    return this.status;
  }

  getStats(): { recv: number; sent: number; dropped: number; status: WsStatus } {
    return { recv: this.recv, sent: this.sent, dropped: this.dropped, status: this.status };
  }

  // ── Internals ────────────────────────────────────────────────────────

  private _send(payload: unknown): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    try {
      this.ws.send(JSON.stringify(payload));
      this.sent++;
    } catch {
      /* ignore */
    }
  }

  private _scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.attempt++;
    const delay = nextBackoff(this.attempt);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private _scheduleFlush(): void {
    if (this.flushScheduled) return;
    this.flushScheduled = true;
    // Use rAF for frame-aligned coalescing; fallback to setTimeout(0).
    const schedule = typeof requestAnimationFrame !== "undefined"
      ? requestAnimationFrame
      : (cb: () => void) => setTimeout(cb, COALESCE_FRAME_MS);
    schedule(() => {
      this.flushScheduled = false;
      // Rebuild snapshot ref so useSyncExternalStore sees a change.
      this._snapshotRef = {
        status: this.status,
        recv: this.recv,
        sent: this.sent,
        dropped: this.dropped,
        channels: [...this.latest.keys()],
        ts: Date.now(),
      };
      for (const l of this.storeListeners) {
        try {
          l();
        } catch {
          /* ignore */
        }
      }
    });
  }

  private _emitStatus(): void {
    this._snapshotRef = {
      status: this.status,
      recv: this.recv,
      sent: this.sent,
      dropped: this.dropped,
      channels: [...this.latest.keys()],
      ts: Date.now(),
    };
    for (const l of this.storeListeners) {
      try {
        l();
      } catch {
        /* ignore */
      }
    }
  }

  // Stable snapshot ref (mutated only on flush / status change).
  private _snapshotRef: WsSnapshot = {
    status: "idle",
    recv: 0,
    sent: 0,
    dropped: 0,
    channels: [],
    ts: 0,
  };
}

export interface WsSnapshot {
  status: WsStatus;
  recv: number;
  sent: number;
  dropped: number;
  channels: string[];
  ts: number;
}

// ── Singleton ──────────────────────────────────────────────────────────

/**
 * Resolve the WS URL. Next.js rewrites `/api/:path*` to the BE, but
 * WebSocket upgrade is not reliably proxied by `rewrites()`; connect
 * directly to the BE when `NEXT_PUBLIC_WS_URL` is set, otherwise derive
 * from `window.location` (same host, BE port 8000 by convention).
 */
function resolveWsUrl(): string {
  if (typeof window === "undefined") return "";
  const explicit = process.env.NEXT_PUBLIC_WS_URL;
  if (explicit) return explicit;
  const host = window.location.hostname;
  // Dev: BE runs on :8000. Prod: assume same origin (reverse proxy).
  return window.location.port === "3000"
    ? `ws://${host}:8000/ws`
    : `ws://${window.location.host}/ws`;
}

let _client: WsClient | null = null;

export function getWsClient(): WsClient {
  if (!_client) {
    _client = new WsClient(resolveWsUrl());
  }
  return _client;
}

/** React hook: coalesced WS status snapshot (re-renders ≤ 60fps). */
export function useWsStatus(): WsSnapshot {
  return useSyncExternalStore(
    (cb: () => void) => getWsClient().subscribeStore(cb),
    getWsClient().getSnapshot,
    getWsClient().getSnapshot,
  );
}

// ── Per-channel coalesced hook ─────────────────────────────────────────
//
// Returns the latest message on `channel`, re-rendering at most once per
// animation frame regardless of message volume. The raw message stream is
// kept in the client's ring buffer (see `ringOf`) for chart history.

export function useWsLatest(channel: string): WsMessage | undefined {
  const [, bump] = useState(0);
  const latestRef = useRef<WsMessage | undefined>(undefined);
  useEffect(() => {
    const client = getWsClient();
    // Seed from any already-buffered message.
    latestRef.current = client.latestOf(channel);
    // Register this subscriber's re-render with the shared rAF flush.
    const flush = () => bump((n) => n + 1);
    _bumpCbs.add(flush);
    const unsub = client.subscribe([channel], (msg) => {
      latestRef.current = msg;
      // Coalesce: schedule a single re-render on the next frame.
      scheduleBump();
    });
    return () => {
      unsub();
      _bumpCbs.delete(flush);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel]);
  // `scheduleBump` is module-scoped (shared rAF flush).
  return latestRef.current;
}

// Shared rAF coalescer for all `useWsLatest` subscribers — one flush/frame.
let _bumpScheduled = false;
const _bumpCbs: Set<() => void> = new Set();
function scheduleBump(): void {
  if (_bumpScheduled) return;
  _bumpScheduled = true;
  const schedule = typeof requestAnimationFrame !== "undefined"
    ? requestAnimationFrame
    : (cb: () => void) => setTimeout(cb, 16);
  schedule(() => {
    _bumpScheduled = false;
    for (const cb of _bumpCbs) {
      try {
        cb();
      } catch {
        /* ignore */
      }
    }
  });
}
