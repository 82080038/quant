"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCallback, useEffect, useState } from "react";

interface PositionData {
  shares: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  weight_pct: number;
}

interface Position extends PositionData {
  ticker: string;
}

interface PortfolioData {
  total_nav: number;
  cash: number;
  positions: Record<string, PositionData>;
  sector_exposure: Record<string, number>;
  market_exposure: Record<string, number>;
  largest_position_pct: number;
  n_positions: number;
}

export default function PortfolioPage() {
  const [data, setData] = useState<PortfolioData | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/portfolio");
      if (res.ok) setData(await res.json());
    } catch {
      // ignore
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const nav = data?.total_nav ?? 0;
  const cash = data?.cash ?? 0;
  const positionList = data ? Object.entries(data.positions).map(([ticker, p]) => ({ ticker, ...p })) : [];
  const unrealized = positionList.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Portofolio</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Posisi, PnL, alokasi, dan riwayat
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardHeader><CardTitle>NAV Total</CardTitle></CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">
              Rp {nav.toLocaleString("id-ID")}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Kas</CardTitle></CardHeader>
          <CardContent>
            <p className="text-2xl font-bold">
              Rp {cash.toLocaleString("id-ID")}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>PnL Unrealized</CardTitle></CardHeader>
          <CardContent>
            <p className={`text-2xl font-bold ${unrealized >= 0 ? "text-green-600" : "text-red-600"}`}>
              {unrealized >= 0 ? "+" : ""}Rp {unrealized.toLocaleString("id-ID")}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Posisi Aktif</CardTitle></CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-muted-foreground text-sm py-8 text-center">Memuat data...</p>
          ) : positionList.length === 0 ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="text-left py-2">Ticker</th>
                  <th className="text-right">Saham</th>
                  <th className="text-right">Avg Cost</th>
                  <th className="text-right">Harga</th>
                  <th className="text-right">Nilai</th>
                  <th className="text-right">PnL</th>
                  <th className="text-right">Bobot</th>
                </tr>
              </thead>
              <tbody>
                <tr className="text-muted-foreground">
                  <td colSpan={7} className="text-center py-8">
                    Belum ada posisi. Mulai paper trading untuk menambah posisi.
                  </td>
                </tr>
              </tbody>
            </table>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="text-left py-2">Ticker</th>
                  <th className="text-right">Saham</th>
                  <th className="text-right">Avg Cost</th>
                  <th className="text-right">Harga</th>
                  <th className="text-right">Nilai</th>
                  <th className="text-right">PnL</th>
                  <th className="text-right">Bobot</th>
                </tr>
              </thead>
              <tbody>
                {positionList.map((p) => (
                  <tr key={p.ticker} className="border-b border-border/50">
                    <td className="py-2 font-mono">{p.ticker}</td>
                    <td className="text-right">{p.shares.toLocaleString("id-ID")}</td>
                    <td className="text-right">{p.avg_cost.toLocaleString("id-ID", { minimumFractionDigits: 0 })}</td>
                    <td className="text-right">{p.current_price.toLocaleString("id-ID", { minimumFractionDigits: 0 })}</td>
                    <td className="text-right">Rp {p.market_value.toLocaleString("id-ID", { maximumFractionDigits: 0 })}</td>
                    <td className={`text-right ${p.unrealized_pnl >= 0 ? "text-green-600" : "text-red-600"}`}>
                      {p.unrealized_pnl >= 0 ? "+" : ""}Rp {p.unrealized_pnl.toLocaleString("id-ID", { maximumFractionDigits: 0 })}
                    </td>
                    <td className="text-right">{p.weight_pct.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Alokasi Sektor</CardTitle></CardHeader>
        <CardContent>
          {positionList.length > 0 && data?.sector_exposure ? (
            <div className="space-y-2">
              {Object.entries(data.sector_exposure).map(([sector, weight]) => (
                <div key={sector} className="flex items-center justify-between text-sm">
                  <span className="capitalize">{sector}</span>
                  <div className="flex items-center gap-2 flex-1 ml-4">
                    <div className="h-2 rounded-full bg-muted flex-1">
                      <div
                        className="h-2 rounded-full bg-primary"
                        style={{ width: `${Math.min(weight, 100)}%` }}
                      />
                    </div>
                    <span className="text-muted-foreground w-12 text-right">
                      {weight.toFixed(1)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-muted-foreground text-sm">
              Grafik alokasi sektor akan ditampilkan setelah posisi tersedia.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
