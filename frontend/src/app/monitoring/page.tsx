"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Activity, AlertCircle, CheckCircle } from "lucide-react";

interface DriftStatus {
  feature: string;
  psi: number;
  status: string;
}

interface ICTrack {
  engine: string;
  ic_1d: number;
  ic_5d: number;
  ic_21d: number;
  ic_decay: number;
}

export default function MonitoringPage() {
  const [drifts, setDrifts] = useState<DriftStatus[]>([]);
  const [ics, setIcs] = useState<ICTrack[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Placeholder — will be replaced with real monitoring data
    setDrifts([
      { feature: "rsi_14", psi: 0.08, status: "OK" },
      { feature: "macd_signal", psi: 0.15, status: "OK" },
      { feature: "volume_ratio", psi: 0.31, status: "DRIFT" },
      { feature: "pe_ratio", psi: 0.12, status: "OK" },
      { feature: "news_sentiment", psi: 0.22, status: "OK" },
      { feature: "foreign_flow_net", psi: 0.45, status: "DRIFT" },
    ]);
    setIcs([
      { engine: "technical", ic_1d: 0.045, ic_5d: 0.038, ic_21d: 0.028, ic_decay: 0.38 },
      { engine: "fundamental", ic_1d: 0.032, ic_5d: 0.035, ic_21d: 0.030, ic_decay: 0.06 },
      { engine: "sentiment", ic_1d: 0.018, ic_5d: 0.022, ic_21d: 0.015, ic_decay: 0.17 },
      { engine: "macro", ic_1d: 0.028, ic_5d: 0.030, ic_21d: 0.025, ic_decay: 0.11 },
      { engine: "alpha_momentum", ic_1d: 0.041, ic_5d: 0.036, ic_21d: 0.022, ic_decay: 0.46 },
    ]);
    setLoading(false);
  }, []);

  const psiColor = (psi: number) => {
    if (psi < 0.1) return "text-green-500";
    if (psi < 0.25) return "text-yellow-500";
    return "text-red-500";
  };

  const driftIcon = (status: string) => {
    if (status === "OK") return <CheckCircle className="w-4 h-4 text-green-500" />;
    return <AlertCircle className="w-4 h-4 text-red-500" />;
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Activity className="w-6 h-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Monitoring & Drift Detection</h1>
          <p className="text-sm text-muted-foreground">
            IC tracking, feature drift (PSI), dan prediction vs reality
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="p-4">
          <p className="text-xs text-muted-foreground">Features OK</p>
          <p className="text-2xl font-bold text-green-500">
            {drifts.filter((d) => d.status === "OK").length}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-muted-foreground">Features Drifting</p>
          <p className="text-2xl font-bold text-red-500">
            {drifts.filter((d) => d.status === "DRIFT").length}
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-xs text-muted-foreground">Avg IC Decay</p>
          <p className="text-2xl font-bold">
            {ics.length > 0
              ? ((ics.reduce((s, e) => s + e.ic_decay, 0) / ics.length) * 100).toFixed(0) + "%"
              : "—"}
          </p>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card className="p-4">
          <h2 className="text-lg font-semibold mb-4">Feature Drift (PSI)</h2>
          {loading ? (
            <p className="text-muted-foreground">Loading...</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 px-3">Feature</th>
                  <th className="text-right py-2 px-3">PSI</th>
                  <th className="text-center py-2 px-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {drifts.map((d) => (
                  <tr key={d.feature} className="border-b hover:bg-accent/50">
                    <td className="py-2 px-3 font-medium">{d.feature}</td>
                    <td className={`text-right py-2 px-3 ${psiColor(d.psi)}`}>
                      {d.psi.toFixed(3)}
                    </td>
                    <td className="text-center py-2 px-3">
                      <span className="inline-flex items-center gap-1">
                        {driftIcon(d.status)}
                        {d.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card className="p-4">
          <h2 className="text-lg font-semibold mb-4">IC Tracking per Engine</h2>
          {loading ? (
            <p className="text-muted-foreground">Loading...</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="text-left py-2 px-3">Engine</th>
                  <th className="text-right py-2 px-3">IC 1D</th>
                  <th className="text-right py-2 px-3">IC 5D</th>
                  <th className="text-right py-2 px-3">IC 21D</th>
                  <th className="text-right py-2 px-3">Decay</th>
                </tr>
              </thead>
              <tbody>
                {ics.map((e) => (
                  <tr key={e.engine} className="border-b hover:bg-accent/50">
                    <td className="py-2 px-3 font-medium">{e.engine}</td>
                    <td className="text-right py-2 px-3">{e.ic_1d.toFixed(4)}</td>
                    <td className="text-right py-2 px-3">{e.ic_5d.toFixed(4)}</td>
                    <td className="text-right py-2 px-3">{e.ic_21d.toFixed(4)}</td>
                    <td className={`text-right py-2 px-3 ${e.ic_decay > 0.4 ? "text-red-500" : e.ic_decay > 0.2 ? "text-yellow-500" : "text-green-500"}`}>
                      {(e.ic_decay * 100).toFixed(0)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <Card className="p-4">
        <h2 className="text-lg font-semibold mb-2">PSI Interpretation</h2>
        <div className="space-y-2 text-sm text-muted-foreground">
          <p><strong className="text-green-500">PSI &lt; 0.1</strong> — No significant drift</p>
          <p><strong className="text-yellow-500">PSI 0.1-0.25</strong> — Moderate drift, monitor closely</p>
          <p><strong className="text-red-500">PSI &gt; 0.25</strong> — Significant drift, retrain required</p>
        </div>
      </Card>
    </div>
  );
}
