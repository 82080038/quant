"use client";

import { useEffect, useState, useCallback } from "react";
import { TrendingUp, TrendingDown, Minus, Telescope } from "lucide-react";
import { Widget } from "./widget";
import { cn } from "@/lib/utils";

interface Projection {
  ticker: string;
  horizon: string;
  horizon_days: number;
  direction: string;
  estimated_magnitude_pct: number;
  confidence: number;
  root_cause: string;
  top_engine: string;
}

interface EngineScore {
  engine: string;
  total_predictions: number;
  directional_accuracy: number;
  mape: number;
  f1_score: number;
  decision: string;
}

export function MultiHorizonProjection() {
  const [projections, setProjections] = useState<Projection[]>([]);
  const [scores, setScores] = useState<EngineScore[]>([]);
  const [loading, setLoading] = useState(true);
  const [evalRunning, setEvalRunning] = useState(false);
  const [evalStatus, setEvalStatus] = useState("");

  const loadData = useCallback(async () => {
    try {
      const [projRes, reportRes] = await Promise.all([
        fetch("/api/projections/multi-horizon"),
        fetch("/api/evaluation/report"),
      ]);
      if (projRes.ok) {
        const data = await projRes.json();
        setProjections(data.projections ?? []);
      }
      if (reportRes.ok) {
        const data = await reportRes.json();
        setScores(data.engine_scores ?? []);
      }
    } catch {
      // keep previous
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const id = setInterval(loadData, 30_000);
    return () => clearInterval(id);
  }, [loadData]);

  const runEvaluation = useCallback(async () => {
    try {
      setEvalRunning(true);
      setEvalStatus("Memulai evaluasi...");
      await fetch("/api/evaluation/run", { method: "POST" });
      const poll = setInterval(async () => {
        const res = await fetch("/api/evaluation/status");
        if (res.ok) {
          const data = await res.json();
          setEvalStatus(data.progress ?? "");
          if (!data.running) {
            clearInterval(poll);
            setEvalRunning(false);
            if (data.done) {
              loadData();
            }
          }
        }
      }, 3000);
    } catch {
      setEvalRunning(false);
      setEvalStatus("Error menjalankan evaluasi");
    }
  }, [loadData]);

  const horizons = ["+1Hari", "+1Minggu", "+1Bulan", "+1Tahun"];
  const tickers = [...new Set(projections.map((p) => p.ticker))].slice(0, 8);

  const dirIcon = (dir: string) =>
    dir === "NAIK" ? <TrendingUp className="w-3 h-3 text-emerald-400" /> :
    dir === "TURUN" ? <TrendingDown className="w-3 h-3 text-red-400" /> :
    <Minus className="w-3 h-3 text-muted-foreground" />;

  const dirColor = (dir: string) =>
    dir === "NAIK" ? "text-emerald-400" :
    dir === "TURUN" ? "text-red-400" : "text-muted-foreground";

  return (
    <Widget
      title="Proyeksi Multi-Horizon"
      icon={<Telescope className="w-3.5 h-3.5" />}
      accent="text-purple-400"
      className="col-span-6"
      right={
        <button
          onClick={runEvaluation}
          disabled={evalRunning}
          className="text-[10px] px-2 py-0.5 rounded border border-border hover:bg-accent text-muted-foreground disabled:opacity-50"
        >
          {evalRunning ? "Menyimulasikan..." : "Evaluasi Ulang"}
        </button>
      }
    >
      <div className="space-y-3">
        {/* Status bar */}
        {evalStatus && (
          <div className="text-[10px] text-muted-foreground">{evalStatus}</div>
        )}

        {/* Engine accuracy summary */}
        {scores.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {scores.filter(s => s.total_predictions > 0).slice(0, 6).map((s) => (
              <span
                key={s.engine}
                className={cn(
                  "text-[9px] px-1.5 py-0.5 rounded font-mono tabular-nums",
                  s.decision === "KEEP" ? "bg-emerald-500/10 text-emerald-400" :
                  s.decision === "TUNE" ? "bg-yellow-500/10 text-yellow-400" :
                  s.decision === "REPLACE" ? "bg-red-500/10 text-red-400" :
                  "bg-muted text-muted-foreground"
                )}
                title={`DA: ${s.directional_accuracy}%, MAPE: ${s.mape}%, F1: ${s.f1_score}`}
              >
                {s.engine}: {s.directional_accuracy.toFixed(0)}%
              </span>
            ))}
          </div>
        )}

        {/* Projection table */}
        {loading ? (
          <div className="text-muted-foreground/60 italic text-xs">Memuat proyeksi...</div>
        ) : projections.length === 0 ? (
          <div className="text-muted-foreground/60 italic text-xs">Belum ada proyeksi. Jalankan evaluasi terlebih dahulu.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border/40 text-left">
                  <th className="py-1 pr-2 text-[10px] text-muted-foreground">Ticker</th>
                  {horizons.map((h) => (
                    <th key={h} className="py-1 px-1 text-[10px] text-muted-foreground text-center">{h}</th>
                  ))}
                  <th className="py-1 pl-2 text-[10px] text-muted-foreground">Faktor Pemicu</th>
                </tr>
              </thead>
              <tbody>
                {tickers.map((ticker) => (
                  <tr key={ticker} className="border-b border-border/20 last:border-0">
                    <td className="py-1 pr-2 font-mono font-semibold tabular-nums">{ticker}</td>
                    {horizons.map((h) => {
                      const proj = projections.find((p) => p.ticker === ticker && p.horizon === h);
                      if (!proj) return <td key={h} className="py-1 px-1 text-center text-muted-foreground/40">—</td>;
                      return (
                        <td key={h} className="py-1 px-1 text-center">
                          <span className={cn("inline-flex items-center gap-0.5 font-mono tabular-nums", dirColor(proj.direction))}>
                            {dirIcon(proj.direction)}
                            {proj.estimated_magnitude_pct.toFixed(2)}%
                          </span>
                        </td>
                      );
                    })}
                    <td className="py-1 pl-2 text-[10px] text-muted-foreground truncate max-w-[120px]" title={projections.find(p => p.ticker === ticker)?.root_cause ?? ""}>
                      {projections.find(p => p.ticker === ticker)?.root_cause?.slice(0, 40) ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Widget>
  );
}
