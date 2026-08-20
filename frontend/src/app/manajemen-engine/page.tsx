"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import {
  Activity,
  Cpu,
  Power,
  TrendingUp,
  TrendingDown,
  Zap,
  Terminal,
  Pause,
  Play,
  Trash2,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ────────────────────────────────────────────────────────────────

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

interface WeightHistoryPoint {
  tick: number;
  weights: Record<string, number>;
}

// ── Constants ────────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, string> = {
  FACTOR_MODEL: "#a855f7",
  ALPHA: "#3b82f6",
  TECHNICAL: "#06b6d4",
  VOLUME: "#22c55e",
  DEEP_LEARNING: "#ec4899",
  ML_ENSEMBLE: "#f97316",
  TIME_CYCLE: "#eab308",
  CAUSALITY: "#ef4444",
  GLOBAL_CAUSALITY: "#ef4444",
  REGIME: "#6366f1",
  VOLATILITY: "#f59e0b",
  RELATIONSHIP: "#14b8a6",
  FUNDAMENTAL: "#10b981",
  MACRO: "#0ea5e9",
  SENTIMENT: "#f43f5e",
  POLICY: "#8b5cf6",
  SCREENING: "#84cc16",
  META: "#d946ef",
  META_LEARNING: "#d946ef",
  SELF_HEALING: "#f97316",
  ORCHESTRATION: "#6b7280",
};

const CHART_COLORS = [
  "#a855f7", "#3b82f6", "#06b6d4", "#22c55e", "#ec4899",
  "#f97316", "#eab308", "#ef4444", "#6366f1", "#f59e0b",
  "#14b8a6", "#10b981", "#0ea5e9", "#f43f5e", "#8b5cf6",
];

const LOG_RING_MAX = 200;

// ── Dynamic Weight Chart (Canvas 2D, rAF throttled) ──────────────────────

