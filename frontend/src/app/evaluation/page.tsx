"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { ShieldCheck, TrendingDown, TrendingUp, AlertTriangle } from "lucide-react";

interface EngineEval {
  engine: string;
  sharpe: number;
  dsr: number;
  pbo: number;
  ic: number;
  status: string;
}

export default function EvaluationPage() {
  const [engines, setEngines] = useState<EngineEval[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/signals/attribution?days=30")
      .then((r) => r.json())
      .then(() => {
        // Placeholder — will be replaced with real evaluation data
        setEngines([
          { engine: "technical", sharpe: 0.82, dsr: 0.71, pbo: 0.23, ic: 0.045, status: "KEEP" },
          { engine: "fundamental", sharpe: 0.65, dsr: 0.58, pbo: 0.31, ic: 0.032, status: "KEEP" },
          { engine: "sentiment", sharpe: 0.41, dsr: 0.35, pbo: 0.52, ic: 0.018, status: "WATCH" },
          { engine: "macro", sharpe: 0.55, dsr: 0.48, pbo: 0.28, ic: 0.028, status: "KEEP" },
          { engine: "alpha_momentum", sharpe: 0.73, dsr: 0.62, pbo: 0.25, ic: 0.041, status: "KEEP" },
          { engine: "alpha_mean_reversion", sharpe: 0.38, dsr: 0.29, pbo: 0.58, ic: 0.012, status: "WATCH" },
          { engine: "global_market", sharpe: 0.49, dsr: 0.42, pbo: 0.35, ic: 0.025, status: "KEEP" },
          { engine: "volume_features", sharpe: 0.31, dsr: 0.22, pbo: 0.64, ic: 0.008, status: "RETIRE" },
        ]);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const statusColor = (s: string) => {
    if (s === "KEEP") return "text-green-500";
    if (s === "WATCH") return "text-yellow-500";
    return "text-red-500";
  };

  const statusIcon = (s: string) => {
    if (s === "KEEP") return <TrendingUp className="w-4 h-4 text-green-500" />;
    if (s === "WATCH") return <AlertTriangle className="w-4 h-4 text-yellow-500" />;
    return <TrendingDown className="w-4 h-4 text-red-500" />;
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <ShieldCheck className="w-6 h-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Evaluasi Engine (DSR/PBO)</h1>
          <p className="text-sm text-muted-foreground">
            Deflated Sharpe Ratio & Probability of Backtest Overfitting per engine
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card className="p-4">
          <p className="text-xs text-muted-foreground">Total Engines</p>
          <p className="text-2xl font-bold">{engines.length}</p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-muted-foreground">KEEP</p>
          <p className="text-2xl font-bold text-green-500">
            {engines.filter((e) => e.status === "KEEP").length}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-muted-foreground">WATCH</p>
          <p className="text-2xl font-bold text-yellow-500">
            {engines.filter((e) => e.status === "WATCH").length}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-muted-foreground">RETIRE</p>
          <p className="text-2xl font-bold text-red-500">
            {engines.filter((e) => e.status === "RETIRE").length}
          </p>
        </Card>
      </div>

      <Card className="p-4">
        <h2 className="text-lg font-semibold mb-4">Engine Performance Matrix</h2>
        {loading ? (
          <p className="text-muted-foreground">Loading...</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 px-3">Engine</th>
                  <th className="text-right py-2 px-3">Sharpe</th>
                  <th className="text-right py-2 px-3">DSR</th>
                  <th className="text-right py-2 px-3">PBO</th>
                  <th className="text-right py-2 px-3">IC</th>
                  <th className="text-center py-2 px-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {engines.map((e) => (
                  <tr key={e.engine} className="border-b hover:bg-accent/50">
                    <td className="py-2 px-3 font-medium">{e.engine}</td>
                    <td className="text-right py-2 px-3">{e.sharpe.toFixed(2)}</td>
                    <td className={`text-right py-2 px-3 ${e.dsr > 0.5 ? "text-green-500" : "text-red-500"}`}>
                      {(e.dsr * 100).toFixed(0)}%
                    </td>
                    <td className={`text-right py-2 px-3 ${e.pbo < 0.5 ? "text-green-500" : "text-red-500"}`}>
                      {(e.pbo * 100).toFixed(0)}%
                    </td>
                    <td className="text-right py-2 px-3">{e.ic.toFixed(4)}</td>
                    <td className="text-center py-2 px-3">
                      <span className={`inline-flex items-center gap-1 ${statusColor(e.status)}`}>
                        {statusIcon(e.status)}
                        {e.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card className="p-4">
        <h2 className="text-lg font-semibold mb-2">Interpretasi</h2>
        <div className="space-y-2 text-sm text-muted-foreground">
          <p><strong className="text-green-500">DSR &gt; 95%</strong> — Sharpe ratio statistically real setelah koreksi selection bias</p>
          <p><strong className="text-green-500">PBO &lt; 50%</strong> — In-sample winner generalizes ke out-of-sample</p>
          <p><strong className="text-yellow-500">WATCH</strong> — Marginal performance, monitor IC decay</p>
          <p><strong className="text-red-500">RETIRE</strong> — IC decayed atau overfit, hapus dari pipeline</p>
        </div>
      </Card>
    </div>
  );
}
