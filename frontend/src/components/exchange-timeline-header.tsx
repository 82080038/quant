"use client";

/**
 * Exchange Timeline Header — global market session strip.
 *
 * Displays all world exchanges as compact cards sorted left→right by
 * WIB open time (earliest open → latest close).  Visual causality
 * connectors (gradient arrows) between cards imply that price action
 * in earlier markets can lead later ones.
 *
 * Data source: /api/scheduler/sessions-with-indices (10s polling).
 * DST-aware: open/close times auto-adjust when is_dst_active is true.
 * Each card shows the exchange's major index symbol + change percentage.
 */

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { ChevronRight, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { getMoonPhase, moonSvgPath, type MoonPhaseInfo } from "@/lib/moon-phase";

// ── Types ────────────────────────────────────────────────────────────────

interface IndexData {
  symbol: string;
  name: string;
  yahoo_ticker: string;
  priority: number;
  price: number | null;
  change: number;
  change_pct: number;
  date?: string;
}

interface SessionStatus {
  market_code: string;
  market_name: string;
  status: string;
  open_time_utc: string;
  close_time_utc: string;
  open_time_wib: string;
  close_time_wib: string;
  current_time_utc: string;
  current_time_wib: string;
  current_time_local: string;
  timezone_iana: string;
  has_dst: boolean;
  current_offset_hours: number;
  is_dst_active: boolean;
  indices: IndexData[];
}

interface SessionsResponse {
  current_time_utc: string;
  current_time_wib: string;
  open_count: number;
  total: number;
  sessions: SessionStatus[];
}

// ── Status styling ───────────────────────────────────────────────────────

const STATUS_BORDER: Record<string, string> = {
  OPEN: "border-green-500/50 shadow-[0_0_8px_rgba(34,197,94,0.25)]",
  "PRE-MARKET": "border-yellow-500/40 shadow-[0_0_6px_rgba(234,179,8,0.2)]",
  "POST-MARKET": "border-orange-500/40 shadow-[0_0_6px_rgba(249,115,22,0.2)]",
  CLOSED: "border-slate-700/40",
  HOLIDAY: "border-red-500/40",
  WEEKEND: "border-red-500/40",
};

const STATUS_DOT: Record<string, string> = {
  OPEN: "bg-green-400 animate-pulse",
  "PRE-MARKET": "bg-yellow-400",
  "POST-MARKET": "bg-orange-400",
  CLOSED: "bg-slate-600",
  HOLIDAY: "bg-red-400",
  WEEKEND: "bg-red-400",
};

const STATUS_TEXT: Record<string, string> = {
  OPEN: "text-green-400",
  "PRE-MARKET": "text-yellow-400",
  "POST-MARKET": "text-orange-400",
  CLOSED: "text-slate-500",
  HOLIDAY: "text-red-400",
  WEEKEND: "text-red-400",
};

const STATUS_LABEL_SHORT: Record<string, string> = {
  OPEN: "OPEN",
  "PRE-MARKET": "PRE",
  "POST-MARKET": "POST",
  CLOSED: "CLOSED",
  HOLIDAY: "HOL",
  "WEEKEND": "WEEK",
};

// ── Moon Phase mini-icon ─────────────────────────────────────────────────

function MoonIcon({ phase, size = 10 }: { phase: MoonPhaseInfo; size?: number }) {
  const isWaxing = phase.illumination > 0 && phase.name.includes("Waxing");
  const path = moonSvgPath(phase.illumination, isWaxing, size);
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      <path d={path} fill="rgba(255,255,255,0.85)" stroke="rgba(255,255,255,0.3)" strokeWidth={0.3} />
    </svg>
  );
}

// ── Component ────────────────────────────────────────────────────────────

