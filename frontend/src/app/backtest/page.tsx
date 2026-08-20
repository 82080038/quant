"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Bot,
  Activity,
  TrendingUp,
  TrendingDown,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  Zap,
  RefreshCw,
  AlertTriangle,
  CalendarDays,
  Gauge,
  ShieldCheck,
} from "lucide-react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface InstrumentResult {
  ticker: string;
  strategy: string;
  status: string;
  metrics: Record<string, number>;
  trade_count: number;
  error: string;
  walk_forward?: {
    oos_sharpe: number;
    oos_return_pct: number;
    consistency_pct: number;
  };
  monte_carlo?: {
    percentiles: Record<string, number>;
    prob_loss_pct: number;
    max_drawdown_pct: number;
  };
}

interface AgentAction {
  cycle_id: string;
  action: string;
  description: string;
  confidence: number;
  requires_human: boolean;
  status: string;
}

interface BacktestRun {
  run_id: string;
  trigger: string;
  status: string;
  triggered_at: string;
  completed_at: string;
  total_instruments: number;
  total_strategies: number;
  successful: number;
  failed: number;
  skipped: number;
  best_sharpe: number;
  worst_sharpe: number;
  avg_sharpe: number;
  best_strategy: string;
  worst_strategy: string;
  instruments_tested: string[];
  agent_actions_proposed: AgentAction[];
  summary: string;
  duration_seconds: number;
  instrument_results: InstrumentResult[];
}

interface TemporalReport {
  start_date: string;
  end_date: string;
  total_days: number;
  trading_days: number;
  skipped_holidays: number;
  total_trades: number;
  buy_trades: number;
  sell_trades: number;
  equity_trades: number;
  cross_asset_trades: number;
  final_equity: number;
  total_return_pct: number;
  annual_return_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  best_day_pct: number;
  worst_day_pct: number;
  avg_daily_return_pct: number;
  volatility_pct: number;
  calmar_ratio: number;
  equity_curve: { date: string; equity: number }[];
  trades: { sim_date: string; ticker: string; side: string; shares: number; price: number; cost: number; asset_class: string; pnl: number }[];
  daily_results: { sim_date: string; equity: number; cash: number; n_positions: number; n_trades: number; regime: string; active_cycles: number; lookahead_check: boolean }[];
  lookahead_violations: number;
  asset_class_breakdown: { equity_trades: number; cross_asset_trades: number; equity_pct: number; cross_asset_pct: number };
}

interface RunnerStatus {
  total_runs: number;
  latest_run: string | null;
  latest_trigger: string | null;
  latest_status: string | null;
  latest_avg_sharpe: number;
  latest_best_strategy: string;
  latest_instruments: number;
  latest_agent_actions: number;
  latest_duration_s: number;
  latest_summary: string;
}

const TRIGGER_LABELS: Record<string, { label: string; icon: typeof Clock; color: string }> = {
  scheduled_eod: { label: "Terjadwal EOD", icon: Clock, color: "text-blue-400" },
  data_change: { label: "Perubahan Data", icon: Activity, color: "text-green-400" },
  market_event: { label: "Event Pasar Global", icon: Zap, color: "text-yellow-400" },
  user_activity: { label: "Aktivitas User", icon: Bot, color: "text-purple-400" },
  drift_detected: { label: "Drift Terdeteksi", icon: AlertTriangle, color: "text-orange-400" },
  manual_force: { label: "Force Manual", icon: RefreshCw, color: "text-red-400" },
};

const REGIME_COLORS: Record<string, string> = {
  bull: "text-emerald-400",
  bear: "text-red-400",
  sideways: "text-yellow-400",
  crisis: "text-orange-400",
  unknown: "text-muted-foreground",
};

