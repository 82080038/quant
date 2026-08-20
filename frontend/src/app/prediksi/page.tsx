"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Telescope,
  Loader2,
  CheckCircle2,
  TrendingUp,
  TrendingDown,
  Minus,
  Activity,
  Gauge,
  Target,
  Zap,
  AlertTriangle,
  ShieldCheck,
  Award,
  CalendarDays,
} from "lucide-react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  BarChart,
  Bar,
  Cell,
} from "recharts";
import { cn } from "@/lib/utils";

interface SimProgress {
  running: boolean;
  done: boolean;
  current_day: number;
  total_trading_days: number;
  sim_date: string | null;
  directional_accuracy: number;
  avg_mape: number;
  f1_score: number;
  equity: number;
  regime: string;
  top_engine: string;
  worst_engine: string;
  lookahead_violations: number;
  n_predictions: number;
  n_correct: number;
  message: string;
  day_log: DayLogEntry[];
  equity_curve: { date: string; equity: number }[];
}

interface DayLogEntry {
  sim_date: string;
  n_predictions: number;
  n_correct: number;
  directional_accuracy: number;
  avg_mape: number;
  f1_score: number;
  equity: number;
  regime: string;
  top_engine: string;
  worst_engine: string;
}

interface SimReport {
  start_date: string;
  end_date: string;
  trading_days: number;
  total_predictions: number;
  total_correct: number;
  overall_da: number;
  overall_mape: number;
  overall_f1: number;
  final_equity: number;
  total_return_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  lookahead_violations: number;
  engine_scores: EngineScore[];
  ticker_scores: TickerScore[];
  daily_results: DayLogEntry[];
  equity_curve: { date: string; equity: number }[];
  horizon_projections: HorizonProj[];
}

interface EngineScore {
  engine: string;
  total_predictions: number;
  correct: number;
  directional_accuracy: number;
  mape: number;
  f1_score: number;
}

interface TickerScore {
  ticker: string;
  total_predictions: number;
  correct: number;
  directional_accuracy: number;
}

interface HorizonProj {
  ticker: string;
  horizon: string;
  direction: string;
  estimated_magnitude_pct: number;
  confidence: number;
  root_cause: string;
  top_engine: string;
}

const REGIME_COLORS: Record<string, string> = {
  bull: "text-emerald-400",
  bear: "text-red-400",
  sideways: "text-yellow-400",
  unknown: "text-muted-foreground",
};

const DA_COLOR = (da: number) =>
  da >= 75 ? "text-emerald-400" : da >= 50 ? "text-yellow-400" : "text-red-400";

const DA_BG = (da: number) =>
  da >= 75 ? "bg-emerald-500/10" : da >= 50 ? "bg-yellow-500/10" : "bg-red-500/10";

