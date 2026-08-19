"use client";

import { useEffect, useState, useCallback } from "react";
import { Activity, Clock, Globe } from "lucide-react";
import { Widget } from "@/components/widget";

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
}

interface SessionsResponse {
  current_time_utc: string;
  current_time_wib: string;
  open_count: number;
  total: number;
  sessions: SessionStatus[];
}

const STATUS_COLORS: Record<string, string> = {
  OPEN: "text-green-400",
  "PRE-MARKET": "text-yellow-400",
  "POST-MARKET": "text-orange-400",
  CLOSED: "text-slate-500",
  HOLIDAY: "text-red-400",
  WEEKEND: "text-red-400",
};

const STATUS_BG: Record<string, string> = {
  OPEN: "bg-green-500/10 border-green-500/30",
  "PRE-MARKET": "bg-yellow-500/10 border-yellow-500/30",
  "POST-MARKET": "bg-orange-500/10 border-orange-500/30",
  CLOSED: "bg-slate-700/30 border-slate-600/30",
  HOLIDAY: "bg-red-500/10 border-red-500/30",
  WEEKEND: "bg-red-500/10 border-red-500/30",
};

const STATUS_DOT: Record<string, string> = {
  OPEN: "bg-green-400 animate-pulse",
  "PRE-MARKET": "bg-yellow-400",
  "POST-MARKET": "bg-orange-400",
  CLOSED: "bg-slate-600",
  HOLIDAY: "bg-red-400",
  WEEKEND: "bg-red-400",
};

export function MarketClockWidget() {
  const [data, setData] = useState<SessionsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    try {
      const res = await fetch("/api/scheduler/sessions");
      if (res.ok) {
        try { setData(await res.json()); } catch {}
      }
    } catch {
      // Network error — keep previous data
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
    const id = setInterval(loadData, 10_000); // Refresh every 10s
    return () => clearInterval(id);
  }, [loadData]);

  if (!data && loading) {
    return (
      <Widget title="Global Market Clock" icon={<Globe className="w-4 h-4" />}>
        <div className="flex items-center justify-center h-32 text-slate-500">
          <Clock className="w-5 h-5 animate-pulse mr-2" />
          Loading sessions...
        </div>
      </Widget>
    );
  }

  if (!data) return null;

  const sorted = [...data.sessions].sort((a, b) => {
    // Open markets first, then by open time
    const aOpen = a.status === "OPEN" ? 0 : 1;
    const bOpen = b.status === "OPEN" ? 0 : 1;
    if (aOpen !== bOpen) return aOpen - bOpen;
    return a.open_time_utc.localeCompare(b.open_time_utc);
  });

  return (
    <Widget title="Global Market Clock" icon={<Globe className="w-4 h-4" />}>
      {/* Header: current times */}
      <div className="flex items-center gap-4 mb-3 pb-3 border-b border-slate-700/50">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-cyan-400" />
          <span className="text-xs text-slate-400">UTC</span>
          <span className="text-sm font-mono text-cyan-300">{data.current_time_utc}</span>
        </div>
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-amber-400" />
          <span className="text-xs text-slate-400">WIB</span>
          <span className="text-sm font-mono text-amber-300">{data.current_time_wib}</span>
        </div>
        <div className="ml-auto text-xs text-slate-500">
          {data.open_count}/{data.total} open
        </div>
      </div>

      {/* Session list */}
      <div className="space-y-1 max-h-[280px] overflow-y-auto scrollbar-thin">
        {sorted.map((s) => (
          <div
            key={s.market_code}
            className={`flex items-center gap-2 px-2 py-1.5 rounded border ${STATUS_BG[s.status] || STATUS_BG.CLOSED}`}
          >
            {/* Status dot */}
            <div className={`w-2 h-2 rounded-full ${STATUS_DOT[s.status] || STATUS_DOT.CLOSED}`} />

            {/* Market code */}
            <span className="text-xs font-bold text-slate-200 w-12">{s.market_code}</span>

            {/* Market name (truncated) */}
            <span className="text-xs text-slate-400 flex-1 truncate">{s.market_name}</span>

            {/* Times */}
            <span className="text-xs font-mono text-slate-300">
              {s.open_time_wib.slice(0, 5)}–{s.close_time_wib.slice(0, 5)}
            </span>

            {/* DST indicator */}
            {s.is_dst_active && (
              <span className="text-[10px] text-blue-400 font-bold">DST</span>
            )}

            {/* Status badge */}
            <span className={`text-[10px] font-bold ${STATUS_COLORS[s.status] || STATUS_COLORS.CLOSED}`}>
              {s.status}
            </span>
          </div>
        ))}
      </div>
    </Widget>
  );
}
