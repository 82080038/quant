"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Bell,
  BellRing,
  RefreshCw,
  Loader2,
  AlertCircle,
  Wallet,
  Activity,
  CheckCircle2,
} from "lucide-react";

interface SignalEntry {
  ticker: string;
  action: string;
  signal: number;
  close_price: number;
  portfolio_weight: number;
  position_sizing: {
    shares: number;
    lots: number;
    allocation_idr: number;
  };
  vol_60d: number;
  adapt_kappa: number;
  baseline_mode: string;
  error: string | null;
  bursa?: string;
  sektor?: string;
  subsektor?: string;
  prediction?: {
    direction: string;
    predicted_price: number;
    return_pct: number;
    confidence: number;
    composite_signal: number;
    factors: Record<string, unknown>;
  };
  smart_money?: {
    smart_money_score: number;
    label: string;
    accumulation_streak: number;
    retail_sell_ratio: number;
    accumulation_grid: Array<{ day: string; score: number; color: string }>;
  };
}

interface SignalBody {
  signal_date: string;
  generated_at: string;
  keep_score: number;
  keep_verdict: string;
  promoted_to_keep: boolean;
  portfolio_capital: number;
  summary: {
    buy: number;
    sell: number;
    hold: number;
    errors: number;
    total_tickers: number;
  };
  signals: SignalEntry[];
  execution_analysis: Record<string, unknown> | null;
  overnight_strategy: Record<string, unknown> | null;
}

interface Notification {
  id: number;
  timestamp: string;
  title: string;
  status: string;
  body: SignalBody | null;
}

interface LatestSignalsResponse {
  found: boolean;
  message?: string;
  notification: Notification | null;
}

const ACTION_STYLES: Record<string, { color: string; bg: string; icon: typeof TrendingUp }> = {
  BUY: { color: "text-green-500", bg: "bg-green-500/10", icon: TrendingUp },
  SELL: { color: "text-red-500", bg: "bg-red-500/10", icon: TrendingDown },
  HOLD: { color: "text-yellow-500", bg: "bg-yellow-500/10", icon: Minus },
  FLAT: { color: "text-gray-500", bg: "bg-gray-500/10", icon: Minus },
  ERROR: { color: "text-red-600", bg: "bg-red-600/10", icon: AlertCircle },
};

