"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TrendingUp, TrendingDown, Wallet, Activity } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

interface Mover {
  ticker: string;
  close: number;
  prev_close: number;
  pct_change: number;
}

interface MoversData {
  gainers: Mover[];
  losers: Mover[];
  as_of: string | null;
  count: number;
}

interface IhsgData {
  price: number | null;
  change: number | null;
  pct_change: number | null;
  as_of: string | null;
}

interface PortfolioSummary {
  total_nav: number;
  cash: number;
  positions: Record<string, {
    shares: number;
    avg_cost: number;
    current_price: number;
    market_value: number;
    unrealized_pnl: number;
    weight_pct: number;
  }>;
  n_positions: number;
}

export default function DashboardPage() {
  const [movers, setMovers] = useState<MoversData | null>(null);
  const [ihsg, setIhsg] = useState<IhsgData | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    const [moversRes, ihsgRes, portfolioRes] = await Promise.allSettled([
      fetch("/api/prices/movers?limit=5"),
      fetch("/api/prices/ihsg"),
      fetch("/api/portfolio"),
    ]);
    if (moversRes.status === "fulfilled" && moversRes.value.ok) {
      setMovers(await moversRes.value.json());
    }
    if (ihsgRes.status === "fulfilled" && ihsgRes.value.ok) {
      setIhsg(await ihsgRes.value.json());
    }
    if (portfolioRes.status === "fulfilled" && portfolioRes.value.ok) {
      const data = await portfolioRes.value.json();
      setPortfolio(data);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Ringkasan portofolio dan kondisi pasar
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>NAV Portofolio</CardTitle>
              <Wallet className="w-5 h-5 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">
              Rp {portfolio ? portfolio.total_nav.toLocaleString("id-ID") : "0"}
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              {portfolio && portfolio.n_positions > 0
                ? `${portfolio.n_positions} posisi aktif`
                : "Belum ada posisi aktif"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Return Hari Ini</CardTitle>
              <TrendingUp className="w-5 h-5 text-primary" />
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold text-primary">
              {portfolio && portfolio.n_positions > 0
                ? `${Object.values(portfolio.positions).reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0) >= 0 ? "+" : ""}Rp ${Object.values(portfolio.positions).reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0).toLocaleString("id-ID", { maximumFractionDigits: 0 })}`
                : "+0.00%"}
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              vs IHSG: {ihsg?.pct_change != null ? `${ihsg.pct_change >= 0 ? "+" : ""}${ihsg.pct_change.toFixed(2)}%` : "—"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Posisi Aktif</CardTitle>
              <Activity className="w-5 h-5 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">{portfolio?.n_positions ?? 0}</p>
            <p className="text-xs text-muted-foreground mt-1">
              {portfolio && portfolio.n_positions > 0 ? `${new Set(Object.keys(portfolio.positions)).size} sektor` : "0 sektor"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Watchlist</CardTitle>
              <TrendingDown className="w-5 h-5 text-muted-foreground" />
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">0</p>
            <p className="text-xs text-muted-foreground mt-1">
              Tambah saham ke watchlist
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Status Pasar IDX</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Sesi</span>
                <span className="font-medium">Regular (09:00-15:50 WIB)</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Status</span>
                <span className="font-medium text-yellow-500">Tutup</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">IHSG</span>
                <span className="font-medium">
                  {ihsg?.price != null
                    ? ihsg.price.toLocaleString("id-ID", { minimumFractionDigits: 2 })
                    : "—"}
                  {ihsg?.pct_change != null && (
                    <span className={ihsg.pct_change >= 0 ? "text-green-600 ml-1" : "text-red-600 ml-1"}>
                      {ihsg.pct_change >= 0 ? "+" : ""}{ihsg.pct_change.toFixed(2)}%
                    </span>
                  )}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Top Movers</CardTitle>
              {movers?.as_of && (
                <span className="text-xs text-muted-foreground">
                  {new Date(movers.as_of).toLocaleDateString("id-ID", {
                    day: "numeric",
                    month: "short",
                  })}
                </span>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {loading ? (
              <p className="text-muted-foreground text-sm">Memuat data...</p>
            ) : !movers || movers.count === 0 ? (
              <p className="text-muted-foreground text-sm">
                Belum ada data. Jalankan fetch untuk mengisi OHLCV.
              </p>
            ) : (
              <div className="space-y-3">
                <div>
                  <p className="text-xs font-medium text-green-600 mb-1">
                    Top Gainers
                  </p>
                  <div className="space-y-1">
                    {movers.gainers.map((m) => (
                      <div
                        key={m.ticker}
                        className="flex items-center justify-between text-sm"
                      >
                        <span className="font-mono">{m.ticker}</span>
                        <span className="font-medium text-green-600">
                          +{m.pct_change.toFixed(2)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-xs font-medium text-red-600 mb-1">
                    Top Losers
                  </p>
                  <div className="space-y-1">
                    {movers.losers.map((m) => (
                      <div
                        key={m.ticker}
                        className="flex items-center justify-between text-sm"
                      >
                        <span className="font-mono">{m.ticker}</span>
                        <span className="font-medium text-red-600">
                          {m.pct_change.toFixed(2)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
