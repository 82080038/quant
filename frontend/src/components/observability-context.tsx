"use client";

/**
 * Observability context — full BE transparency for the dashboard.
 *
 * Consumes the SSE stream (`/api/observability/stream`) and exposes:
 *   - `logs`    : ring buffer of recent BE log entries (max 500)
 *   - `metrics` : latest system metric snapshot (DB / rate-limiters / WS)
 *   - `status`  : SSE connection status
 *   - `wsStats` : WS client counters (recv/sent/dropped) for the console
 *
 * Anti-freeze: log entries are appended to a ref-backed deque and a single
 * rAF-aligned snapshot bump triggers React re-render at most once per frame,
 * regardless of log volume. Widgets read via `useSyncExternalStore`.
 */

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { getSseClient, type ObsLogEntry, type ObsMetric, type SseStatus } from "@/lib/sse-client";
import { getWsClient } from "@/lib/ws-client";

// ── Constants ──────────────────────────────────────────────────────────

const LOG_RING_MAX = 500;

// ── Store (framework-agnostic, lives outside React) ────────────────────

interface ObsStore {
  logs: ObsLogEntry[];
  metric: ObsMetric | null;
  sseStatus: SseStatus;
  wsRecv: number;
  wsSent: number;
  wsDropped: number;
  wsStatus: string;
  version: number; // bump to trigger re-render
}

const _store: ObsStore = {
  logs: [],
  metric: null,
  sseStatus: "idle",
  wsRecv: 0,
  wsSent: 0,
  wsDropped: 0,
  wsStatus: "idle",
  version: 0,
};

let _snapshotRef: ObsStore = _store;
const _listeners: Set<() => void> = new Set();
let _flushScheduled = false;

function _bump(): void {
  // Rebuild snapshot ref so useSyncExternalStore detects the change.
  _snapshotRef = { ..._store, logs: _store.logs, version: _store.version + 1 };
  _store.version = _snapshotRef.version;
  for (const l of _listeners) {
    try {
      l();
    } catch {
      /* ignore */
    }
  }
}

function _scheduleBump(): void {
  if (_flushScheduled) return;
  _flushScheduled = true;
  const schedule = typeof requestAnimationFrame !== "undefined"
    ? requestAnimationFrame
    : (cb: () => void) => setTimeout(cb, 16);
  schedule(() => {
    _flushScheduled = false;
    _bump();
  });
}

function _appendLog(entry: ObsLogEntry): void {
  if (_store.logs.length >= LOG_RING_MAX) _store.logs.shift();
  _store.logs.push(entry);
  _scheduleBump();
}

function _setMetric(metric: ObsMetric): void {
  _store.metric = metric;
  _scheduleBump();
}

function _setSseStatus(status: SseStatus): void {
  _store.sseStatus = status;
  _scheduleBump();
}

// ── React binding ──────────────────────────────────────────────────────

function subscribe(listener: () => void): () => void {
  _listeners.add(listener);
  return () => _listeners.delete(listener);
}

function getSnapshot(): ObsStore {
  return _snapshotRef;
}

// ── Context (for non-hook consumers / providers) ───────────────────────

interface ObservabilityContextValue {
  sseStatus: SseStatus;
  wsStatus: string;
  clearLogs: () => void;
}

const ObservabilityContext = createContext<ObservabilityContextValue | null>(null);

// ── Provider ───────────────────────────────────────────────────────────

export function ObservabilityProvider({ children }: { children: ReactNode }) {
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const sse = getSseClient();
    const ws = getWsClient();

    const offLog = sse.onLog((entry) => _appendLog(entry));
    const offMetric = sse.onMetric((metric) => _setMetric(metric));
    const offStatus = sse.onStatus((status) => _setSseStatus(status));

    // Connect transports.
    sse.connect();
    ws.connect();

    // Periodically mirror WS counters into the store (cheap, 1s).
    const wsMirror = setInterval(() => {
      const s = ws.getStats();
      _store.wsRecv = s.recv;
      _store.wsSent = s.sent;
      _store.wsDropped = s.dropped;
      _store.wsStatus = s.status;
      _scheduleBump();
    }, 1000);

    return () => {
      offLog();
      offMetric();
      offStatus();
      clearInterval(wsMirror);
      // Keep transports connected across route changes (singleton).
    };
  }, []);

  const clearLogs = () => {
    _store.logs = [];
    _bump();
  };

  const value: ObservabilityContextValue = {
    sseStatus: _store.sseStatus,
    wsStatus: _store.wsStatus,
    clearLogs,
  };

  return (
    <ObservabilityContext.Provider value={value}>
      {children}
    </ObservabilityContext.Provider>
  );
}

export function useObservability() {
  const ctx = useContext(ObservabilityContext);
  if (!ctx) throw new Error("useObservability must be used within ObservabilityProvider");
  return ctx;
}

// ── Selectors (useSyncExternalStore — coalesced re-renders) ─────────────

/** Latest N log entries (default 100). Re-renders ≤ 60fps. */
export function useObsLogs(max = 100): ObsLogEntry[] {
  const store = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const total = store.logs.length;
  return total > max ? store.logs.slice(total - max) : store.logs;
}

/** Latest metric snapshot. Re-renders ≤ 60fps. */
export function useObsMetric(): ObsMetric | null {
  const store = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  return store.metric;
}

/** SSE + WS connection status + counters. Re-renders ≤ 60fps. */
export function useObsStatus(): {
  sse: SseStatus;
  ws: string;
  wsRecv: number;
  wsSent: number;
  wsDropped: number;
} {
  const store = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  return {
    sse: store.sseStatus,
    ws: store.wsStatus,
    wsRecv: store.wsRecv,
    wsSent: store.wsSent,
    wsDropped: store.wsDropped,
  };
}
