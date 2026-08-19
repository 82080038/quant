"use client";

/**
 * BE Observability Console — full system transparency widget.
 *
 * Left: status indicators (DB / API / WS / SSE / rate-limiter / backpressure)
 * Right: mini live log stream (SSE) with level coloring + pause/clear.
 *
 * Reads from the observability context (coalesced re-renders ≤ 60fps),
 * so a flood of BE logs never freezes the UI.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, Pause, Play, Trash2 } from "lucide-react";
import { Widget } from "@/components/widget";
import {
  useObsLogs,
  useObsMetric,
  useObsStatus,
  useObservability,
} from "@/components/observability-context";

function dotClass(status: string): string {
  if (status === "ok" || status === "open" || status === "connected") return "ok";
  if (status === "warn" || status === "connecting" || status === "degraded") return "warn";
  if (status === "bad" || status === "error" || status === "closed" || status === "disconnected") return "bad";
  return "idle";
}

function StatusItem({ label, status, detail }: { label: string; status: string; detail?: string }) {
  return (
    <div className="flex items-center gap-1.5 text-[11px]">
      <span className={`status-dot ${dotClass(status)}`} />
      <span className="text-muted-foreground">{label}</span>
      {detail && <span className="font-mono text-foreground/70 ml-auto">{detail}</span>}
    </div>
  );
}

export function ObservabilityConsole() {
  const logs = useObsLogs(120);
  const metric = useObsMetric();
  const status = useObsStatus();
  const { clearLogs } = useObservability();
  const [paused, setPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const logBoxRef = useRef<HTMLDivElement | null>(null);
  const pausedRef = useRef(false);

  // Keep ref in sync so the SSE-driven append path can read it.
  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  // Auto-scroll to bottom when new logs arrive (unless paused or user scrolled up).
  useEffect(() => {
    if (!autoScroll || paused) return;
    const el = logBoxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs, autoScroll, paused]);

  const dbStatus = metric?.db?.connected ? "ok" : metric?.db ? "bad" : "idle";
  const wsStatus = status.ws;
  const sseStatus = status.sse;
  const throttleRate = metric?.ws?.throttle_rate ?? null;
  const limiterCount = metric?.rate_limiters
    ? Object.keys(metric.rate_limiters).length
    : 0;

  // Aggregate a single "API" health from rate-limiter errors if present.
  const apiStatus = useMemo(() => {
    const rl = metric?.rate_limiters;
    if (!rl) return sseStatus === "open" ? "ok" : "idle";
    const anyError = Object.values(rl).some(
      (v) => (v as { totalErrors?: number })?.totalErrors ?? 0 > 0,
    );
    return anyError ? "warn" : "ok";
  }, [metric, sseStatus]);

  return (
    <Widget
      title="BE Observability"
      icon={<Activity className="w-3.5 h-3.5" />}
      accent="text-primary"
      right={
        <div className="flex items-center gap-1">
          <button
            onClick={() => setPaused((p) => !p)}
            className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
            title={paused ? "Lanjutkan stream" : "Jeda stream"}
          >
            {paused ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
          </button>
          <button
            onClick={clearLogs}
            className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
            title="Bersihkan log"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      }
      bodyClassName="!p-0 flex flex-col"
      className="min-h-[160px]"
    >
      <div className="grid grid-cols-2 gap-2 p-2 border-b border-border/50 flex-shrink-0">
        <div className="space-y-1">
          <StatusItem label="DB" status={dbStatus} detail={metric?.db?.connected ? "ON" : "OFF"} />
          <StatusItem label="API" status={apiStatus} detail={`${limiterCount} limiter`} />
          <StatusItem label="WS" status={wsStatus} detail={`${status.wsRecv}↘`} />
          <StatusItem label="SSE" status={sseStatus} detail={`${logs.length} log`} />
        </div>
        <div className="space-y-1">
          <StatusItem
            label="Backpressure"
            status={throttleRate != null ? "warn" : "ok"}
            detail={throttleRate != null ? `${throttleRate}/s` : "OFF"}
          />
          <StatusItem label="WS dropped" status={status.wsDropped > 0 ? "warn" : "ok"} detail={`${status.wsDropped}`} />
          <StatusItem label="WS sent" status="idle" detail={`${status.wsSent}↗`} />
          <StatusItem
            label="Log ring"
            status="idle"
            detail={`${metric?.log_ring_size ?? 0}`}
          />
        </div>
      </div>
      <div
        ref={logBoxRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
          setAutoScroll(atBottom);
        }}
        className="obs-log flex-1 min-h-0 overflow-auto p-2"
      >
        {logs.length === 0 ? (
          <div className="text-muted-foreground/60 italic px-1">
            Menunggu stream log dari BE…
          </div>
        ) : (
          <VirtualLogList logs={logs} paused={paused} autoScroll={autoScroll} containerRef={logBoxRef} />
        )}
      </div>
    </Widget>
  );
}

// ── Virtual scrolling log list ───────────────────────────────────────────

const LOG_LINE_HEIGHT = 16; // px per log line (leading-snug + padding)

function VirtualLogList({
  logs,
  paused,
  autoScroll,
  containerRef,
}: {
  logs: { ts: number; level: string; src: string; msg: string }[];
  paused: boolean;
  autoScroll: boolean;
  containerRef: React.RefObject<HTMLDivElement | null>;
}) {
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(200);
  const rafRef = useRef(0);

  // Track scroll position with rAF throttling
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const onScroll = () => {
      if (rafRef.current) return;
      rafRef.current = requestAnimationFrame(() => {
        setScrollTop(el.scrollTop);
        rafRef.current = 0;
      });
    };

    const onResize = () => setViewportH(el.clientHeight);
    onResize();

    el.addEventListener("scroll", onScroll, { passive: true });
    const ro = new ResizeObserver(onResize);
    ro.observe(el);

    return () => {
      el.removeEventListener("scroll", onScroll);
      ro.disconnect();
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [containerRef]);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (!autoScroll || paused) return;
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs, autoScroll, paused, containerRef]);

  const totalH = logs.length * LOG_LINE_HEIGHT;
  const startIndex = Math.max(0, Math.floor(scrollTop / LOG_LINE_HEIGHT) - 5);
  const endIndex = Math.min(
    logs.length,
    Math.ceil((scrollTop + viewportH) / LOG_LINE_HEIGHT) + 5,
  );
  const visibleLogs = logs.slice(startIndex, endIndex);
  const offsetY = startIndex * LOG_LINE_HEIGHT;

  return (
    <div style={{ height: totalH, position: "relative" }}>
      <div style={{ transform: `translateY(${offsetY}px)` }}>
        {visibleLogs.map((l, i) => {
          const time = new Date(l.ts * 1000).toLocaleTimeString("en-GB", { hour12: false });
          return (
            <div
              key={startIndex + i}
              className="leading-snug"
              style={{ height: LOG_LINE_HEIGHT }}
            >
              <span className="text-muted-foreground/70">{time}</span>{" "}
              <span className={`lvl-${l.level}`}>[{l.level}]</span>{" "}
              <span className="text-muted-foreground/80">{l.src}</span>{" "}
              <span>{l.msg}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