interface SimProgress {
  running: boolean;
  current_day: number;
  total_trading_days: number;
  sim_date: string | null;
  equity: number;
  cash: number;
  n_positions: number;
  n_trades_today: number;
  regime: string;
  active_cycles: number;
  lookahead_violations: number;
  errors_intercepted: number;
  hot_patches: number;
  day_log: { sim_date: string; equity: number; cash: number; n_positions: number; n_trades: number; regime: string; active_cycles: number; lookahead_check: boolean; had_error: boolean }[];
  error_log: { sim_date: string; stage: string; error_type: string; error_msg: string; severity: string }[];
  patch_log: { bug_id: string; sim_day: string; severity: string; file_modified: string; fix_description: string }[];
  done: boolean;
  message: string;
}

export default function BacktestPage() {
  const [status, setStatus] = useState<RunnerStatus | null>(null);
  const [latest, setLatest] = useState<BacktestRun | null>(null);
  const [temporal, setTemporal] = useState<TemporalReport | null>(null);
  const [simProgress, setSimProgress] = useState<SimProgress | null>(null);
  const [simRunning, setSimRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/autonomous-backtest/status");
      if (!res.ok) throw new Error("Gagal memuat status");
      setStatus(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    }
  }, []);

  const fetchLatest = useCallback(async () => {
    try {
      const res = await fetch("/api/autonomous-backtest/latest");
      if (!res.ok) throw new Error("Gagal memuat data backtest");
      const data = await res.json();
      setLatest(data.status === "idle" ? null : data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchTemporal = useCallback(async () => {
    try {
      const res = await fetch("/api/temporal-backtest/report");
      if (!res.ok) return;
      const data = await res.json();
      if (data.status !== "not_found") setTemporal(data as TemporalReport);
    } catch {
      // silent — temporal report is optional
    }
  }, []);

  const fetchSimProgress = useCallback(async () => {
    try {
      const res = await fetch("/api/temporal-backtest/progress");
      if (!res.ok) return;
      const data = await res.json() as SimProgress;
      setSimProgress(data);
      setSimRunning(data.running);
      if (data.done) {
        // Reload the full report
        void fetchTemporal();
      }
    } catch {
      // silent
    }
  }, [fetchTemporal]);

  const startSimulation = useCallback(async () => {
    try {
      setSimRunning(true);
      const res = await fetch("/api/temporal-backtest/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start: "2025-08-20", end: "2026-08-18", universe_size: 15 }),
      });
      if (!res.ok) throw new Error("Failed to start simulation");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      setSimRunning(false);
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
    void fetchLatest();
    void fetchTemporal();
    void fetchSimProgress();
  }, [fetchStatus, fetchLatest, fetchTemporal, fetchSimProgress]);

  // Poll progress every 2s while simulation is running
  useEffect(() => {
    if (!simRunning) return;
    const interval = setInterval(() => void fetchSimProgress(), 2000);
    return () => clearInterval(interval);
  }, [simRunning, fetchSimProgress]);

  const triggerRun = async () => {
    setTriggering(true);
    setError(null);
    try {
      await fetch("/api/autonomous-backtest/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trigger: "manual_force" }),
      });
      await fetchStatus();
      await fetchLatest();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setTriggering(false);
    }
  };

  const equityChartData = useMemo(() => {
    if (!temporal) return [];
    return temporal.equity_curve.map((d) => ({ ...d, equity: d.equity / 1_000_000 }));
  }, [temporal]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const triggerInfo = latest
    ? TRIGGER_LABELS[latest.trigger] || TRIGGER_LABELS.manual_force
    : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Bot className="w-6 h-6 text-primary" />
          Backtest Otonom
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          Backtest berjalan otomatis oleh AI Self-Evolution & Autonomous Layer.
          Tidak ada campur tangan user — sistem menguji seluruh instrumen,
          strategi, dan merespons perubahan data/event pasar secara mandiri.
        </p>
      </div>

      {/* ── Live Simulation Control Panel ── */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Zap className="w-4 h-4 text-yellow-400" />
            1-Year Temporal Simulation Control
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {/* Run button + status */}
            <div className="flex items-center gap-4 flex-wrap">
              <button
                onClick={startSimulation}
                disabled={simRunning}
                className="px-6 py-2 rounded-md bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-50 flex items-center gap-2"
              >
                {simRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                {simRunning ? "Simulating..." : "Run 1-Year Simulation"}
              </button>
              {simProgress?.done && (
                <span className="flex items-center gap-1 text-sm text-emerald-400 font-medium">
                  <CheckCircle2 className="w-4 h-4" /> Simulation Complete
                </span>
              )}
              {simProgress && !simProgress.done && !simProgress.running && (
                <span className="flex items-center gap-1 text-sm text-muted-foreground">
                  {simProgress.message}
                </span>
              )}
            </div>

            {/* Progress bar */}
            {simProgress && (simProgress.running || simProgress.done) && (
              <>
                <div className="w-full bg-muted rounded-full h-3 overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 transition-all duration-500 rounded-full"
                    style={{
                      width: `${simProgress.total_trading_days > 0
                        ? (simProgress.current_day / simProgress.total_trading_days) * 100
                        : 0}%`,
                    }}
                  />
                </div>
                <p className="text-xs text-muted-foreground text-center">
                  Day {simProgress.current_day} / {simProgress.total_trading_days} trading days
                  {simProgress.sim_date && ` | ${simProgress.sim_date}`}
                </p>
              </>
            )}

            {/* Live metrics grid */}
            {simProgress && simProgress.running && (
              <div className="grid grid-cols-3 md:grid-cols-6 gap-3 text-sm">
                <div className="rounded-md border border-border p-2">
                  <p className="text-xs text-muted-foreground">Equity</p>
                  <p className="font-bold font-mono">{(simProgress.equity / 1_000_000).toFixed(2)}M</p>
                </div>
                <div className="rounded-md border border-border p-2">
                  <p className="text-xs text-muted-foreground">Cash</p>
                  <p className="font-bold font-mono text-muted-foreground">{(simProgress.cash / 1_000_000).toFixed(1)}M</p>
                </div>
                <div className="rounded-md border border-border p-2">
                  <p className="text-xs text-muted-foreground">Positions</p>
                  <p className="font-bold">{simProgress.n_positions}</p>
                </div>
                <div className="rounded-md border border-border p-2">
                  <p className="text-xs text-muted-foreground">Regime</p>
                  <p className={`font-bold ${REGIME_COLORS[simProgress.regime] || "text-muted-foreground"}`}>{simProgress.regime}</p>
                </div>
                <div className="rounded-md border border-border p-2">
                  <p className="text-xs text-muted-foreground">Look-ahead</p>
                  <p className="font-bold text-emerald-400">{simProgress.lookahead_violations}</p>
                </div>
                <div className="rounded-md border border-border p-2">
                  <p className="text-xs text-muted-foreground">Errors</p>
                  <p className={`font-bold ${simProgress.errors_intercepted > 0 ? "text-red-400" : "text-emerald-400"}`}>{simProgress.errors_intercepted}</p>
                </div>
              </div>
            )}

            {/* Live day log (last 10 days) */}
            {simProgress && simProgress.day_log && simProgress.day_log.length > 0 && (
              <div className="max-h-40 overflow-y-auto rounded-md border border-border">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-card">
                    <tr className="border-b border-border text-left">
                      <th className="px-2 py-1">Date</th>
                      <th className="px-2 py-1 text-right">Equity</th>
                      <th className="px-2 py-1 text-center">Pos</th>
                      <th className="px-2 py-1 text-center">Trades</th>
                      <th className="px-2 py-1">Regime</th>
                      <th className="px-2 py-1 text-center">PIT</th>
                      <th className="px-2 py-1 text-center">Err</th>
                    </tr>
                  </thead>
                  <tbody>
                    {simProgress.day_log.slice(-10).reverse().map((d, i) => (
                      <tr key={i} className="border-b border-border/30">
                        <td className="px-2 py-1 font-mono">{d.sim_date}</td>
                        <td className="px-2 py-1 text-right font-mono">{(d.equity / 1_000_000).toFixed(2)}M</td>
                        <td className="px-2 py-1 text-center">{d.n_positions}</td>
                        <td className="px-2 py-1 text-center">{d.n_trades}</td>
                        <td className={`px-2 py-1 ${REGIME_COLORS[d.regime] || "text-muted-foreground"}`}>{d.regime}</td>
                        <td className="px-2 py-1 text-center">{d.lookahead_check ? "✓" : "✗"}</td>
                        <td className="px-2 py-1 text-center">{d.had_error ? "⚠" : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Intercepted errors */}
            {simProgress && simProgress.error_log && simProgress.error_log.length > 0 && (
              <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3">
                <p className="text-xs font-medium text-red-400 mb-2 flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" /> Intercepted Errors ({simProgress.error_log.length})
                </p>
                <div className="space-y-1 max-h-32 overflow-y-auto">
                  {simProgress.error_log.map((e, i) => (
                    <div key={i} className="text-xs font-mono">
                      <span className="text-red-400">[{e.severity.toUpperCase()}]</span>{" "}
                      <span className="text-muted-foreground">{e.sim_date}</span>{" "}
                      <span className="text-yellow-400">{e.stage}:</span>{" "}
                      <span>{e.error_type}: {e.error_msg}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Hot-patch log */}
            {simProgress && simProgress.patch_log && simProgress.patch_log.length > 0 && (
              <div className="rounded-md border border-yellow-500/30 bg-yellow-500/5 p-3">
                <p className="text-xs font-medium text-yellow-400 mb-2">🔧 Live Hot-Patches ({simProgress.patch_log.length})</p>
                <div className="space-y-1">
                  {simProgress.patch_log.map((p, i) => (
                    <div key={i} className="text-xs">
                      <span className="font-mono text-yellow-400">#{p.bug_id}</span>{" "}
                      <span className="text-muted-foreground">Day {p.sim_day}</span>{" "}
                      <span>{p.fix_description}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* ── Temporal Simulation Results ── */}
      {temporal && (
        <>
          <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-4">
            <div className="flex items-start gap-3">
              <CalendarDays className="w-5 h-5 text-emerald-500 mt-0.5 flex-shrink-0" />
              <div className="text-sm space-y-1">
                <p className="font-medium text-emerald-600 dark:text-emerald-400">
                  1-Year Temporal Trading Simulation — Completed
                </p>
                <p className="text-muted-foreground">
                  Period: {temporal.start_date} → {temporal.end_date} |
                  {temporal.trading_days} trading days executed |
                  {temporal.skipped_holidays} holidays skipped |
                  Look-ahead violations: {temporal.lookahead_violations}
                </p>
              </div>
            </div>
          </div>

          {/* Temporal Metrics Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-xs flex items-center gap-1"><CalendarDays className="w-3 h-3" /> Trading Days</CardTitle></CardHeader>
              <CardContent><p className="text-xl font-bold">{temporal.trading_days}</p></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-xs flex items-center gap-1"><Activity className="w-3 h-3" /> Total Trades</CardTitle></CardHeader>
              <CardContent><p className="text-xl font-bold">{temporal.total_trades}</p></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-xs flex items-center gap-1"><TrendingUp className="w-3 h-3" /> Return</CardTitle></CardHeader>
              <CardContent><p className={`text-xl font-bold ${temporal.total_return_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>{temporal.total_return_pct > 0 ? "+" : ""}{temporal.total_return_pct.toFixed(2)}%</p></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-xs flex items-center gap-1"><TrendingDown className="w-3 h-3" /> Max Drawdown</CardTitle></CardHeader>
              <CardContent><p className="text-xl font-bold text-red-400">{temporal.max_drawdown_pct.toFixed(2)}%</p></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-xs flex items-center gap-1"><Gauge className="w-3 h-3" /> Sharpe</CardTitle></CardHeader>
              <CardContent><p className="text-xl font-bold">{temporal.sharpe_ratio.toFixed(3)}</p></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-xs flex items-center gap-1"><ShieldCheck className="w-3 h-3" /> Look-ahead</CardTitle></CardHeader>
              <CardContent><p className="text-xl font-bold text-emerald-400">{temporal.lookahead_violations} violations</p></CardContent>
            </Card>
          </div>

          {/* Equity Curve Chart */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-sm">
                <Activity className="w-4 h-4 text-emerald-400" />
                Equity Curve — {temporal.trading_days} Trading Days
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={equityChartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                    <defs>
                      <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#22c55e" stopOpacity={0.4} />
                        <stop offset="100%" stopColor="#22c55e" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis
                      dataKey="date"
                      tick={{ fill: "#64748b", fontSize: 9 }}
                      axisLine={false}
                      tickLine={false}
                      interval={Math.max(1, Math.floor(equityChartData.length / 8))}
                      tickFormatter={(v: string) => v.slice(5)}
                    />
                    <YAxis
                      tick={{ fill: "#64748b", fontSize: 9 }}
                      axisLine={false}
                      tickLine={false}
                      width={48}
                      tickFormatter={(v: number) => `${v.toFixed(1)}M`}
                    />
                    <Tooltip
                      contentStyle={{ background: "rgba(10,14,26,0.9)", border: "1px solid hsl(217 33% 25%)", borderRadius: 6, fontSize: 11 }}
                      labelFormatter={(v: string) => v}
                      formatter={(v: number) => [`Rp ${(v * 1_000_000).toLocaleString("en-US", { maximumFractionDigits: 0 })}`, "Equity"]}
                    />
                    <Area type="monotone" dataKey="equity" stroke="#22c55e" strokeWidth={1.5} fill="url(#equityFill)" isAnimationActive={false} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          {/* Detailed Metrics Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <Card><CardContent className="p-3"><p className="text-xs text-muted-foreground">Final Equity</p><p className="font-bold">Rp {temporal.final_equity.toLocaleString("en-US", { maximumFractionDigits: 0 })}</p></CardContent></Card>
            <Card><CardContent className="p-3"><p className="text-xs text-muted-foreground">Annual Return</p><p className={`font-bold ${temporal.annual_return_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>{temporal.annual_return_pct > 0 ? "+" : ""}{temporal.annual_return_pct.toFixed(2)}%</p></CardContent></Card>
            <Card><CardContent className="p-3"><p className="text-xs text-muted-foreground">Sortino Ratio</p><p className="font-bold">{temporal.sortino_ratio.toFixed(3)}</p></CardContent></Card>
            <Card><CardContent className="p-3"><p className="text-xs text-muted-foreground">Calmar Ratio</p><p className="font-bold">{temporal.calmar_ratio.toFixed(3)}</p></CardContent></Card>
            <Card><CardContent className="p-3"><p className="text-xs text-muted-foreground">Win Rate</p><p className="font-bold">{temporal.win_rate_pct.toFixed(1)}%</p></CardContent></Card>
            <Card><CardContent className="p-3"><p className="text-xs text-muted-foreground">Volatility (ann)</p><p className="font-bold">{temporal.volatility_pct.toFixed(2)}%</p></CardContent></Card>
            <Card><CardContent className="p-3"><p className="text-xs text-muted-foreground">Buy / Sell</p><p className="font-bold">{temporal.buy_trades} / {temporal.sell_trades}</p></CardContent></Card>
            <Card><CardContent className="p-3"><p className="text-xs text-muted-foreground">Equity / Cross-Asset</p><p className="font-bold">{temporal.equity_trades} / {temporal.cross_asset_trades}</p></CardContent></Card>
          </div>

          {/* Daily Results Table */}
          <Card>
            <CardHeader><CardTitle className="text-sm">Daily Simulation Log — {temporal.daily_results.length} days</CardTitle></CardHeader>
            <CardContent>
              <div className="overflow-x-auto max-h-80 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-card">
                    <tr className="border-b border-border text-left">
                      <th className="pb-1 pr-3">Date</th>
                      <th className="pb-1 pr-3 text-right">Equity</th>
                      <th className="pb-1 pr-3 text-right">Cash</th>
                      <th className="pb-1 pr-3 text-center">Pos</th>
                      <th className="pb-1 pr-3 text-center">Trades</th>
                      <th className="pb-1 pr-3">Regime</th>
                      <th className="pb-1 pr-3 text-center">Cycles</th>
                      <th className="pb-1 pr-3 text-center">PIT</th>
                    </tr>
                  </thead>
                  <tbody>
                    {temporal.daily_results.map((d, i) => (
                      <tr key={i} className="border-b border-border/30 hover:bg-muted/30">
                        <td className="py-1 pr-3 font-mono">{d.sim_date}</td>
                        <td className="py-1 pr-3 text-right font-mono">{(d.equity / 1_000_000).toFixed(2)}M</td>
                        <td className="py-1 pr-3 text-right font-mono text-muted-foreground">{(d.cash / 1_000_000).toFixed(1)}M</td>
                        <td className="py-1 pr-3 text-center">{d.n_positions}</td>
                        <td className="py-1 pr-3 text-center">{d.n_trades}</td>
                        <td className={`py-1 pr-3 ${REGIME_COLORS[d.regime] || "text-muted-foreground"}`}>{d.regime}</td>
                        <td className="py-1 pr-3 text-center">{d.active_cycles}</td>
                        <td className="py-1 pr-3 text-center">{d.lookahead_check ? "✓" : "✗"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {/* Recent Trades Table */}
          <Card>
            <CardHeader><CardTitle className="text-sm">Trade Log — {temporal.trades.length} trades</CardTitle></CardHeader>
            <CardContent>
              <div className="overflow-x-auto max-h-60 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-card">
                    <tr className="border-b border-border text-left">
                      <th className="pb-1 pr-3">Date</th>
                      <th className="pb-1 pr-3">Side</th>
                      <th className="pb-1 pr-3">Ticker</th>
                      <th className="pb-1 pr-3 text-right">Shares</th>
                      <th className="pb-1 pr-3 text-right">Price</th>
                      <th className="pb-1 pr-3 text-right">Cost</th>
                      <th className="pb-1 pr-3 text-right">PnL</th>
                      <th className="pb-1 pr-3">Class</th>
                    </tr>
                  </thead>
                  <tbody>
                    {temporal.trades.slice().reverse().slice(0, 100).map((t, i) => (
                      <tr key={i} className="border-b border-border/30 hover:bg-muted/30">
                        <td className="py-1 pr-3 font-mono">{t.sim_date}</td>
                        <td className={`py-1 pr-3 font-medium ${t.side === "buy" ? "text-emerald-400" : "text-red-400"}`}>{t.side.toUpperCase()}</td>
                        <td className="py-1 pr-3 font-mono font-semibold">{t.ticker}</td>
                        <td className="py-1 pr-3 text-right font-mono">{t.shares.toLocaleString("en-US", { maximumFractionDigits: 0 })}</td>
                        <td className="py-1 pr-3 text-right font-mono">{t.price.toFixed(2)}</td>
                        <td className="py-1 pr-3 text-right font-mono text-muted-foreground">{t.cost.toFixed(0)}</td>
                        <td className={`py-1 pr-3 text-right font-mono ${t.pnl > 0 ? "text-emerald-400" : t.pnl < 0 ? "text-red-400" : "text-muted-foreground"}`}>{t.pnl !== 0 ? t.pnl.toFixed(0) : "—"}</td>
                        <td className="py-1 pr-3 text-muted-foreground">{t.asset_class}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {/* Info Banner */}
      <div className="rounded-md border border-blue-500/30 bg-blue-500/5 p-4">
        <div className="flex items-start gap-3">
          <Bot className="w-5 h-5 text-blue-500 mt-0.5 flex-shrink-0" />
          <div className="text-sm space-y-1">
            <p className="font-medium text-blue-600 dark:text-blue-400">
              Sistem Otonom Aktif
            </p>
            <p className="text-muted-foreground">
              Backtest dijalankan otomatis pada: EOD (17:30 WIB), perubahan data,
              event pasar global, aktivitas user, dan deteksi drift model.
              Hasil dianalisis oleh Self-Evolution Agent untuk retrain/adjust/promote strategi.
            </p>
          </div>
        </div>
      </div>

      {/* Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
        <Card>
          <CardHeader><CardTitle className="text-sm">Total Runs</CardTitle></CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{status?.total_runs ?? 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">Avg Sharpe</CardTitle></CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{status?.latest_avg_sharpe?.toFixed(3) ?? "—"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">Best Strategy</CardTitle></CardHeader>
          <CardContent>
            <p className="text-2xl font-bold capitalize">{status?.latest_best_strategy || "—"}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">Instruments</CardTitle></CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{status?.latest_instruments ?? 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">Agent Actions</CardTitle></CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{status?.latest_agent_actions ?? 0}</p>
          </CardContent>
        </Card>
      </div>

      {/* Latest Run Details */}
      {latest && triggerInfo && (
        <>
          {/* Run Summary */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <triggerInfo.icon className={`w-4 h-4 ${triggerInfo.color}`} />
                Run Terbaru: {latest.run_id}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div className="flex items-center gap-4 flex-wrap text-sm">
                  <span className="flex items-center gap-1">
                    <span className="text-muted-foreground">Trigger:</span>
                    <span className={`font-medium ${triggerInfo.color}`}>{triggerInfo.label}</span>
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="text-muted-foreground">Status:</span>
                    {latest.status === "completed" ? (
                      <CheckCircle2 className="w-4 h-4 text-green-500" />
                    ) : latest.status === "failed" ? (
                      <XCircle className="w-4 h-4 text-red-500" />
                    ) : (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    )}
                    <span className="font-medium capitalize">{latest.status}</span>
                  </span>
                  <span className="text-muted-foreground">
                    Durasi: {latest.duration_seconds.toFixed(1)}s
                  </span>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-6 gap-3 text-sm">
                  <div>
                    <p className="text-muted-foreground text-xs">Instruments</p>
                    <p className="font-medium">{latest.total_instruments}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground text-xs">Strategies</p>
                    <p className="font-medium">{latest.total_strategies}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground text-xs">Successful</p>
                    <p className="font-medium text-green-500">{latest.successful}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground text-xs">Failed</p>
                    <p className="font-medium text-red-500">{latest.failed}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground text-xs">Best Sharpe</p>
                    <p className="font-medium text-green-500 flex items-center gap-1">
                      <TrendingUp className="w-3 h-3" />{latest.best_sharpe.toFixed(3)}
                    </p>
                  </div>
                  <div>
                    <p className="text-muted-foreground text-xs">Worst Sharpe</p>
                    <p className="font-medium text-red-500 flex items-center gap-1">
                      <TrendingDown className="w-3 h-3" />{latest.worst_sharpe.toFixed(3)}
                    </p>
                  </div>
                </div>

                <p className="text-xs text-muted-foreground">{latest.summary}</p>

                <div className="flex flex-wrap gap-2">
                  {latest.instruments_tested.map((t) => (
                    <span key={t} className="px-2 py-0.5 rounded text-xs bg-muted text-muted-foreground">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Agent Actions */}
          {latest.agent_actions_proposed.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Bot className="w-4 h-4 text-purple-500" />
                  Self-Evolution Agent Actions
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {latest.agent_actions_proposed.map((action, i) => (
                    <div key={i} className="rounded-md border border-border p-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                            action.action === "retrain_model" ? "bg-blue-500/20 text-blue-500" :
                            action.action === "adjust_params" ? "bg-yellow-500/20 text-yellow-500" :
                            action.action === "escalate_human" ? "bg-red-500/20 text-red-500" :
                            action.action === "no_action" ? "bg-muted text-muted-foreground" :
                            "bg-muted text-muted-foreground"
                          }`}>
                            {action.action.replace(/_/g, " ")}
                          </span>
                          {action.requires_human && (
                            <span className="text-xs text-yellow-500">⚠️ Perlu approval</span>
                          )}
                        </div>
                        <span className="text-xs text-muted-foreground">
                          confidence: {(action.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                      <p className="text-sm mt-1">{action.description}</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        Cycle: {action.cycle_id} | Status: {action.status}
                      </p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Instrument Results Table */}
          <Card>
            <CardHeader>
              <CardTitle>Hasil per Instrumen & Strategi</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left">
                      <th className="pb-2 pr-4">Ticker</th>
                      <th className="pb-2 pr-4">Strategi</th>
                      <th className="pb-2 pr-4">Status</th>
                      <th className="pb-2 pr-4 text-right">Sharpe</th>
                      <th className="pb-2 pr-4 text-right">Return %</th>
                      <th className="pb-2 pr-4 text-right">Max DD %</th>
                      <th className="pb-2 pr-4 text-right">Trades</th>
                      <th className="pb-2 pr-4 text-right">WF Consistency</th>
                      <th className="pb-2 pr-4 text-right">MC Prob Loss</th>
                    </tr>
                  </thead>
                  <tbody>
                    {latest.instrument_results.map((r, i) => (
                      <tr key={i} className="border-b border-border/50">
                        <td className="py-2 pr-4 font-medium">{r.ticker}</td>
                        <td className="py-2 pr-4 capitalize">{r.strategy.replace(/_/g, " ")}</td>
                        <td className="py-2 pr-4">
                          {r.status === "completed" ? (
                            <CheckCircle2 className="w-4 h-4 text-green-500" />
                          ) : r.status === "failed" ? (
                            <XCircle className="w-4 h-4 text-red-500" />
                          ) : (
                            <span className="text-muted-foreground text-xs">skipped</span>
                          )}
                        </td>
                        <td className="py-2 pr-4 text-right">
                          {r.metrics.sharpe_ratio?.toFixed(3) ?? "—"}
                        </td>
                        <td className="py-2 pr-4 text-right">
                          {r.metrics.total_return_pct?.toFixed(2) ?? "—"}
                        </td>
                        <td className="py-2 pr-4 text-right text-red-400">
                          {r.metrics.max_drawdown_pct?.toFixed(2) ?? "—"}
                        </td>
                        <td className="py-2 pr-4 text-right">{r.trade_count}</td>
                        <td className="py-2 pr-4 text-right">
                          {r.walk_forward?.consistency_pct?.toFixed(0) ?? "—"}%
                        </td>
                        <td className="py-2 pr-4 text-right">
                          {r.monte_carlo?.prob_loss_pct?.toFixed(1) ?? "—"}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {/* No runs yet */}
      {!latest && !loading && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Bot className="w-12 h-12 text-muted-foreground mb-3" />
            <p className="text-muted-foreground text-sm">
              Belum ada backtest otonom yang berjalan.
              Sistem akan otomatis berjalan sesuai jadwal (EOD 17:30 WIB),
              perubahan data, event pasar, atau deteksi drift.
            </p>
            <button
              onClick={triggerRun}
              disabled={triggering}
              className="mt-4 px-6 py-2 rounded-md border border-border text-sm font-medium hover:bg-accent disabled:opacity-50 flex items-center gap-2"
            >
              {triggering ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
              Trigger Manual (Admin)
            </button>
          </CardContent>
        </Card>
      )}

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3">
          <p className="text-sm text-destructive">{error}</p>
        </div>
      )}
    </div>
  );
}
