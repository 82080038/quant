"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Cpu, Power, TrendingUp, TrendingDown, Zap, Activity } from "lucide-react";
import { cn } from "@/lib/utils";

interface EngineEntry {
  engine_name: string;
  engine_type: string;
  is_active: boolean;
  accuracy_score: number;
  weight_percentage: number;
}

interface EnsembleProgress {
  running: boolean;
  done: boolean;
  current_day: number;
  total_trading_days: number;
  sim_date: string | null;
  directional_accuracy: number;
  equity: number;
  n_predictions: number;
  n_correct: number;
  message: string;
  orchestration_log: string[];
  active_engines: EngineEntry[];
  deactivated_engines: string[];
}

const TYPE_COLORS: Record<string, string> = {
  FACTOR_MODEL: "text-purple-400",
  ALPHA: "text-blue-400",
  TECHNICAL: "text-cyan-400",
  VOLUME: "text-green-400",
  DEEP_LEARNING: "text-pink-400",
  ML_ENSEMBLE: "text-orange-400",
  TIME_CYCLE: "text-yellow-400",
  CAUSALITY: "text-red-400",
  GLOBAL_CAUSALITY: "text-red-400",
  REGIME: "text-indigo-400",
  VOLATILITY: "text-amber-400",
  RELATIONSHIP: "text-teal-400",
  FUNDAMENTAL: "text-emerald-400",
  MACRO: "text-sky-400",
  SENTIMENT: "text-rose-400",
  POLICY: "text-violet-400",
  SCREENING: "text-lime-400",
  META: "text-fuchsia-400",
  META_LEARNING: "text-fuchsia-400",
  SELF_HEALING: "text-orange-400",
  ORCHESTRATION: "text-gray-400",
};

