"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCallback, useState } from "react";

interface AdvisoryPick {
  ticker: string;
  composite_score: number;
  recommendation: string;
  factors?: Record<string, number>;
}

interface AdvisoryReport {
  market_regime: string;
  picks: AdvisoryPick[];
  summary?: string;
}

export default function ScreenerPage() {
  const [minComposite, setMinComposite] = useState(50);
  const [regime, setRegime] = useState("neutral");
  const [result, setResult] = useState<AdvisoryReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runScreen = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/advisory?market_regime=${encodeURIComponent(regime)}&min_composite=${minComposite}`,
      );
      if (res.ok) {
        setResult(await res.json());
      } else {
        setError(`Error: ${res.status}`);
      }
    } catch {
      setError("Tidak bisa terhubung ke API.");
    }
    setLoading(false);
  }, [minComposite, regime]);

  const picks = result?.picks ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Screener</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Filter saham berdasarkan skor faktor
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle>Filter</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="text-sm font-medium block mb-1">Min Composite Score</label>
              <input
                type="number"
                value={minComposite}
                onChange={(e) => setMinComposite(Number(e.target.value))}
                min={0}
                max={100}
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm"
              />
            </div>
            <div>
              <label className="text-sm font-medium block mb-1">Market Regime</label>
              <select
                value={regime}
                onChange={(e) => setRegime(e.target.value)}
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm"
              >
                <option value="neutral">Neutral</option>
                <option value="bull">Bull</option>
                <option value="bear">Bear</option>
                <option value="volatile">Volatile</option>
              </select>
            </div>
            <div className="flex items-end">
              <button
                onClick={runScreen}
                disabled={loading}
                className="w-full px-6 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
              >
                {loading ? "Menyaring..." : "Screening"}
              </button>
            </div>
          </div>
          {error && <p className="text-sm text-red-500 mt-2">{error}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>Hasil Screening</CardTitle>
            {result && (
              <span className="text-xs text-muted-foreground">
                Regime: {result.market_regime} • {picks.length} saham lolos
              </span>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {picks.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {result
                ? "Tidak ada saham yang lolos filter. Coba turunkan min composite score."
                : "Jalankan screening untuk melihat saham yang lolos filter."}
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="text-left py-2">Ticker</th>
                  <th className="text-right">Composite</th>
                  <th className="text-left">Rekomendasi</th>
                </tr>
              </thead>
              <tbody>
                {picks.map((p) => (
                  <tr key={p.ticker} className="border-b border-border/50">
                    <td className="py-2 font-mono">{p.ticker}</td>
                    <td className="text-right font-medium">
                      {p.composite_score?.toFixed(0) ?? "—"}
                    </td>
                    <td className="text-left">{p.recommendation ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
