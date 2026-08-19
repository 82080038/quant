"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Activity,
  Database,
  TrendingUp,
  Wallet,
  AlertCircle,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Cpu,
  Newspaper,
  Layers,
} from "lucide-react";

interface PipelineStateEntry {
  step: string;
  status: string;
  count: number;
}

interface DashboardData {
  pipeline_state: PipelineStateEntry[];
  signals: { total: number; tickers: number; engines: number };
  portfolio: { positions: number; concentrated: number };
  paper_trading: {
    date: string | null;
    nav: number | null;
    cash: number | null;
    n_trades: number;
    n_rejected: number;
    total_pnl: number;
    is_halted: boolean;
  };
  feature_values_count: number;
  news_sentiment_count: number;
  engines_tracked: number;
  engines: string[];
  error?: string;
}

const STEP_LABELS: Record<string, string> = {
  ingest: "Ingest",
  screen: "Screen",
  analyze: "Analyze",
  signal: "Signal",
  portfolio: "Portfolio",
  execute: "Execute",
};

const STATUS_COLORS: Record<string, string> = {
  ingested: "text-blue-400",
  screened: "text-blue-400",
  analyzed: "text-blue-400",
  signal_generated: "text-purple-400",
  portfolio_optimized: "text-green-400",
  done: "text-green-400",
  failed: "text-red-400",
  skipped: "text-yellow-400",
};

export default function PipelineDashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/pipeline/dashboard");
      if (res.ok) {
        const json = await res.json();
        setData(json);
        if (json.error) setError(json.error);
      } else {
        setError(`HTTP ${res.status}`);
      }
    } catch {
      setError("Cannot connect to API");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-96">
        <RefreshCw className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex flex-col items-center justify-center h-96 gap-2">
        <AlertCircle className="w-8 h-8 text-red-500" />
        <p className="text-muted-foreground">{error}</p>
        <button onClick={fetchData} className="px-4 py-2 text-sm border rounded-md hover:bg-accent">
          Retry
        </button>
      </div>
    );
  }

  const pt = data?.paper_trading;
  const stateByStep: Record<string, PipelineStateEntry[]> = {};
  data?.pipeline_state.forEach((s) => {
    if (!stateByStep[s.step]) stateByStep[s.step] = [];
    stateByStep[s.step].push(s);
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Pipeline Dashboard</h1>
          <p className="text-muted-foreground text-sm mt-1">
            End-to-end pipeline status & monitoring
          </p>
        </div>
        <button
          onClick={fetchData}
          disabled={loading}
          className="px-4 py-2 text-sm border rounded-md hover:bg-accent disabled:opacity-50 flex items-center gap-2"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 mb-1">
              <Wallet className="w-4 h-4 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">Paper Trading NAV</span>
            </div>
            <p className="text-2xl font-bold">
              {pt?.nav != null ? `${pt.nav.toLocaleString("id-ID", { maximumFractionDigits: 0 })}` : "—"}
            </p>
            <p className={`text-xs ${pt && pt.total_pnl >= 0 ? "text-green-500" : "text-red-500"}`}>
              {pt?.total_pnl != null ? `${pt.total_pnl >= 0 ? "+" : ""}${pt.total_pnl.toLocaleString("id-ID", { maximumFractionDigits: 0 })} P&L` : ""}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 mb-1">
              <TrendingUp className="w-4 h-4 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">Signals</span>
            </div>
            <p className="text-2xl font-bold">{data?.signals.total ?? 0}</p>
            <p className="text-xs text-muted-foreground">
              {data?.signals.tickers ?? 0} tickers • {data?.signals.engines ?? 0} engines
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 mb-1">
              <Layers className="w-4 h-4 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">Feature Values</span>
            </div>
            <p className="text-2xl font-bold">{data?.feature_values_count?.toLocaleString() ?? 0}</p>
            <p className="text-xs text-muted-foreground">rows in DB</p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 mb-1">
              <Newspaper className="w-4 h-4 text-muted-foreground" />
              <span className="text-xs text-muted-foreground">News Sentiment</span>
            </div>
            <p className="text-2xl font-bold">{data?.news_sentiment_count?.toLocaleString() ?? 0}</p>
            <p className="text-xs text-muted-foreground">articles scored</p>
          </CardContent>
        </Card>
      </div>

      {/* Pipeline State */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="w-5 h-5" />
            Pipeline State (Latest Date)
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
            {Object.entries(STEP_LABELS).map(([step, label]) => {
              const entries = stateByStep[step] || [];
              const total = entries.reduce((sum, e) => sum + e.count, 0);
              const done = entries.filter((e) => e.status === "done").reduce((s, e) => s + e.count, 0);
              const failed = entries.filter((e) => e.status === "failed").reduce((s, e) => s + e.count, 0);
              return (
                <div key={step} className="border rounded-lg p-3">
                  <p className="text-sm font-medium mb-2">{label}</p>
                  <p className="text-2xl font-bold">{total}</p>
                  <div className="flex items-center gap-2 mt-1 text-xs">
                    {done > 0 && (
                      <span className="flex items-center gap-1 text-green-500">
                        <CheckCircle2 className="w-3 h-3" /> {done}
                      </span>
                    )}
                    {failed > 0 && (
                      <span className="flex items-center gap-1 text-red-500">
                        <XCircle className="w-3 h-3" /> {failed}
                      </span>
                    )}
                  </div>
                  {entries.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {entries.map((e) => (
                        <div key={`${e.step}-${e.status}`} className="flex justify-between text-xs">
                          <span className={STATUS_COLORS[e.status] || "text-muted-foreground"}>
                            {e.status}
                          </span>
                          <span className="text-muted-foreground">{e.count}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Paper Trading + Portfolio */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Wallet className="w-5 h-5" />
              Paper Trading State
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">Date</span>
              <span className="text-sm font-mono">{pt?.date ?? "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">NAV</span>
              <span className="text-sm font-mono">
                {pt?.nav != null ? pt.nav.toLocaleString("id-ID", { maximumFractionDigits: 0 }) : "—"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">Cash</span>
              <span className="text-sm font-mono">
                {pt?.cash != null ? pt.cash.toLocaleString("id-ID", { maximumFractionDigits: 0 }) : "—"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">Trades</span>
              <span className="text-sm font-mono">{pt?.n_trades ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">Rejected</span>
              <span className="text-sm font-mono text-red-500">{pt?.n_rejected ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">Halted</span>
              <span className={`text-sm font-mono ${pt?.is_halted ? "text-red-500" : "text-green-500"}`}>
                {pt?.is_halted ? "YES" : "No"}
              </span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cpu className="w-5 h-5" />
              Models & Engines
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">Engines Tracked</span>
              <span className="text-sm font-mono">{data?.engines_tracked ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">Portfolio Positions</span>
              <span className="text-sm font-mono">{data?.portfolio.positions ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-sm text-muted-foreground">Concentrated (&gt;5%)</span>
              <span className="text-sm font-mono">{data?.portfolio.concentrated ?? 0}</span>
            </div>
            {data?.engines && data.engines.length > 0 && (
              <div>
                <p className="text-sm text-muted-foreground mb-2">Active Engines:</p>
                <div className="flex flex-wrap gap-2">
                  {data.engines.map((e) => (
                    <span
                      key={e}
                      className="px-2 py-1 text-xs rounded-md bg-accent text-accent-foreground font-mono"
                    >
                      {e}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