function DynamicWeightChart({
  engines,
  history,
  running,
}: {
  engines: EngineEntry[];
  history: WeightHistoryPoint[];
  running: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef(0);
  const historyRef = useRef<WeightHistoryPoint[]>(history);
  const enginesRef = useRef<EngineEntry[]>(engines);

  // Keep refs in sync
  useEffect(() => { historyRef.current = history; }, [history]);
  useEffect(() => { enginesRef.current = engines; }, [engines]);

  // Top engines by weight for chart display
  const chartEngines = useMemo(() => {
    return [...engines]
      .filter((e) => e.is_active && e.weight_percentage > 0)
      .sort((a, b) => b.weight_percentage - a.weight_percentage)
      .slice(0, 10);
  }, [engines]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);

      const W = rect.width;
      const H = rect.height;
      const padding = { top: 20, right: 120, bottom: 30, left: 40 };
      const chartW = W - padding.left - padding.right;
      const chartH = H - padding.top - padding.bottom;

      // Background
      ctx.fillStyle = "rgba(0,0,0,0.3)";
      ctx.fillRect(0, 0, W, H);

      // Grid
      ctx.strokeStyle = "rgba(255,255,255,0.05)";
      ctx.lineWidth = 1;
      for (let i = 0; i <= 5; i++) {
        const y = padding.top + (chartH / 5) * i;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(padding.left + chartW, y);
        ctx.stroke();
      }
      for (let i = 0; i <= 10; i++) {
        const x = padding.left + (chartW / 10) * i;
        ctx.beginPath();
        ctx.moveTo(x, padding.top);
        ctx.lineTo(x, padding.top + chartH);
        ctx.stroke();
      }

      // Y-axis labels (weight %)
      ctx.fillStyle = "rgba(255,255,255,0.4)";
      ctx.font = "10px monospace";
      ctx.textAlign = "right";
      for (let i = 0; i <= 5; i++) {
        const val = 50 - i * 10;
        const y = padding.top + (chartH / 5) * i;
        ctx.fillText(`${val}%`, padding.left - 5, y + 3);
      }

      // X-axis label
      ctx.textAlign = "center";
      ctx.fillText("Siklus Tuning →", padding.left + chartW / 2, H - 5);

      const hist = historyRef.current;
      const engs = chartEngines;

      if (hist.length < 2 || engs.length === 0) {
        ctx.fillStyle = "rgba(255,255,255,0.3)";
        ctx.font = "12px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("Menunggu data simulasi...", W / 2, H / 2);
        return;
      }

      const maxTick = Math.max(...hist.map((h) => h.tick), 1);
      const maxWeight = 55;

      // Draw lines for each engine
      engs.forEach((eng, idx) => {
        const color = CHART_COLORS[idx % CHART_COLORS.length];
        ctx.strokeStyle = color;
        ctx.lineWidth = eng.weight_percentage > 20 ? 2.5 : 1.5;
        ctx.beginPath();

        hist.forEach((point, i) => {
          const x = padding.left + (i / Math.max(hist.length - 1, 1)) * chartW;
          const w = point.weights[eng.engine_name] ?? 0;
          const y = padding.top + chartH - (w / maxWeight) * chartH;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });

        ctx.stroke();

        // Draw last point dot
        const lastPoint = hist[hist.length - 1];
        const lastW = lastPoint.weights[eng.engine_name] ?? 0;
        const lastX = padding.left + chartW;
        const lastY = padding.top + chartH - (lastW / maxWeight) * chartH;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(lastX, lastY, 3, 0, Math.PI * 2);
        ctx.fill();
      });

      // Legend (right side)
      ctx.font = "10px monospace";
      ctx.textAlign = "left";
      engs.forEach((eng, idx) => {
        const color = CHART_COLORS[idx % CHART_COLORS.length];
        const y = padding.top + idx * 14 + 5;
        const w = hist[hist.length - 1].weights[eng.engine_name] ?? 0;
        ctx.fillStyle = color;
        ctx.fillRect(padding.left + chartW + 5, y - 7, 8, 8);
        ctx.fillStyle = "rgba(255,255,255,0.7)";
        const name = eng.engine_name.length > 15 ? eng.engine_name.slice(0, 13) + ".." : eng.engine_name;
        ctx.fillText(`${name} ${w.toFixed(1)}%`, padding.left + chartW + 18, y);
      });
    };

    const loop = () => {
      draw();
      rafRef.current = requestAnimationFrame(loop);
    };

    rafRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafRef.current);
  }, [chartEngines]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full"
      style={{ minHeight: 280 }}
    />
  );
}

// ── Engine Toggle Card ───────────────────────────────────────────────────

function EngineCard({
  engine,
  onToggle,
}: {
  engine: EngineEntry;
  onToggle: (name: string, active: boolean) => void;
}) {
  const color = TYPE_COLORS[engine.engine_type] || "#6b7280";

  return (
    <div
      className={cn(
        "rounded-lg border p-2 transition-all duration-200",
        engine.is_active
          ? "border-emerald-500/30 bg-emerald-500/5 hover:border-emerald-500/50"
          : "border-red-500/30 bg-red-500/5 opacity-60 hover:opacity-80"
      )}
    >
      <div className="flex items-center justify-between gap-1">
        <span
          className="text-[10px] font-mono font-medium truncate flex-1"
          style={{ color }}
          title={engine.engine_name}
        >
          {engine.engine_name}
        </span>
        <button
          onClick={() => onToggle(engine.engine_name, !engine.is_active)}
          className={cn(
            "relative w-7 h-3.5 rounded-full transition-colors flex-shrink-0",
            engine.is_active ? "bg-emerald-500" : "bg-red-500/50"
          )}
          title={engine.is_active ? "Klik untuk nonaktifkan" : "Klik untuk aktifkan"}
        >
          <span
            className={cn(
              "absolute top-0.5 w-2.5 h-2.5 rounded-full bg-white transition-transform",
              engine.is_active ? "translate-x-3.5" : "translate-x-0.5"
            )}
          />
        </button>
      </div>
      <div className="flex items-center justify-between mt-1 text-[9px] text-muted-foreground">
        <span>{engine.engine_type}</span>
        <span className="tabular-nums">
          {engine.accuracy_score > 0 ? `DA: ${engine.accuracy_score.toFixed(0)}%` : "DA: —"}
        </span>
      </div>
      <div className="mt-0.5">
        <div className="flex items-center justify-between text-[9px] text-muted-foreground">
          <span>Bobot</span>
          <span className="tabular-nums font-medium" style={{ color: engine.is_active ? color : undefined }}>
            {engine.weight_percentage.toFixed(1)}%
          </span>
        </div>
        <div className="h-1 bg-muted rounded-full overflow-hidden mt-0.5">
          <div
            className="h-full rounded-full transition-all duration-300"
            style={{
              width: `${Math.min(engine.weight_percentage / 50 * 100, 100)}%`,
              backgroundColor: color,
              opacity: engine.is_active ? 1 : 0.3,
            }}
          />
        </div>
      </div>
    </div>
  );
}