export default function PrediksiPage() {
  const [progress, setProgress] = useState<SimProgress | null>(null);
  const [report, setReport] = useState<SimReport | null>(null);
  const [loading, setLoading] = useState(true);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  const fetchProgress = useCallback(async () => {
    try {
      const res = await fetch("/api/prediction-sim/progress");
      if (res.ok) {
        const data = await res.json();
        setProgress(data);
        if (data.done && !data.running) {
          const repRes = await fetch("/api/prediction-sim/report");
          if (repRes.ok) {
            const rep = await repRes.json();
            if (rep.status !== "not_found") setReport(rep);
          }
        }
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProgress();
    const id = setInterval(fetchProgress, 2000);
    pollRef.current = id;
    return () => clearInterval(id);
  }, [fetchProgress]);

  const startSim = useCallback(async () => {
    try {
      await fetch("/api/prediction-sim/run", { method: "POST" });
      fetchProgress();
    } catch {
      // ignore
    }
  }, [fetchProgress]);

  const stopSim = useCallback(async () => {
    try {
      await fetch("/api/prediction-sim/stop", { method: "POST" });
    } catch {
      // ignore
    }
  }, []);

  const running = progress?.running ?? false;
  const done = progress?.done ?? false;
  const pct = progress && progress.total_trading_days > 0
    ? (progress.current_day / progress.total_trading_days) * 100
    : 0;

  const equityData = (report?.equity_curve ?? progress?.equity_curve ?? []).map((d) => ({
    date: d.date,
    equity: d.equity / 1_000_000,
  }));

  const engineData = (report?.engine_scores ?? []).slice(0, 12).map((e) => ({
    name: e.engine,
    da: e.directional_accuracy,
  }));

  const dirIcon = (dir: string) =>
    dir === "NAIK" ? <TrendingUp className="w-3 h-3 text-emerald-400" /> :
    dir === "TURUN" ? <TrendingDown className="w-3 h-3 text-red-400" /> :
    <Minus className="w-3 h-3 text-muted-foreground" />;

  const horizons = ["+1Hari", "+1Minggu", "+1Bulan", "+1Tahun"];
  const projections = report?.horizon_projections ?? [];
  const projTickers = [...new Set(projections.map((p) => p.ticker))].slice(0, 8);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Telescope className="w-6 h-6 text-purple-400" />
          Simulasi Prediksi 1 Tahun
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          Evaluasi akurasi prediksi 15 engine sinyal terhadap data aktual 1 tahun.
          Setiap hari bursa, semua engine menghasilkan prediksi arah (Naik/Turun/Datar)
          yang dibandingkan dengan pergerakan harga aktual T+1.
        </p>
      </div>

      {/* Control Panel */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Zap className="w-4 h-4 text-yellow-400" />
            Kontrol Simulasi Prediksi
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {/* Run/Stop buttons */}
            <div className="flex items-center gap-4 flex-wrap">
              <button
                onClick={startSim}
                disabled={running}
                className="px-6 py-2 rounded-md bg-purple-600 text-white text-sm font-medium hover:bg-purple-700 disabled:opacity-50 flex items-center gap-2"
              >
                {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Telescope className="w-4 h-4" />}
                {running ? "Menyimulasikan..." : "Jalankan Simulasi Prediksi 1 Tahun"}
              </button>
              {running && (
                <button
                  onClick={stopSim}
                  className="px-4 py-2 rounded-md border border-red-500/50 text-red-400 text-sm hover:bg-red-500/10"
                >
                  Hentikan
                </button>
              )}
              {done && (
                <span className="flex items-center gap-1 text-sm text-emerald-400 font-medium">
                  <CheckCircle2 className="w-4 h-4" /> Simulasi Selesai
                </span>
              )}
              {progress && !done && !running && progress.message && (
                <span className="text-sm text-muted-foreground">{progress.message}</span>
              )}
            </div>

            {/* Progress bar */}
            {progress && (running || done) && (
              <>
                <div className="w-full bg-muted rounded-full h-3 overflow-hidden">
                  <div
                    className="h-full bg-purple-500 transition-all duration-500 rounded-full"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <p className="text-xs text-muted-foreground text-center">
                  Hari {progress.current_day} / {progress.total_trading_days} hari bursa
                  {progress.sim_date && ` | ${progress.sim_date}`}
                  {progress.message && ` | ${progress.message}`}
                </p>
              </>
            )}

            {/* Live metrics grid */}
            {progress && (running || done) && progress.n_predictions > 0 && (
              <div className="grid grid-cols-3 md:grid-cols-6 gap-3 text-sm">
                <div className="rounded-md border border-border p-2">
                  <p className="text-xs text-muted-foreground">DA Kumulatif</p>
                  <p className={cn("font-bold font-mono", DA_COLOR(progress.directional_accuracy))}>
                    {progress.directional_accuracy.toFixed(1)}%
                  </p>
                </div>
                <div className="rounded-md border border-border p-2">
                  <p className="text-xs text-muted-foreground">MAPE</p>
                  <p className="font-bold font-mono">{progress.avg_mape.toFixed(1)}%</p>
                </div>
                <div className="rounded-md border border-border p-2">
                  <p className="text-xs text-muted-foreground">F1 Score</p>
                  <p className="font-bold font-mono">{progress.f1_score.toFixed(3)}</p>
                </div>
                <div className="rounded-md border border-border p-2">
                  <p className="text-xs text-muted-foreground">Ekuitas</p>
                  <p className="font-bold font-mono">{(progress.equity / 1_000_000).toFixed(2)}Jt</p>
                </div>
                <div className="rounded-md border border-border p-2">
                  <p className="text-xs text-muted-foreground">Prediksi</p>
                  <p className="font-bold font-mono">{progress.n_predictions}</p>
                </div>
                <div className="rounded-md border border-border p-2">
                  <p className="text-xs text-muted-foreground">Regime</p>
                  <p className={cn("font-bold", REGIME_COLORS[progress.regime] || "text-muted-foreground")}>
                    {progress.regime}
                  </p>
                </div>
              </div>
            )}

            {/* Top/Worst engine badges */}
            {progress && (running || done) && progress.top_engine !== "—" && (
              <div className="flex items-center gap-3 text-xs">
                <span className="flex items-center gap-1 text-emerald-400">
                  <Award className="w-3 h-3" /> Engine Terbaik: <strong>{progress.top_engine}</strong>
                </span>
                <span className="flex items-center gap-1 text-red-400">
                  <AlertTriangle className="w-3 h-3" /> Engine Terburuk: <strong>{progress.worst_engine}</strong>
                </span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Results — only show when done or has data */}
      {report && (
        <>
          {/* Summary banner */}
          <div className="rounded-md border border-purple-500/30 bg-purple-500/5 p-4">
            <div className="flex items-start gap-3">
              <CalendarDays className="w-5 h-5 text-purple-500 mt-0.5 flex-shrink-0" />
              <div className="text-sm space-y-1">
                <p className="font-medium text-purple-600 dark:text-purple-400">
                  Simulasi Prediksi 1 Tahun — Selesai
                </p>
                <p className="text-muted-foreground">
                  Periode: {report.start_date} → {report.end_date} |
                  {report.trading_days} hari bursa dieksekusi |
                  {report.total_predictions} prediksi dievaluasi |
                  Pelanggaran look-ahead: {report.lookahead_violations}
                </p>
              </div>
            </div>
          </div>

          {/* Summary metrics cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-xs flex items-center gap-1"><CalendarDays className="w-3 h-3" /> Hari Bursa</CardTitle></CardHeader>
              <CardContent><p className="text-xl font-bold">{report.trading_days}</p></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-xs flex items-center gap-1"><Target className="w-3 h-3" /> Total Prediksi</CardTitle></CardHeader>
              <CardContent><p className="text-xl font-bold">{report.total_predictions}</p></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-xs flex items-center gap-1"><Activity className="w-3 h-3" /> DA Keseluruhan</CardTitle></CardHeader>
              <CardContent><p className={cn("text-xl font-bold", DA_COLOR(report.overall_da))}>{report.overall_da.toFixed(1)}%</p></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-xs flex items-center gap-1"><Gauge className="w-3 h-3" /> MAPE</CardTitle></CardHeader>
              <CardContent><p className="text-xl font-bold">{report.overall_mape.toFixed(1)}%</p></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-xs flex items-center gap-1"><Target className="w-3 h-3" /> F1 Score</CardTitle></CardHeader>
              <CardContent><p className="text-xl font-bold">{report.overall_f1.toFixed(3)}</p></CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-xs flex items-center gap-1"><ShieldCheck className="w-3 h-3" /> Look-ahead</CardTitle></CardHeader>
              <CardContent><p className="text-xl font-bold text-emerald-400">{report.lookahead_violations}</p></CardContent>
            </Card>
          </div>

          {/* Equity Curve */}
          {equityData.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-emerald-400" />
                  Kurva Ekuitas Prediksi
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={250}>
                  <AreaChart data={equityData}>
                    <defs>
                      <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#a855f7" stopOpacity={0.3} />
                        <stop offset="100%" stopColor="#a855f7" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <XAxis dataKey="date" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 10 }} domain={["auto", "auto"]} />
                    <Tooltip
                      contentStyle={{ fontSize: 11, background: "#1a1a2e", border: "1px solid #333" }}
                      formatter={(v: number) => [`Rp ${v.toFixed(2)}Jt`, "Ekuitas"]}
                    />
                    <Area type="monotone" dataKey="equity" stroke="#a855f7" strokeWidth={2} fill="url(#eqGrad)" />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          {/* Engine Accuracy Bar Chart */}
          {engineData.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm flex items-center gap-2">
                  <Award className="w-4 h-4 text-yellow-400" />
                  Akurasi Directional per Engine
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart data={engineData} layout="vertical" margin={{ left: 100 }}>
                    <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10 }} />
                    <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={100} />
                    <Tooltip
                      contentStyle={{ fontSize: 11, background: "#1a1a2e", border: "1px solid #333" }}
                      formatter={(v: number) => [`${v.toFixed(1)}%`, "DA"]}
                    />
                    <Bar dataKey="da" radius={[0, 4, 4, 0]}>
                      {engineData.map((e, i) => (
                        <Cell key={i} fill={e.da >= 75 ? "#22c55e" : e.da >= 50 ? "#eab308" : "#ef4444"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          {/* Engine Scores Table */}
          {report.engine_scores.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Skor Engine</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border text-left">
                        <th className="py-1 px-2">Engine</th>
                        <th className="py-1 px-2 text-right">Prediksi</th>
                        <th className="py-1 px-2 text-right">Benar</th>
                        <th className="py-1 px-2 text-right">DA%</th>
                        <th className="py-1 px-2 text-right">MAPE%</th>
                        <th className="py-1 px-2 text-right">F1</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.engine_scores.map((e) => (
                        <tr key={e.engine} className="border-b border-border/30">
                          <td className="py-1 px-2 font-mono">{e.engine}</td>
                          <td className="py-1 px-2 text-right font-mono">{e.total_predictions}</td>
                          <td className="py-1 px-2 text-right font-mono">{e.correct}</td>
                          <td className={cn("py-1 px-2 text-right font-mono font-bold", DA_COLOR(e.directional_accuracy))}>
                            {e.directional_accuracy.toFixed(1)}%
                          </td>
                          <td className="py-1 px-2 text-right font-mono">{e.mape.toFixed(1)}%</td>
                          <td className="py-1 px-2 text-right font-mono">{e.f1_score.toFixed(3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Multi-Horizon Projections */}
          {projections.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm flex items-center gap-2">
                  <Telescope className="w-4 h-4 text-purple-400" />
                  Proyeksi Multi-Horizon
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border text-left">
                        <th className="py-1 px-2">Ticker</th>
                        {horizons.map((h) => (
                          <th key={h} className="py-1 px-2 text-center">{h}</th>
                        ))}
                        <th className="py-1 px-2">Faktor Pemicu</th>
                      </tr>
                    </thead>
                    <tbody>
                      {projTickers.map((ticker) => (
                        <tr key={ticker} className="border-b border-border/20">
                          <td className="py-1 px-2 font-mono font-semibold">{ticker}</td>
                          {horizons.map((h) => {
                            const proj = projections.find((p) => p.ticker === ticker && p.horizon === h);
                            if (!proj) return <td key={h} className="py-1 px-2 text-center text-muted-foreground/40">—</td>;
                            return (
                              <td key={h} className="py-1 px-2 text-center">
                                <span className={cn(
                                  "inline-flex items-center gap-0.5 font-mono tabular-nums",
                                  proj.direction === "NAIK" ? "text-emerald-400" :
                                  proj.direction === "TURUN" ? "text-red-400" : "text-muted-foreground"
                                )}>
                                  {dirIcon(proj.direction)}
                                  {proj.estimated_magnitude_pct.toFixed(2)}%
                                </span>
                              </td>
                            );
                          })}
                          <td className="py-1 px-2 text-[10px] text-muted-foreground truncate max-w-[150px]">
                            {projections.find((p) => p.ticker === ticker)?.root_cause?.slice(0, 40) ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Daily Log */}
          {report.daily_results.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Log Harian Simulasi (30 hari terakhir)</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="max-h-60 overflow-y-auto rounded-md border border-border">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-card">
                      <tr className="border-b border-border text-left">
                        <th className="px-2 py-1">Tanggal</th>
                        <th className="px-2 py-1 text-right">Prediksi</th>
                        <th className="px-2 py-1 text-right">Benar</th>
                        <th className="px-2 py-1 text-right">DA%</th>
                        <th className="px-2 py-1 text-right">MAPE%</th>
                        <th className="px-2 py-1 text-right">F1</th>
                        <th className="px-2 py-1 text-right">Ekuitas</th>
                        <th className="px-2 py-1">Regime</th>
                        <th className="px-2 py-1">Engine Terbaik</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.daily_results.slice(-30).reverse().map((d, i) => (
                        <tr key={i} className="border-b border-border/30">
                          <td className="px-2 py-1 font-mono">{d.sim_date}</td>
                          <td className="px-2 py-1 text-right font-mono">{d.n_predictions}</td>
                          <td className="px-2 py-1 text-right font-mono">{d.n_correct}</td>
                          <td className={cn("px-2 py-1 text-right font-mono", DA_COLOR(d.directional_accuracy))}>
                            {d.directional_accuracy.toFixed(1)}%
                          </td>
                          <td className="px-2 py-1 text-right font-mono">{d.avg_mape.toFixed(1)}%</td>
                          <td className="px-2 py-1 text-right font-mono">{d.f1_score.toFixed(3)}</td>
                          <td className="px-2 py-1 text-right font-mono">{(d.equity / 1_000_000).toFixed(2)}Jt</td>
                          <td className={cn("px-2 py-1", REGIME_COLORS[d.regime] || "text-muted-foreground")}>{d.regime}</td>
                          <td className="px-2 py-1 text-[10px]">{d.top_engine}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* Empty state */}
      {loading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-purple-400" />
        </div>
      )}

      {!loading && !report && (!progress || (!progress.running && !progress.done && progress.n_predictions === 0)) && (
        <Card>
          <CardContent className="py-20 text-center">
            <Telescope className="w-12 h-12 text-purple-400 mx-auto mb-4 opacity-50" />
            <p className="text-muted-foreground">Belum ada simulasi prediksi. Klik tombol di atas untuk memulai.</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
