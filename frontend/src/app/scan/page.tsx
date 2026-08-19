"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  Scan,
  Brain,
  Terminal,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Loader2,
  Activity,
  Zap,
  BookOpen,
  ShieldAlert,
  Ban,
  AlertTriangle,
  FileWarning,
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Area,
  AreaChart,
} from "recharts";

interface LogEntry {
  timestamp: string;
  level: string;
  ticker: string;
  message: string;
  data: Record<string, unknown>;
}

interface PatternResult {
  pattern_type: string;
  direction: string;
  confidence: number;
  price_at_detection: number;
  key_levels: Record<string, number>;
  description: string;
  indicators_snapshot: Record<string, number>;
}

interface PredictionResult {
  ticker: string;
  as_of: string;
  method: string;
  predicted_price: number;
  predicted_direction: string;
  predicted_return_pct: number;
  confidence: number;
  horizon_days: number;
  indicators_used: Record<string, number>;
  pattern_signals: string[];
  rationale: string;
}

interface PredictionError {
  error_id: string;
  ticker: string;
  as_of: string;
  method: string;
  predicted_price: number;
  actual_price: number;
  predicted_direction: string;
  actual_direction: string;
  error_pct: number;
  direction_correct: boolean;
  error_category: string;
  root_cause: string;
  lesson: string;
  risk_weight: number;
}

interface ErrorSummary {
  total_errors: number;
  by_category: Record<string, number>;
  avg_error_pct: number;
  direction_accuracy: number;
  avg_risk_weight: number;
  risk_adjustment: number | Record<string, unknown>;
  recent_lessons: string[];
}

type Tab = "scan" | "predict" | "errors" | "delisting";

interface DelistingRecord {
  record_id: string;
  ticker: string;
  exchange: string;
  status: string;
  reason: string;
  event_date: string;
  last_price: number;
  price_decline_pct: number;
  lesson: string;
  risk_score: number;
  sector: string;
  warning_patterns: Array<{ type: string; description: string; severity: number }>;
}

interface DelistingCheck {
  ticker: string;
  is_blocked: boolean;
  is_suspended: boolean;
  record: DelistingRecord | null;
}

interface DelistingSummary {
  total_records: number;
  by_status: Record<string, number>;
  by_reason: Record<string, number>;
  total_reminders: number;
  critical_reminders: number;
}

const DIRECTION_ICONS: Record<string, typeof TrendingUp> = {
  up: TrendingUp,
  down: TrendingDown,
  flat: Minus,
  bullish: TrendingUp,
  bearish: TrendingDown,
  neutral: Minus,
};

const LEVEL_COLORS: Record<string, string> = {
  info: "text-blue-400",
  warn: "text-yellow-400",
  error: "text-red-400",
  detect: "text-green-400",
  predict: "text-purple-400",
  verify: "text-cyan-400",
};