function formatIDR(value: number): string {
  return new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency: "IDR",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

function formatNumber(value: number, decimals = 2): string {
  return new Intl.NumberFormat("id-ID", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export default function SignalsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notification, setNotification] = useState<Notification | null>(null);
  const [markingRead, setMarkingRead] = useState(false);

  const fetchLatestSignals = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/notifications/signals/latest");
      if (!res.ok) throw new Error("Gagal mengambil sinyal");
      const data: LatestSignalsResponse = await res.json();
      if (data.found && data.notification) {
        setNotification(data.notification);
      } else {
        setNotification(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchLatestSignals();
  }, [fetchLatestSignals]);

  const handleMarkRead = async () => {
    if (!notification) return;
    setMarkingRead(true);
    try {
      await fetch(`/api/notifications/${notification.id}/read`, { method: "PATCH" });
      setNotification({ ...notification, status: "READ" });
    } catch {
      // ignore
    } finally {
      setMarkingRead(false);
    }
  };

  const body = notification?.body;
  const signals = body?.signals ?? [];
  const summary = body?.summary;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <BellRing className="w-6 h-6 text-primary" />
            Sinyal Harian
          </h1>
          <p className="text-muted-foreground text-sm mt-1">
            Sinyal BUY/SELL/HOLD + position sizing HRP untuk 20 saham fokus
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => void fetchLatestSignals()}
            disabled={loading}
            className="px-4 py-2 rounded-md border border-border text-sm font-medium hover:bg-accent disabled:opacity-50 flex items-center gap-2"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            Refresh
          </button>
          {notification && notification.status === "UNREAD" && (
            <button
              onClick={handleMarkRead}
              disabled={markingRead}
              className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 flex items-center gap-2"
            >
              {markingRead ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
              Tandai Dibaca
            </button>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0" />
          <p className="text-sm text-red-500">{error}</p>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-primary" />
        </div>
      )}

      {/* No data */}
      {!loading && !notification && !error && (
        <Card>
          <CardContent>
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <Bell className="w-12 h-12 text-muted-foreground mb-4" />
              <p className="text-lg font-medium">Belum ada sinyal harian</p>
              <p className="text-sm text-muted-foreground mt-1">
                Jalankan <code className="px-1 py-0.5 rounded bg-muted text-xs">daily_signal_cron.py</code>{" "}
                untuk generate sinyal pertama
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Signal content */}
      {!loading && notification && body && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm">KEEP Score</CardTitle>
                  <Activity className="w-5 h-5 text-muted-foreground" />
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold">
                  {body.keep_score?.toFixed(2) ?? "—"}
                  <span className="text-sm text-muted-foreground">/5.00</span>
                </p>
                <p className={`text-xs mt-1 font-medium ${
                  body.promoted_to_keep ? "text-green-500" : "text-yellow-500"
                }`}>
                  {body.promoted_to_keep ? "PROMOTED KEEP" : body.keep_verdict || "Belum promote"}
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm">Modal Portofolio</CardTitle>
                  <Wallet className="w-5 h-5 text-muted-foreground" />
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold">{formatIDR(body.portfolio_capital ?? 0)}</p>
                <p className="text-xs text-muted-foreground mt-1">Total alokasi</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm">Sinyal</CardTitle>
                  <TrendingUp className="w-5 h-5 text-muted-foreground" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex gap-3 text-sm">
                  <span className="text-green-500 font-bold">{summary?.buy ?? 0} BUY</span>
                  <span className="text-red-500 font-bold">{summary?.sell ?? 0} SELL</span>
                  <span className="text-yellow-500 font-bold">{summary?.hold ?? 0} HOLD</span>
                </div>
                {summary && summary.errors > 0 && (
                  <p className="text-xs text-red-500 mt-1">{summary.errors} error</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm">Tanggal Sinyal</CardTitle>
                  <Bell className="w-5 h-5 text-muted-foreground" />
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-lg font-bold">{body.signal_date ?? "—"}</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {notification.timestamp
                    ? new Date(notification.timestamp).toLocaleString("id-ID", { timeZone: "Asia/Jakarta" }) + " WIB"
                    : ""}
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Signal table */}
          <Card>
            <CardHeader>
              <CardTitle>Detail Sinyal per Ticker ({signals.length})</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left">
                      <th className="py-2 px-3 font-medium text-muted-foreground">Ticker</th>
                      <th className="py-2 px-3 font-medium text-muted-foreground">Sinyal</th>
                      <th className="py-2 px-3 font-medium text-muted-foreground text-right">Close</th>
                      <th className="py-2 px-3 font-medium text-muted-foreground text-right">Weight</th>
                      <th className="py-2 px-3 font-medium text-muted-foreground text-right">Lots</th>
                      <th className="py-2 px-3 font-medium text-muted-foreground text-right">Alokasi IDR</th>
                      <th className="py-2 px-3 font-medium text-muted-foreground">Sektor</th>
                      <th className="py-2 px-3 font-medium text-muted-foreground">Prediksi</th>
                      <th className="py-2 px-3 font-medium text-muted-foreground">Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {signals.map((sig, i) => {
                      const style = ACTION_STYLES[sig.action] ?? ACTION_STYLES["HOLD"];
                      const ActionIcon = style.icon;
                      return (
                        <tr key={i} className="border-b border-border/50 hover:bg-accent/30">
                          <td className="py-2 px-3 font-medium">{sig.ticker}</td>
                          <td className="py-2 px-3">
                            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-bold ${style.bg} ${style.color}`}>
                              <ActionIcon className="w-3 h-3" />
                              {sig.action}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-right tabular-nums">
                            {sig.close_price ? formatNumber(sig.close_price) : "—"}
                          </td>
                          <td className="py-2 px-3 text-right tabular-nums">
                            {(sig.portfolio_weight * 100).toFixed(2)}%
                          </td>
                          <td className="py-2 px-3 text-right tabular-nums">
                            {sig.position_sizing?.lots ?? 0}
                          </td>
                          <td className="py-2 px-3 text-right tabular-nums">
                            {sig.position_sizing?.allocation_idr
                              ? formatIDR(sig.position_sizing.allocation_idr)
                              : "—"}
                          </td>
                          <td className="py-2 px-3 text-muted-foreground text-xs">
                            {sig.sektor ?? "—"}
                          </td>
                          <td className="py-2 px-3">
                            {sig.prediction ? (
                              <span className={`text-xs font-medium ${
                                sig.prediction.direction === "up" ? "text-green-500" :
                                sig.prediction.direction === "down" ? "text-red-500" :
                                "text-yellow-500"
                              }`}>
                                {sig.prediction.direction.toUpperCase()}{" "}
                                ({sig.prediction.return_pct >= 0 ? "+" : ""}
                                {formatNumber(sig.prediction.return_pct)}%)
                              </span>
                            ) : "—"}
                          </td>
                          <td className="py-2 px-3">
                            {sig.prediction ? (
                              <span className="text-xs tabular-nums">
                                {(sig.prediction.confidence * 100).toFixed(0)}%
                              </span>
                            ) : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {/* Smart Money / Bandarmology */}
          {signals.some((s) => s.smart_money) && (
            <Card>
              <CardHeader>
                <CardTitle>Smart Money / Bandarmology (5-Day Accumulation Grid)</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {signals
                    .filter((s) => s.smart_money)
                    .map((sig, i) => (
                      <div key={i} className="flex items-center gap-4 py-2 border-b border-border/30">
                        <span className="font-medium text-sm w-24">{sig.ticker}</span>
                        <span className={`text-xs font-medium ${
                          sig.smart_money!.smart_money_score > 0 ? "text-green-500" :
                          sig.smart_money!.smart_money_score < 0 ? "text-red-500" :
                          "text-gray-500"
                        }`}>
                          Score: {sig.smart_money!.smart_money_score.toFixed(2)} ({sig.smart_money!.label})
                        </span>
                        <div className="flex gap-1">
                          {sig.smart_money!.accumulation_grid?.map((cell, ci) => (
                            <div
                              key={ci}
                              className={`w-8 h-8 rounded flex items-center justify-center text-xs font-bold ${
                                cell.color === "green" ? "bg-green-500/20 text-green-500" :
                                cell.color === "red" ? "bg-red-500/20 text-red-500" :
                                "bg-gray-500/20 text-gray-500"
                              }`}
                              title={`${cell.day}: ${cell.score.toFixed(3)}`}
                            >
                              {cell.score > 0 ? "+" : cell.score < 0 ? "-" : "·"}
                            </div>
                          ))}
                        </div>
                        <span className="text-xs text-muted-foreground">
                          Streak: {sig.smart_money!.accumulation_streak}d ·
                          Retail Sell: {(sig.smart_money!.retail_sell_ratio * 100).toFixed(0)}%
                        </span>
                      </div>
                    ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Overnight Strategy */}
          {body.overnight_strategy && (
            <Card>
              <CardHeader>
                <CardTitle>Overnight Strategy Mining</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="text-xs text-muted-foreground overflow-x-auto">
                  {JSON.stringify(body.overnight_strategy, null, 2)}
                </pre>
              </CardContent>
            </Card>
          )}

          {/* Execution Analysis */}
          {body.execution_analysis && (
            <Card>
              <CardHeader>
                <CardTitle>Post-Trade Execution Analysis</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="text-xs text-muted-foreground overflow-x-auto">
                  {JSON.stringify(body.execution_analysis, null, 2)}
                </pre>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
