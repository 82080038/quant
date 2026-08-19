"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCallback, useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";

interface StockData {
  ticker: string;
  latest: {
    close: number;
    open: number;
    high: number;
    low: number;
    volume: number;
    pct_change: number | null;
    as_of: string | null;
  };
  ohlcv: Array<{
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  }>;
  factors: {
    technical: number;
    fundamental: number;
    macro: number;
    global: number;
    relationship: number;
    sentiment: number;
    composite: number;
  };
  prediction: {
    direction: string;
    predicted_price: number | null;
    confidence: number | null;
    return_pct: number | null;
    horizon_days: number;
    as_of: string | null;
  } | null;
}

interface StrategyData {
  ticker: string;
  best_strategy: string;
  strategy_class: string;
  strategy_rationale: string | null;
  in_sample_sharpe: number | null;
  in_sample_max_dd: number | null;
  in_sample_winrate: number | null;
  updated_at: string | null;
}

const FACTOR_COLORS: Record<string, string> = {
  technical: "bg-blue-500",
  fundamental: "bg-green-500",
  macro: "bg-yellow-500",
  global: "bg-purple-500",
  relationship: "bg-pink-500",
  sentiment: "bg-orange-500",
};

export default function StockPage() {
  const [ticker, setTicker] = useState("");
  const [data, setData] = useState<StockData | null>(null);
  const [strategy, setStrategy] = useState<StrategyData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const analyze = useCallback(async () => {
    if (!ticker.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/stock/${encodeURIComponent(ticker.trim())}`);
      if (res.ok) {
        setData(await res.json());
      } else if (res.status === 404) {
        setError(`Ticker ${ticker.trim()} tidak ditemukan di database.`);
        setData(null);
      } else {
        setError(`Error: ${res.status}`);
        setData(null);
      }
      // Fetch strategy assignment (Gap #13)
      try {
        const stratRes = await fetch(`/api/strategy/assignment/${encodeURIComponent(ticker.trim())}`);
        if (stratRes.ok) {
          setStrategy(await stratRes.json());
        } else {
          setStrategy(null);
        }
      } catch {
        setStrategy(null);
      }
    } catch {
      setError("Tidak bisa terhubung ke API.");
      setData(null);
    }
    setLoading(false);
  }, [ticker]);

  const factors = data?.factors;
  const latest = data?.latest;
  const prediction = data?.prediction;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Detail Saham</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Chart, indikator, skor, dan rekomendasi
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle>Pencarian Saham</CardTitle></CardHeader>
        <CardContent>
          <div className="flex gap-4">
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && analyze()}
              placeholder="Masukkan ticker (contoh: BBCA.JK)"
              className="flex-1 px-4 py-2 rounded-md border border-input bg-background text-sm"
            />
            <button
              onClick={analyze}
              disabled={loading || !ticker.trim()}
              className="px-6 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
            >
              {loading ? "Memuat..." : "Analisis"}
            </button>
          </div>
          {error && <p className="text-sm text-red-500 mt-2">{error}</p>}
        </CardContent>
      </Card>

      {data && latest && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card>
              <CardContent className="pt-6">
                <p className="text-xs text-muted-foreground">Harga Terakhir</p>
                <p className="text-xl font-bold">
                  {latest.close.toLocaleString("id-ID", { minimumFractionDigits: 0 })}
                </p>
                {latest.pct_change != null && (
                  <p className={`text-sm ${latest.pct_change >= 0 ? "text-green-600" : "text-red-600"}`}>
                    {latest.pct_change >= 0 ? "+" : ""}{latest.pct_change.toFixed(2)}%
                  </p>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-xs text-muted-foreground">Open</p>
                <p className="text-xl font-bold">{latest.open.toLocaleString("id-ID", { minimumFractionDigits: 0 })}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-xs text-muted-foreground">High / Low</p>
                <p className="text-xl font-bold">
                  {latest.high.toLocaleString("id-ID", { minimumFractionDigits: 0 })} / {latest.low.toLocaleString("id-ID", { minimumFractionDigits: 0 })}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-xs text-muted-foreground">Volume</p>
                <p className="text-xl font-bold">{(latest.volume / 1e6).toFixed(1)}M</p>
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <Card className="lg:col-span-2">
              <CardHeader><CardTitle>Chart Harga (30 Hari)</CardTitle></CardHeader>
              <CardContent>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data.ohlcv}>
                      <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
                      <XAxis dataKey="date" tick={{ fontSize: 10 }} />
                      <YAxis tick={{ fontSize: 10 }} domain={["auto", "auto"]} />
                      <Tooltip
                        contentStyle={{ fontSize: 12 }}
                        formatter={(v: number) => v.toLocaleString("id-ID", { minimumFractionDigits: 0 })}
                      />
                      <Line type="monotone" dataKey="close" stroke="#3b82f6" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader><CardTitle>Skor Faktor</CardTitle></CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {factors && Object.entries(FACTOR_COLORS).map(([key, color]) => (
                    <div key={key}>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="capitalize">{key}</span>
                        <span className="font-medium">{factors[key as keyof typeof factors].toFixed(0)}/100</span>
                      </div>
                      <div className="h-2 rounded-full bg-muted">
                        <div
                          className={`h-2 rounded-full ${color}`}
                          style={{ width: `${Math.min(factors[key as keyof typeof factors], 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                  {factors && (
                    <div className="pt-2 border-t">
                      <div className="flex justify-between text-sm font-bold">
                        <span>Composite</span>
                        <span>{factors.composite.toFixed(0)}/100</span>
                      </div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader><CardTitle>Rekomendasi & Prediksi</CardTitle></CardHeader>
            <CardContent>
              {prediction ? (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div>
                    <p className="text-xs text-muted-foreground">Arah</p>
                    <p className={`text-lg font-bold ${prediction.direction === "up" ? "text-green-600" : prediction.direction === "down" ? "text-red-600" : "text-muted-foreground"}`}>
                      {prediction.direction === "up" ? "Naik" : prediction.direction === "down" ? "Turun" : "Datar"}
                    </p>
                  </div>
                  {prediction.predicted_price != null && (
                    <div>
                      <p className="text-xs text-muted-foreground">Target Harga</p>
                      <p className="text-lg font-bold">
                        {prediction.predicted_price.toLocaleString("id-ID", { minimumFractionDigits: 0 })}
                      </p>
                    </div>
                  )}
                  {prediction.confidence != null && (
                    <div>
                      <p className="text-xs text-muted-foreground">Confidence</p>
                      <p className="text-lg font-bold">{(prediction.confidence * 100).toFixed(0)}%</p>
                    </div>
                  )}
                  {prediction.return_pct != null && (
                    <div>
                      <p className="text-xs text-muted-foreground">Expected Return</p>
                      <p className={`text-lg font-bold ${prediction.return_pct >= 0 ? "text-green-600" : "text-red-600"}`}>
                        {prediction.return_pct >= 0 ? "+" : ""}{prediction.return_pct.toFixed(2)}%
                      </p>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">
                  Belum ada prediksi untuk ticker ini.
                </p>
              )}
            </CardContent>
          </Card>

          {strategy && (
            <Card>
              <CardHeader><CardTitle>Strategi Optimal</CardTitle></CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                  <div>
                    <p className="text-xs text-muted-foreground">Strategi</p>
                    <p className="text-lg font-bold capitalize">{strategy.best_strategy.replace(/_/g, " ")}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Kelas</p>
                    <p className="text-lg font-bold capitalize">{strategy.strategy_class.replace(/_/g, " ")}</p>
                  </div>
                  {strategy.in_sample_sharpe != null && (
                    <div>
                      <p className="text-xs text-muted-foreground">In-Sample Sharpe</p>
                      <p className="text-lg font-bold">{strategy.in_sample_sharpe.toFixed(3)}</p>
                    </div>
                  )}
                  {strategy.in_sample_winrate != null && (
                    <div>
                      <p className="text-xs text-muted-foreground">Win Rate</p>
                      <p className="text-lg font-bold">{strategy.in_sample_winrate.toFixed(1)}%</p>
                    </div>
                  )}
                </div>
                {strategy.strategy_rationale && (
                  <div className="pt-3 border-t">
                    <p className="text-xs text-muted-foreground mb-1">Rasional</p>
                    <p className="text-sm">{strategy.strategy_rationale}</p>
                  </div>
                )}
                {strategy.updated_at && (
                  <p className="text-xs text-muted-foreground mt-3">
                    Update: {new Date(strategy.updated_at).toLocaleString("id-ID")}
                  </p>
                )}
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