export default function PatternPredictionPage() {
  const [tab, setTab] = useState<Tab>("scan");
  const [ticker, setTicker] = useState("BBCA.JK");
  const [asOf, setAsOf] = useState("");
  const [method, setMethod] = useState("ensemble");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logEntries, setLogEntries] = useState<LogEntry[]>([]);
  const [patterns, setPatterns] = useState<PatternResult[]>([]);
  const [prediction, setPrediction] = useState<PredictionResult | null>(null);
  const [verifyResult, setVerifyResult] = useState<PredictionError | null>(null);
  const [errorSummary, setErrorSummary] = useState<ErrorSummary | null>(null);
  const [chartData, setChartData] = useState<Array<Record<string, number | string>>>([]);
  const [riskAdjustment, setRiskAdjustment] = useState<number | null>(null);
  const [delistingSummary, setDelistingSummary] = useState<DelistingSummary | null>(null);
  const [delistingCheck, setDelistingCheck] = useState<DelistingCheck | null>(null);
  const [delistingRecords, setDelistingRecords] = useState<DelistingRecord[]>([]);
  const [delistingLessons, setDelistingLessons] = useState<Array<Record<string, unknown>>>([]);
  const terminalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [logEntries]);

  const generateMockOHLCV = useCallback(() => {
    const n = 200;
    const dates: string[] = [];
    const opens: number[] = [];
    const highs: number[] = [];
    const lows: number[] = [];
    const closes: number[] = [];
    const volumes: number[] = [];

    let price = 8000;
    // Use deterministic seed
    let seed = 42;
    const rng = () => {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      return seed / 0x7fffffff;
    };

    const start = new Date("2023-06-01");
    for (let i = 0; i < n; i++) {
      const d = new Date(start);
      d.setDate(d.getDate() + i + Math.floor(i / 5) * 2); // skip weekends roughly
      dates.push(d.toISOString().split("T")[0]);

      const change = (rng() - 0.48) * 100;
      price += change;
      const open = price - (rng() - 0.5) * 20;
      const close = price;
      const high = Math.max(open, close) + rng() * 30;
      const low = Math.min(open, close) - rng() * 30;
      const vol = 100000 + rng() * 900000;

      opens.push(Math.round(open * 100) / 100);
      highs.push(Math.round(high * 100) / 100);
      lows.push(Math.round(low * 100) / 100);
      closes.push(Math.round(close * 100) / 100);
      volumes.push(Math.round(vol));
    }

    return { date: dates, open: opens, high: highs, low: lows, close: closes, volume: volumes };
  }, []);

  const buildChartData = (ohlcv: Record<string, number[] | string[]>) => {
    const dates = ohlcv.date as string[];
    const closes = ohlcv.close as number[];
    const data: Array<Record<string, number | string>> = [];
    for (let i = 0; i < dates.length; i++) {
      data.push({ date: dates[i], close: closes[i] });
    }
    setChartData(data);
  };

  const runScan = async () => {
    setLoading(true);
    setError(null);
    setLogEntries([]);
    setPatterns([]);
    const ohlcv = generateMockOHLCV();
    buildChartData(ohlcv);

    try {
      const res = await fetch("/api/pattern/detect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, ohlcv, as_of: asOf || undefined }),
      });
      if (!res.ok) throw new Error("Gagal deteksi pola");
      const data = await res.json();
      setPatterns(data.patterns || []);
      setLogEntries(data.log || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  const runPredict = async () => {
    setLoading(true);
    setError(null);
    setLogEntries([]);
    setPrediction(null);
    setVerifyResult(null);
    const ohlcv = generateMockOHLCV();
    buildChartData(ohlcv);

    try {
      const res = await fetch("/api/prediction/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker,
          ohlcv,
          as_of: asOf || undefined,
          method,
        }),
      });
      if (!res.ok) throw new Error("Gagal prediksi");
      const data = await res.json();
      setPrediction(data.prediction);
      setLogEntries(data.log || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  const runVerify = async () => {
    setLoading(true);
    setError(null);
    setLogEntries([]);
    setVerifyResult(null);
    const ohlcv = generateMockOHLCV();

    try {
      const asOfDate = asOf || (ohlcv.date as string[])[Math.floor((ohlcv.date as string[]).length * 0.8)];
      const res = await fetch("/api/prediction/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, ohlcv, as_of: asOfDate }),
      });
      if (!res.ok) throw new Error("Gagal verifikasi");
      const data = await res.json();
      setVerifyResult(data.error);
      setLogEntries(data.log || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  const fetchErrors = useCallback(async () => {
    try {
      const res = await fetch("/api/prediction/errors");
      if (!res.ok) return;
      const data = await res.json();
      setErrorSummary(data);
    } catch {
      // ignore
    }
  }, []);

  const fetchRisk = useCallback(async () => {
    try {
      const res = await fetch(`/api/prediction/risk/${ticker}`);
      if (!res.ok) return;
      const data = await res.json();
      setRiskAdjustment(typeof data.risk_adjustment === "number" ? data.risk_adjustment : null);
    } catch {
      // ignore
    }
  }, [ticker]);

  const fetchDelistingData = useCallback(async () => {
    try {
      const [sumRes, recRes, lesRes] = await Promise.all([
        fetch("/api/delisting/summary"),
        fetch("/api/delisting/records"),
        fetch("/api/delisting/lessons"),
      ]);
      if (sumRes.ok) setDelistingSummary(await sumRes.json());
      if (recRes.ok) {
        const recData = await recRes.json();
        setDelistingRecords(recData.records || []);
      }
      if (lesRes.ok) {
        const lesData = await lesRes.json();
        setDelistingLessons(lesData.lessons || []);
      }
    } catch {
      // ignore
    }
  }, []);

  const checkDelisting = useCallback(async () => {
    try {
      const res = await fetch(`/api/delisting/check/${ticker}`);
      if (!res.ok) return;
      const data = await res.json();
      setDelistingCheck(data);
    } catch {
      // ignore
    }
  }, [ticker]);

  useEffect(() => {
    if (tab === "errors") {
      void fetchErrors();
      void fetchRisk();
    }
    if (tab === "delisting") {
      void fetchDelistingData();
      void checkDelisting();
    }
  }, [tab, fetchErrors, fetchRisk, fetchDelistingData, checkDelisting]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Scan className="w-6 h-6 text-primary" />
          Pengecekan Pola & Prediksi
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          Deteksi pola chart dan prediksi harga tanpa look-ahead bias.
          Setiap error prediksi dianalisis root cause-nya, disimpan sebagai
          faktor risiko, dan dipelajari untuk keputusan eksekusi yang lebih bijak.
        </p>
      </div>

      {/* No look-ahead warning banner */}
      <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-4">
        <div className="flex items-start gap-3">
          <ShieldAlert className="w-5 h-5 text-amber-500 mt-0.5 flex-shrink-0" />
          <div className="text-sm space-y-1">
            <p className="font-medium text-amber-600 dark:text-amber-400">
              No Look-Ahead Bias Protection
            </p>
            <p className="text-muted-foreground">
              Semua deteksi pola dan prediksi hanya menggunakan data hingga tanggal
              <code className="mx-1 px-1 py-0.5 rounded bg-muted text-xs">as_of</code>
              — tidak boleh melihat data di depan tanggal tersebut. Error prediksi
              dianalisis dan disimpan sebagai memory risiko.
            </p>
          </div>
        </div>
      </div>

      {/* Controls */}
      <Card>
        <CardHeader><CardTitle className="text-sm">Konfigurasi</CardTitle></CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-4 items-end">
            <div className="flex-1 min-w-[160px]">
              <label className="text-sm font-medium block mb-1">Ticker</label>
              <input
                type="text"
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder="BBCA.JK"
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm"
              />
            </div>
            <div className="flex-1 min-w-[160px]">
              <label className="text-sm font-medium block mb-1">As Of (tanggal cek)</label>
              <input
                type="date"
                value={asOf}
                onChange={(e) => setAsOf(e.target.value)}
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm"
              />
            </div>
            <div className="min-w-[160px]">
              <label className="text-sm font-medium block mb-1">Metode Prediksi</label>
              <select
                value={method}
                onChange={(e) => setMethod(e.target.value)}
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm"
              >
                <option value="ensemble">Ensemble</option>
                <option value="ma_based">MA-Based</option>
                <option value="momentum">Momentum</option>
                <option value="pattern_based">Pattern-Based</option>
                <option value="volatility_adjusted">Volatility-Adjusted</option>
              </select>
            </div>
          </div>

          {/* Tab buttons */}
          <div className="flex gap-2 mt-4">
            <button
              onClick={() => setTab("scan")}
              className={`px-4 py-2 rounded-md text-sm font-medium flex items-center gap-2 ${
                tab === "scan" ? "bg-primary text-primary-foreground" : "border border-border hover:bg-accent"
              }`}
            >
              <Scan className="w-4 h-4" /> Deteksi Pola
            </button>
            <button
              onClick={() => setTab("predict")}
              className={`px-4 py-2 rounded-md text-sm font-medium flex items-center gap-2 ${
                tab === "predict" ? "bg-primary text-primary-foreground" : "border border-border hover:bg-accent"
              }`}
            >
              <Brain className="w-4 h-4" /> Prediksi
            </button>
            <button
              onClick={() => setTab("errors")}
              className={`px-4 py-2 rounded-md text-sm font-medium flex items-center gap-2 ${
                tab === "errors" ? "bg-primary text-primary-foreground" : "border border-border hover:bg-accent"
              }`}
            >
              <AlertCircle className="w-4 h-4" /> Error Memory
            </button>
            <button
              onClick={() => setTab("delisting")}
              className={`px-4 py-2 rounded-md text-sm font-medium flex items-center gap-2 ${
                tab === "delisting" ? "bg-primary text-primary-foreground" : "border border-border hover:bg-accent"
              }`}
            >
              <Ban className="w-4 h-4" /> Delisting Memory
            </button>
          </div>
        </CardContent>
      </Card>

      {/* Action buttons */}
      <div className="flex gap-3">
        {tab === "scan" && (
          <button
            onClick={runScan}
            disabled={loading}
            className="px-6 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 flex items-center gap-2"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Scan className="w-4 h-4" />}
            Jalankan Deteksi Pola
          </button>
        )}
        {tab === "predict" && (
          <>
            <button
              onClick={runPredict}
              disabled={loading}
              className="px-6 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 flex items-center gap-2"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Brain className="w-4 h-4" />}
              Jalankan Prediksi
            </button>
            <button
              onClick={runVerify}
              disabled={loading}
              className="px-6 py-2 rounded-md border border-border text-sm font-medium hover:bg-accent disabled:opacity-50 flex items-center gap-2"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle2 className="w-4 h-4" />}
              Verifikasi & Track Error
            </button>
          </>
        )}
      </div>

      {/* Chart */}
      {chartData.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="w-4 h-4" />
              Chart Harga {ticker}
              {asOf && (
                <span className="text-xs text-muted-foreground ml-2">
                  cutoff: {asOf}
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#8884d8" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#8884d8" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10 }}
                  interval={Math.max(1, Math.floor(chartData.length / 10))}
                />
                <YAxis tick={{ fontSize: 10 }} domain={["auto", "auto"]} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--popover))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "4px",
                    fontSize: "12px",
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="close"
                  stroke="#8884d8"
                  fill="url(#priceGradient)"
                  strokeWidth={1.5}
                />
                {asOf && (
                  <ReferenceLine
                    x={asOf}
                    stroke="#f59e0b"
                    strokeWidth={2}
                    strokeDasharray="5 5"
                    label={{ value: "as_of", fontSize: 10, fill: "#f59e0b" }}
                  />
                )}
                {prediction && (
                  <ReferenceLine
                    y={prediction.predicted_price}
                    stroke="#8b5cf6"
                    strokeWidth={2}
                    strokeDasharray="3 3"
                    label={{ value: `pred: ${prediction.predicted_price}`, fontSize: 10, fill: "#8b5cf6" }}
                  />
                )}
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Terminal Output */}
      {logEntries.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Terminal className="w-4 h-4 text-green-500" />
              Terminal Output
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div
              ref={terminalRef}
              className="bg-black/90 dark:bg-black/60 rounded-md p-4 font-mono text-xs h-64 overflow-y-auto space-y-0.5"
            >
              {logEntries.map((entry, i) => {
                const color = LEVEL_COLORS[entry.level] || "text-gray-400";
                const time = entry.timestamp.split("T")[1]?.split(".")[0] || "";
                return (
                  <div key={i} className="flex gap-2">
                    <span className="text-gray-600 flex-shrink-0">{time}</span>
                    <span className={`flex-shrink-0 font-bold uppercase ${color}`}>
                      [{entry.level}]
                    </span>
                    <span className="text-cyan-300 flex-shrink-0">{entry.ticker}</span>
                    <span className="text-gray-300">{entry.message}</span>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Scan Results */}
      {tab === "scan" && patterns.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Scan className="w-4 h-4 text-green-500" />
              Pola Terdeteksi ({patterns.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {patterns.map((p, i) => {
                const DirIcon = DIRECTION_ICONS[p.direction] || Minus;
                const dirColor =
                  p.direction === "bullish" ? "text-green-500" :
                  p.direction === "bearish" ? "text-red-500" :
                  "text-yellow-500";
                return (
                  <div key={i} className="rounded-md border border-border p-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <DirIcon className={`w-4 h-4 ${dirColor}`} />
                        <span className="font-medium capitalize">
                          {p.pattern_type.replace(/_/g, " ")}
                        </span>
                        <span className={`text-xs ${dirColor} capitalize`}>{p.direction}</span>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        confidence: {(p.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    <p className="text-sm mt-1 text-muted-foreground">{p.description}</p>
                    <div className="flex flex-wrap gap-2 mt-2">
                      {Object.entries(p.key_levels).map(([k, v]) => (
                        <span key={k} className="px-2 py-0.5 rounded text-xs bg-muted text-muted-foreground">
                          {k}: {typeof v === "number" ? v.toFixed(2) : v}
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Prediction Result */}
      {tab === "predict" && prediction && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Brain className="w-4 h-4 text-purple-500" />
                Hasil Prediksi
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                  <p className="text-muted-foreground text-xs">Predicted Price</p>
                  <p className="text-xl font-bold">{prediction.predicted_price.toFixed(2)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground text-xs">Direction</p>
                  <p className="text-xl font-bold flex items-center gap-1">
                    {(() => {
                      const Icon = DIRECTION_ICONS[prediction.predicted_direction] || Minus;
                      const color =
                        prediction.predicted_direction === "up" ? "text-green-500" :
                        prediction.predicted_direction === "down" ? "text-red-500" :
                        "text-yellow-500";
                      return <Icon className={`w-5 h-5 ${color}`} />;
                    })()}
                    <span className="capitalize">{prediction.predicted_direction}</span>
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground text-xs">Return %</p>
                  <p className={`text-xl font-bold ${prediction.predicted_return_pct >= 0 ? "text-green-500" : "text-red-500"}`}>
                    {prediction.predicted_return_pct >= 0 ? "+" : ""}{prediction.predicted_return_pct.toFixed(2)}%
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground text-xs">Confidence</p>
                  <p className="text-xl font-bold">{(prediction.confidence * 100).toFixed(0)}%</p>
                </div>
              </div>
              <div className="mt-4 space-y-2 text-sm">
                <p className="text-muted-foreground">
                  <span className="font-medium">Method:</span> {prediction.method}
                </p>
                <p className="text-muted-foreground">
                  <span className="font-medium">Horizon:</span> {prediction.horizon_days} days
                </p>
                <p className="text-muted-foreground">
                  <span className="font-medium">Rationale:</span> {prediction.rationale}
                </p>
                {prediction.pattern_signals.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-2">
                    {prediction.pattern_signals.map((s, i) => (
                      <span key={i} className="px-2 py-0.5 rounded text-xs bg-purple-500/20 text-purple-500">
                        {s.replace(/_/g, " ")}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Verification Result */}
          {verifyResult && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  {verifyResult.direction_correct ? (
                    <CheckCircle2 className="w-4 h-4 text-green-500" />
                  ) : (
                    <XCircle className="w-4 h-4 text-red-500" />
                  )}
                  Verifikasi Prediksi
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                    <div>
                      <p className="text-muted-foreground text-xs">Predicted</p>
                      <p className="font-medium">{verifyResult.predicted_price.toFixed(2)}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground text-xs">Actual</p>
                      <p className="font-medium">{verifyResult.actual_price.toFixed(2)}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground text-xs">Error %</p>
                      <p className={`font-medium ${verifyResult.error_pct > 5 ? "text-red-500" : "text-yellow-500"}`}>
                        {verifyResult.error_pct.toFixed(2)}%
                      </p>
                    </div>
                    <div>
                      <p className="text-muted-foreground text-xs">Direction</p>
                      <p className={`font-medium ${verifyResult.direction_correct ? "text-green-500" : "text-red-500"}`}>
                        {verifyResult.direction_correct ? "✓ Correct" : "✗ Wrong"}
                      </p>
                    </div>
                  </div>

                  {!verifyResult.direction_correct && (
                    <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 space-y-2">
                      <div className="flex items-center gap-2">
                        <AlertCircle className="w-4 h-4 text-red-500" />
                        <span className="font-medium text-sm text-red-500">
                          Root Cause: {verifyResult.error_category.replace(/_/g, " ")}
                        </span>
                      </div>
                      <p className="text-sm text-muted-foreground">{verifyResult.root_cause}</p>
                      <div className="flex items-start gap-2 pt-2 border-t border-border/50">
                        <BookOpen className="w-4 h-4 text-blue-500 mt-0.5 flex-shrink-0" />
                        <div>
                          <p className="text-xs font-medium text-blue-500">Lesson (Risk Memory):</p>
                          <p className="text-sm text-muted-foreground mt-0.5">{verifyResult.lesson}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 pt-1">
                        <Zap className="w-4 h-4 text-yellow-500" />
                        <span className="text-xs text-muted-foreground">
                          Risk Weight: {verifyResult.risk_weight.toFixed(3)} —
                          akan mengurangi ukuran posisi untuk {ticker} di masa depan
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Error Memory Tab */}
      {tab === "errors" && (
        <div className="space-y-4">
          {errorSummary && (
            <>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <Card>
                  <CardHeader><CardTitle className="text-sm">Total Errors</CardTitle></CardHeader>
                  <CardContent>
                    <p className="text-2xl font-bold">{errorSummary.total_errors}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-sm">Direction Accuracy</CardTitle></CardHeader>
                  <CardContent>
                    <p className="text-2xl font-bold">
                      {((errorSummary.direction_accuracy || 0) * 100).toFixed(0)}%
                    </p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-sm">Avg Error %</CardTitle></CardHeader>
                  <CardContent>
                    <p className="text-2xl font-bold">{errorSummary.avg_error_pct?.toFixed(2) || "0"}%</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-sm">Risk Adjustment</CardTitle></CardHeader>
                  <CardContent>
                    <p className="text-2xl font-bold">
                      {riskAdjustment !== null ? `${(riskAdjustment * 100).toFixed(0)}%` : "—"}
                    </p>
                    <p className="text-xs text-muted-foreground">position size multiplier</p>
                  </CardContent>
                </Card>
              </div>

              {errorSummary.by_category && Object.keys(errorSummary.by_category).length > 0 && (
                <Card>
                  <CardHeader><CardTitle className="text-sm">Error by Category</CardTitle></CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {Object.entries(errorSummary.by_category).map(([cat, count]) => (
                        <div key={cat} className="flex items-center justify-between text-sm">
                          <span className="capitalize">{cat.replace(/_/g, " ")}</span>
                          <span className="font-medium">{count}</span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {errorSummary.recent_lessons && errorSummary.recent_lessons.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <BookOpen className="w-4 h-4 text-blue-500" />
                      Lessons Learned (Risk Memory)
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-3">
                      {errorSummary.recent_lessons.map((lesson, i) => (
                        <div key={i} className="rounded-md border border-border p-3">
                          <p className="text-sm text-muted-foreground">{lesson}</p>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </>
          )}

          {!errorSummary?.total_errors && (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-12">
                <CheckCircle2 className="w-12 h-12 text-green-500 mb-3" />
                <p className="text-muted-foreground text-sm">
                  Belum ada error prediksi yang tercatat. Jalankan prediksi dan verifikasi
                  untuk membangun risk memory.
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Delisting Memory Tab */}
      {tab === "delisting" && (
        <div className="space-y-4">
          {/* Ticker check */}
          {delistingCheck && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <FileWarning className="w-4 h-4 text-yellow-500" />
                  Cek Status: {ticker}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {delistingCheck.is_blocked ? (
                  <div className="rounded-md border border-red-500/30 bg-red-500/5 p-4 flex items-start gap-3">
                    <Ban className="w-5 h-5 text-red-500 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="font-medium text-red-500">INSTRUMENT BLOCKED/DELISTED</p>
                      {delistingCheck.record && (
                        <>
                          <p className="text-sm text-muted-foreground mt-1">
                            Reason: {delistingCheck.record.reason.replace(/_/g, " ")}
                          </p>
                          <p className="text-sm text-muted-foreground mt-1">
                            Lesson: {delistingCheck.record.lesson}
                          </p>
                        </>
                      )}
                    </div>
                  </div>
                ) : delistingCheck.is_suspended ? (
                  <div className="rounded-md border border-yellow-500/30 bg-yellow-500/5 p-4 flex items-start gap-3">
                    <AlertTriangle className="w-5 h-5 text-yellow-500 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="font-medium text-yellow-500">INSTRUMENT SUSPENDED</p>
                      {delistingCheck.record && (
                        <p className="text-sm text-muted-foreground mt-1">
                          Reason: {delistingCheck.record.reason.replace(/_/g, " ")}
                        </p>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-md border border-green-500/30 bg-green-500/5 p-4 flex items-center gap-3">
                    <CheckCircle2 className="w-5 h-5 text-green-500" />
                    <p className="text-sm text-green-600 dark:text-green-400">
                      {ticker} tidak ada dalam daftar delisted/suspended/blocked.
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Summary cards */}
          {delistingSummary && (
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <Card>
                <CardHeader><CardTitle className="text-sm">Total Records</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-2xl font-bold">{delistingSummary.total_records}</p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="text-sm">Delisted</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-2xl font-bold text-red-500">
                    {delistingSummary.by_status?.delisted || 0}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="text-sm">Suspended</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-2xl font-bold text-yellow-500">
                    {delistingSummary.by_status?.suspended || 0}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle className="text-sm">Blocked by AI</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-2xl font-bold text-orange-500">
                    {delistingSummary.by_status?.blocked || 0}
                  </p>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Records list */}
          {delistingRecords.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Ban className="w-4 h-4 text-red-500" />
                  Instrumen Delisted/Suspended/Blocked
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {delistingRecords.map((rec) => {
                    const statusColor =
                      rec.status === "delisted" ? "text-red-500" :
                      rec.status === "suspended" ? "text-yellow-500" :
                      rec.status === "blocked" ? "text-orange-500" :
                      "text-muted-foreground";
                    return (
                      <div key={rec.record_id} className="rounded-md border border-border p-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Ban className={`w-4 h-4 ${statusColor}`} />
                            <span className="font-medium">{rec.ticker}</span>
                            <span className={`text-xs capitalize ${statusColor}`}>{rec.status}</span>
                            <span className="text-xs text-muted-foreground capitalize">
                              {rec.reason.replace(/_/g, " ")}
                            </span>
                          </div>
                          <span className="text-xs text-muted-foreground">
                            risk: {(rec.risk_score * 100).toFixed(0)}%
                          </span>
                        </div>
                        <p className="text-sm mt-1 text-muted-foreground">{rec.lesson}</p>
                        {rec.warning_patterns.length > 0 && (
                          <div className="flex flex-wrap gap-2 mt-2">
                            {rec.warning_patterns.map((w, i) => (
                              <span
                                key={i}
                                className={`px-2 py-0.5 rounded text-xs ${
                                  w.severity >= 0.7
                                    ? "bg-red-500/20 text-red-500"
                                    : w.severity >= 0.4
                                    ? "bg-yellow-500/20 text-yellow-500"
                                    : "bg-muted text-muted-foreground"
                                }`}
                              >
                                {w.type.replace(/_/g, " ")}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          )}

          {/* AI Lessons */}
          {delistingLessons.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <BookOpen className="w-4 h-4 text-blue-500" />
                  AI Lessons (Delisting Memory → Self-Evolution)
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {delistingLessons.map((lesson, i) => (
                    <div key={i} className="rounded-md border border-border p-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium text-sm">
                          {lesson.ticker as string}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          risk: {((lesson.risk_score as number) * 100).toFixed(0)}%
                        </span>
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {lesson.lesson as string}
                      </p>
                      {Array.isArray(lesson.warning_patterns) && lesson.warning_patterns.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {(lesson.warning_patterns as string[]).map((p, j) => (
                            <span key={j} className="px-1.5 py-0.5 rounded text-xs bg-muted text-muted-foreground">
                              {p.replace(/_/g, " ")}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Empty state */}
          {!delistingSummary?.total_records && (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-12">
                <CheckCircle2 className="w-12 h-12 text-green-500 mb-3" />
                <p className="text-muted-foreground text-sm">
                  Belum ada catatan delisting/suspension. Instrumen yang pernah delisted
                  akan dicatat di sini sebagai pengingat AI untuk menghindari pola serupa.
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3">
          <p className="text-sm text-destructive">{error}</p>
        </div>
      )}
    </div>
  );
}
