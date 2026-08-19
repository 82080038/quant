"use client";

import { useState, useEffect, useCallback } from "react";
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
} from "lucide-react";

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

export default function BacktestPage() {
  const [status, setStatus] = useState<RunnerStatus | null>(null);
  const [latest, setLatest] = useState<BacktestRun | null>(null);
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

  useEffect(() => {
    void fetchStatus();
    void fetchLatest();
  }, [fetchStatus, fetchLatest]);

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