export function ExchangeTimelineHeader() {
  const [data, setData] = useState<SessionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const prevOrderRef = useRef<string[]>([]);

  // Compute moon phase once per render cycle (updates every poll)
  const moonPhase = useMemo(() => getMoonPhase(), [data?.current_time_utc]);

  const loadData = useCallback(async () => {
    try {
      const res = await fetch("/api/scheduler/sessions-with-indices");
      if (res.ok) {
        try { setData(await res.json()); } catch { /* keep prev */ }
      }
    } catch {
      // Network error — keep previous data
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
    const id = setInterval(loadData, 10_000);
    return () => clearInterval(id);
  }, [loadData]);

  // Sort by WIB open time (earliest → latest), then by close time
  const sorted = useMemo(() => {
    if (!data?.sessions) return [];
    return [...data.sessions].sort((a, b) => {
      // Compare by open_time_wib (HH:MM:SS string sort works for time)
      const openCmp = a.open_time_wib.localeCompare(b.open_time_wib);
      if (openCmp !== 0) return openCmp;
      // Tie-break by close time
      return a.close_time_wib.localeCompare(b.close_time_wib);
    });
  }, [data]);

  // Track order changes for smooth transition
  const currentOrder = sorted.map(s => s.market_code);
  const orderChanged = currentOrder.join(",") !== prevOrderRef.current.join(",");
  if (orderChanged) {
    prevOrderRef.current = currentOrder;
  }

  if (!data && loading) {
    return (
      <div className="flex items-center gap-2 px-3 h-10 rounded-md border border-border/60 bg-card/60 backdrop-blur-sm text-xs shrink-0">
        <Clock className="w-3.5 h-3.5 animate-pulse text-muted-foreground" />
        <span className="text-muted-foreground">Loading global sessions...</span>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="flex items-center gap-0 px-2 h-10 rounded-md border border-border/60 bg-card/60 backdrop-blur-sm text-xs overflow-hidden shrink-0">
      {/* Clock display with moon phase */}
      <div className="flex items-center gap-1.5 px-2 shrink-0 border-r border-border/40 h-full">
        <Clock className="w-3 h-3 text-amber-400" />
        <span className="font-mono text-amber-300 text-[11px]">{data.current_time_wib}</span>
        <span className="text-[9px] text-muted-foreground">WIB</span>
        <div className="w-px h-3 bg-border/40 mx-0.5" />
        <MoonIcon phase={moonPhase} size={11} />
        <span className="text-[8px] text-slate-400 leading-none" title={moonPhase.name}>
          {(moonPhase.illumination * 100).toFixed(0)}%
        </span>
      </div>

      {/* Exchange cards with causality connectors */}
      <div className="flex items-center gap-0 overflow-x-auto scrollbar-none flex-1 h-full py-1">
        {sorted.map((s, i) => {
          const isOpen = s.status === "OPEN";
          const isPre = s.status === "PRE-MARKET";
          const isPost = s.status === "POST-MARKET";
          const isActive = isOpen || isPre || isPost;

          return (
            <div key={s.market_code} className="flex items-center shrink-0">
              {/* Causality connector (gradient arrow between cards) */}
              {i > 0 && (
                <div className="flex items-center shrink-0 mx-px">
                  <div
                    className={cn(
                      "h-px w-3 transition-colors duration-500",
                      isActive
                        ? "bg-gradient-to-r from-green-500/30 to-cyan-500/30"
                        : "bg-border/30"
                    )}
                  />
                  <ChevronRight
                    className={cn(
                      "w-2.5 h-2.5 transition-colors duration-500",
                      isActive ? "text-cyan-400/40" : "text-border/40"
                    )}
                  />
                </div>
              )}

              {/* Exchange card */}
              <div
                className={cn(
                  "flex flex-col items-center justify-center px-2 py-0.5 rounded border transition-all duration-500 ease-in-out",
                  "min-w-[72px] gap-0",
                  STATUS_BORDER[s.status] || STATUS_BORDER.CLOSED,
                  isOpen && "bg-green-500/5",
                  isPre && "bg-yellow-500/5",
                  isPost && "bg-orange-500/5",
                  !isActive && "bg-transparent",
                )}
              >
                {/* Top row: market code + status dot + moon */}
                <div className="flex items-center gap-1 w-full justify-center">
                  <div className={cn(
                    "w-1.5 h-1.5 rounded-full shrink-0",
                    STATUS_DOT[s.status] || STATUS_DOT.CLOSED
                  )} />
                  <span className="font-bold text-[10px] text-slate-200 leading-none">
                    {s.market_code}
                  </span>
                  {s.is_dst_active && (
                    <span className="text-[7px] text-blue-400 font-bold leading-none">D</span>
                  )}
                  <MoonIcon phase={moonPhase} size={8} />
                </div>

                {/* Index row: symbol + change% */}
                {s.indices && s.indices.length > 0 && s.indices[0].price != null ? (
                  <div className="flex items-center gap-1 mt-0.5 w-full justify-center">
                    <span className="text-[8px] text-slate-300 font-semibold leading-none">
                      {s.indices[0].symbol}
                    </span>
                    <span className={cn(
                      "text-[8px] font-mono font-bold leading-none",
                      s.indices[0].change_pct > 0
                        ? "text-emerald-400"
                        : s.indices[0].change_pct < 0
                        ? "text-red-400"
                        : "text-slate-400"
                    )}>
                      {s.indices[0].change_pct > 0 ? "+" : ""}
                      {s.indices[0].change_pct.toFixed(2)}%
                    </span>
                  </div>
                ) : (
                  <div className="flex items-center gap-0.5 mt-0.5">
                    <span className="font-mono text-[8px] text-slate-600 leading-none">
                      {s.open_time_wib.slice(0, 5)}-{s.close_time_wib.slice(0, 5)}
                    </span>
                  </div>
                )}

                {/* Bottom row: WIB times (always visible) */}
                <div className="flex items-center gap-0.5 mt-px">
                  <span className="font-mono text-[7px] text-slate-500 leading-none">
                    {s.open_time_wib.slice(0, 5)}
                  </span>
                  <span className="text-[6px] text-slate-700 leading-none">-</span>
                  <span className="font-mono text-[7px] text-slate-500 leading-none">
                    {s.close_time_wib.slice(0, 5)}
                  </span>
                </div>

                {/* Status label (tiny) */}
                <span className={cn(
                  "text-[7px] font-bold leading-none mt-px",
                  STATUS_TEXT[s.status] || STATUS_TEXT.CLOSED
                )}>
                  {STATUS_LABEL_SHORT[s.status] || s.status}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Summary badge */}
      <div className="flex items-center gap-1.5 px-2 shrink-0 border-l border-border/40 h-full">
        <div className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
        <span className="font-mono text-[10px] text-green-400">{data.open_count}</span>
        <span className="text-[9px] text-muted-foreground">/ {data.total} open</span>
      </div>
    </div>
  );
}