export function EngineOrchestrationLog() {
  const [engines, setEngines] = useState<EngineEntry[]>([]);
  const [progress, setProgress] = useState<EnsembleProgress | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const logRef = useRef<HTMLDivElement | null>(null);
  const prevLogLen = useRef(0);

  const fetchEngines = useCallback(async () => {
    try {
      const res = await fetch("/api/engine-registry");
      if (res.ok) {
        const data = await res.json();
        if (data.engines) setEngines(data.engines);
      }
    } catch {
      // ignore
    }
  }, []);

  const fetchProgress = useCallback(async () => {
    try {
      const res = await fetch("/api/ensemble-tuning/progress");
      if (res.ok) {
        const data = await res.json();
        setProgress(data);
        if (data.orchestration_log && data.orchestration_log.length > prevLogLen.current) {
          const newLines = data.orchestration_log.slice(prevLogLen.current);
          setLogLines((prev) => [...prev, ...newLines].slice(-100));
          prevLogLen.current = data.orchestration_log.length;
        }
      }
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchEngines();
    fetchProgress();
    const id = setInterval(() => {
      fetchEngines();
      fetchProgress();
    }, 3000);
    return () => clearInterval(id);
  }, [fetchEngines, fetchProgress]);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logLines]);

  const startTuning = useCallback(async () => {
    try {
      await fetch("/api/ensemble-tuning/run", { method: "POST" });
      setLogLines([]);
      prevLogLen.current = 0;
      fetchProgress();
    } catch {
      // ignore
    }
  }, [fetchProgress]);

  const running = progress?.running ?? false;
  const done = progress?.done ?? false;
  const activeCount = engines.filter((e) => e.is_active).length;
  const inactiveCount = engines.length - activeCount;
  const pct = progress && progress.total_trading_days > 0
    ? (progress.current_day / progress.total_trading_days) * 100
    : 0;

  const logColor = (line: string) => {
    if (line.includes("Mematikan")) return "text-red-400";
    if (line.includes("Mengaktifkan")) return "text-emerald-400";
    if (line.includes("Selesai")) return "text-emerald-400";
    if (line.includes("Error") || line.includes("error")) return "text-red-400";
    if (line.includes("Memulai")) return "text-yellow-400";
    return "text-muted-foreground";
  };

  return (
    <div className="space-y-3">
      {/* Header + Run button */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-purple-400" />
          <h3 className="text-sm font-semibold">Orkestrasi Engine Hybrid</h3>
          <span className="text-xs text-muted-foreground">
            ({activeCount} aktif / {inactiveCount} mati)
          </span>
        </div>
        <button
          onClick={startTuning}
          disabled={running}
          className="px-3 py-1 rounded-md bg-purple-600 text-white text-xs font-medium hover:bg-purple-700 disabled:opacity-50 flex items-center gap-1"
        >
          {running ? <Activity className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
          {running ? "Menyimulasikan..." : "Tuning Ensemble"}
        </button>
      </div>

      {/* Progress bar */}
      {progress && (running || done) && progress.total_trading_days > 0 && (
        <div className="space-y-1">
          <div className="w-full bg-muted rounded-full h-2 overflow-hidden">
            <div
              className="h-full bg-purple-500 transition-all duration-500 rounded-full"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-[10px] text-muted-foreground text-center">
            Hari {progress.current_day}/{progress.total_trading_days}
            {progress.sim_date && ` | ${progress.sim_date}`}
            {progress.directional_accuracy > 0 && ` | DA: ${progress.directional_accuracy.toFixed(1)}%`}
            {progress.equity > 0 && ` | Rp ${(progress.equity / 1_000_000).toFixed(2)}Jt`}
          </p>
        </div>
      )}

      {/* Engine badges grid */}
      <div className="grid grid-cols-4 md:grid-cols-6 gap-1.5">
        {engines.slice(0, 18).map((e) => (
          <div
            key={e.engine_name}
            className={cn(
              "rounded border px-1.5 py-1 text-[10px] truncate",
              e.is_active
                ? "border-emerald-500/30 bg-emerald-500/5"
                : "border-red-500/30 bg-red-500/5 opacity-50"
            )}
            title={`${e.engine_name} | ${e.engine_type} | DA: ${e.accuracy_score}% | W: ${e.weight_percentage}%`}
          >
            <div className="flex items-center gap-0.5">
              {e.is_active ? (
                <Power className="w-2.5 h-2.5 text-emerald-400 flex-shrink-0" />
              ) : (
                <Power className="w-2.5 h-2.5 text-red-400 flex-shrink-0" />
              )}
              <span className={cn("font-mono truncate", TYPE_COLORS[e.engine_type] || "text-muted-foreground")}>
                {e.engine_name.length > 12 ? e.engine_name.slice(0, 10) + ".." : e.engine_name}
              </span>
            </div>
            <div className="flex items-center justify-between mt-0.5">
              <span className="text-muted-foreground/60">{e.accuracy_score > 0 ? `${e.accuracy_score.toFixed(0)}%` : "—"}</span>
              <span className="text-muted-foreground/60">{e.weight_percentage > 0 ? `${e.weight_percentage.toFixed(0)}%` : ""}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Live orchestration log */}
      <div className="rounded-md border border-border bg-black/30 overflow-hidden">
        <div className="px-2 py-1 border-b border-border/50 text-[10px] font-semibold text-muted-foreground flex items-center gap-1">
          <Activity className="w-3 h-3" />
          Log Orkestrasi Real-time
        </div>
        <div
          ref={logRef}
          className="h-32 overflow-y-auto p-2 font-mono text-[10px] leading-tight space-y-0.5"
        >
          {logLines.length === 0 ? (
            <div className="text-muted-foreground/50 italic">
              Menunggu aktivitas orkestrasi engine... Klik "Tuning Ensemble" untuk memulai.
            </div>
          ) : (
            logLines.map((line, i) => (
              <div key={i} className={logColor(line)}>
                {line}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Done summary */}
      {done && progress && (
        <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-2 text-xs">
          <span className="text-emerald-400 font-medium">✅ {progress.message}</span>
        </div>
      )}
    </div>
  );
}