// ── Terminal Log Component ───────────────────────────────────────────────

function TerminalLog({
  logs,
  paused,
  onTogglePause,
  onClear,
}: {
  logs: string[];
  paused: boolean;
  onTogglePause: () => void;
  onClear: () => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!paused && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs, paused]);

  const logColor = (line: string) => {
    if (line.includes("Mematikan")) return "text-red-400";
    if (line.includes("Mengaktifkan")) return "text-emerald-400";
    if (line.includes("Selesai")) return "text-emerald-400";
    if (line.includes("Error") || line.includes("error")) return "text-red-400";
    if (line.includes("Memulai")) return "text-yellow-400";
    if (line.includes("Hari")) return "text-cyan-400";
    return "text-muted-foreground";
  };

  return (
    <div className="rounded-md border border-border bg-black/40 overflow-hidden h-full flex flex-col">
      <div className="px-3 py-1.5 border-b border-border/50 text-xs font-semibold text-muted-foreground flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-1.5">
          <Terminal className="w-3.5 h-3.5" />
          Terminal Log Orkestrasi
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onTogglePause}
            className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
            title={paused ? "Lanjutkan" : "Jeda"}
          >
            {paused ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
          </button>
          <button
            onClick={onClear}
            className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
            title="Bersihkan"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      </div>
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed space-y-0.5 min-h-0"
      >
        {logs.length === 0 ? (
          <div className="text-muted-foreground/50 italic">
            $ menunggu aktivitas orkestrasi engine...
            <br />
            $ klik "Tuning Ensemble" untuk memulai simulasi hybrid
          </div>
        ) : (
          logs.map((line, i) => (
            <div key={i} className={logColor(line)}>
              <span className="text-muted-foreground/40">
                {new Date().toLocaleTimeString("id-ID", { hour12: false })}
              </span>{" "}
              {line}
            </div>
          ))
        )}
        {!paused && logs.length > 0 && (
          <div className="text-emerald-400 animate-pulse">▌</div>
        )}
      </div>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────

export default function ManajemenEnginePage() {
  const [engines, setEngines] = useState<EngineEntry[]>([]);
  const [progress, setProgress] = useState<EnsembleProgress | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [weightHistory, setWeightHistory] = useState<WeightHistoryPoint[]>([]);
  const [paused, setPaused] = useState(false);
  const [loading, setLoading] = useState(true);
  const prevLogLen = useRef(0);
  const tickRef = useRef(0);
  const pausedRef = useRef(false);

  useEffect(() => { pausedRef.current = paused; }, [paused]);

  const fetchEngines = useCallback(async () => {
    try {
      const res = await fetch("/api/engine-registry");
      if (res.ok) {
        const data = await res.json();
        if (data.engines) setEngines(data.engines);
      }
    } catch { /* ignore */ }
  }, []);

  const fetchProgress = useCallback(async () => {
    try {
      const res = await fetch("/api/ensemble-tuning/progress");
      if (res.ok) {
        const data = await res.json();
        setProgress(data);

        // Append new log lines
        if (data.orchestration_log && data.orchestration_log.length > prevLogLen.current) {
          const newLines = data.orchestration_log.slice(prevLogLen.current);
          setLogLines((prev) => [...prev, ...newLines].slice(-LOG_RING_MAX));
          prevLogLen.current = data.orchestration_log.length;
        }

        // Record weight history snapshot
        if (data.running || data.done) {
          tickRef.current += 1;
          const snapshot: Record<string, number> = {};
          if (data.active_engines) {
            for (const eng of data.active_engines) {
              snapshot[eng.engine_name] = eng.weight_percentage;
            }
          }
          setWeightHistory((prev) => [...prev, { tick: tickRef.current, weights: snapshot }].slice(-100));
        }
      }
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    fetchEngines().then(() => setLoading(false));
    fetchProgress();
    const id = setInterval(() => {
      fetchEngines();
      if (!pausedRef.current) fetchProgress();
    }, 2000);
    return () => clearInterval(id);
  }, [fetchEngines, fetchProgress]);

  const handleToggle = useCallback(async (name: string, active: boolean) => {
    setEngines((prev) =>
      prev.map((e) => e.engine_name === name ? { ...e, is_active: active } : e)
    );
    try {
      await fetch("/api/engine-registry/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ engine_name: name, is_active: active }),
      });
    } catch { /* ignore */ }
  }, []);

  const startTuning = useCallback(async () => {
    try {
      await fetch("/api/ensemble-tuning/run", { method: "POST" });
      setLogLines([]);
      setWeightHistory([]);
      prevLogLen.current = 0;
      tickRef.current = 0;
      fetchProgress();
    } catch { /* ignore */ }
  }, [fetchProgress]);

  const running = progress?.running ?? false;
  const done = progress?.done ?? false;
  const activeCount = engines.filter((e) => e.is_active).length;
  const inactiveCount = engines.length - activeCount;
  const pct = progress && progress.total_trading_days > 0
    ? (progress.current_day / progress.total_trading_days) * 100
    : 0;

  // Group engines by type
  const engineGroups = useMemo(() => {
    const groups: Record<string, EngineEntry[]> = {};
    for (const e of engines) {
      if (!groups[e.engine_type]) groups[e.engine_type] = [];
      groups[e.engine_type].push(e);
    }
    return groups;
  }, [engines]);

  return (
    <div className="min-h-screen bg-background p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Cpu className="w-5 h-5 text-purple-400" />
            <h1 className="text-lg font-bold">Manajemen Engine & Log Orkestrasi</h1>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400">
              {activeCount} aktif
            </span>
            <span className="px-2 py-0.5 rounded bg-red-500/10 text-red-400">
              {inactiveCount} nonaktif
            </span>
            <span className="text-muted-foreground/60">
              {engines.length} total engine
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { fetchEngines(); fetchProgress(); }}
            className="px-3 py-1.5 rounded-md border border-border text-xs hover:bg-accent flex items-center gap-1"
          >
            <RefreshCw className="w-3 h-3" />
            Segarkan
          </button>
          <button
            onClick={startTuning}
            disabled={running}
            className="px-4 py-1.5 rounded-md bg-purple-600 text-white text-xs font-medium hover:bg-purple-700 disabled:opacity-50 flex items-center gap-1.5"
          >
            {running ? <Activity className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />}
            {running ? "Menyimulasikan..." : "Tuning Ensemble"}
          </button>
        </div>
      </div>

      {/* Progress bar */}
      {(running || done) && progress && progress.total_trading_days > 0 && (
        <div className="space-y-1">
          <div className="w-full bg-muted rounded-full h-2.5 overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-purple-500 to-blue-500 transition-all duration-500 rounded-full"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="flex items-center justify-between text-[10px] text-muted-foreground">
            <span>
              Hari {progress.current_day}/{progress.total_trading_days}
              {progress.sim_date && ` | ${progress.sim_date}`}
            </span>
            <span>
              DA: {progress.directional_accuracy?.toFixed(1) ?? 0}%
              {" | "}
              Ekuitas: Rp {((progress.equity ?? 0) / 1_000_000).toFixed(2)}Jt
              {" | "}
              {progress.message}
            </span>
          </div>
        </div>
      )}

      {/* Bento Grid: 3 panels */}
      <div className="grid grid-cols-12 gap-4">
        {/* Panel 1: Engine Registry Grid (5 cols) */}
        <div className="col-span-12 lg:col-span-5 rounded-xl border border-border bg-card/50 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Power className="w-4 h-4 text-emerald-400" />
            <h2 className="text-sm font-semibold">Engine Registry Grid</h2>
            <span className="text-[10px] text-muted-foreground ml-auto">
              Klik sakelar untuk aktif/nonaktif
            </span>
          </div>
          {loading ? (
            <div className="text-muted-foreground text-sm py-8 text-center">
              Memuat data engine dari database...
            </div>
          ) : (
            <div className="space-y-3 max-h-[500px] overflow-y-auto pr-1">
              {Object.entries(engineGroups).map(([type, engs]) => (
                <div key={type}>
                  <div className="text-[10px] font-semibold text-muted-foreground/70 mb-1.5 uppercase tracking-wider">
                    {type} ({engs.length})
                  </div>
                  <div className="grid grid-cols-3 gap-1.5">
                    {engs.map((e) => (
                      <EngineCard key={e.engine_name} engine={e} onToggle={handleToggle} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Panel 2: Dynamic Weight Chart (7 cols) */}
        <div className="col-span-12 lg:col-span-7 rounded-xl border border-border bg-card/50 p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className="w-4 h-4 text-blue-400" />
            <h2 className="text-sm font-semibold">Grafik Bobot Engine Hybrid (Time-Series)</h2>
            <span className="text-[10px] text-muted-foreground ml-auto">
              Canvas 2D · rAF · &gt;55 FPS
            </span>
          </div>
          <div className="w-full" style={{ height: 320 }}>
            <DynamicWeightChart engines={engines} history={weightHistory} running={running} />
          </div>
          {/* Summary stats */}
          <div className="grid grid-cols-4 gap-2 mt-3">
            <div className="rounded-md border border-border/50 p-2 text-center">
              <div className="text-[10px] text-muted-foreground">Engine Aktif</div>
              <div className="text-lg font-bold text-emerald-400">{activeCount}</div>
            </div>
            <div className="rounded-md border border-border/50 p-2 text-center">
              <div className="text-[10px] text-muted-foreground">Engine Nonaktif</div>
              <div className="text-lg font-bold text-red-400">{inactiveCount}</div>
            </div>
            <div className="rounded-md border border-border/50 p-2 text-center">
              <div className="text-[10px] text-muted-foreground">DA Tertinggi</div>
              <div className="text-lg font-bold text-purple-400">
                {engines.length > 0 ? Math.max(...engines.map((e) => e.accuracy_score)).toFixed(1) : 0}%
              </div>
            </div>
            <div className="rounded-md border border-border/50 p-2 text-center">
              <div className="text-[10px] text-muted-foreground">Total Bobot</div>
              <div className="text-lg font-bold text-blue-400">
                {engines.reduce((s, e) => s + e.weight_percentage, 0).toFixed(0)}%
              </div>
            </div>
          </div>
        </div>

        {/* Panel 3: Terminal Log (full width) */}
        <div className="col-span-12 rounded-xl border border-border bg-card/50 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Terminal className="w-4 h-4 text-emerald-400" />
            <h2 className="text-sm font-semibold">Terminal Log Jalur Browser</h2>
            <span className="text-[10px] text-muted-foreground ml-auto">
              {logLines.length} entri · auto-scroll
            </span>
          </div>
          <div style={{ height: 240 }}>
            <TerminalLog
              logs={logLines}
              paused={paused}
              onTogglePause={() => setPaused((p) => !p)}
              onClear={() => setLogLines([])}
            />
          </div>
        </div>
      </div>

      {/* Done banner */}
      {done && progress && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm">
          <span className="text-emerald-400 font-medium">
            ✅ Simulasi Ensemble Selesai: {progress.message}
          </span>
          <span className="text-muted-foreground ml-4">
            DA: {progress.directional_accuracy?.toFixed(1)}% · Prediksi: {progress.n_predictions}
          </span>
        </div>
      )}
    </div>
  );
}
