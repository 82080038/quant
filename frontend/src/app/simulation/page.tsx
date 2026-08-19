"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Play,
  SkipForward,
  TrendingUp,
  TrendingDown,
  CheckCircle2,
  XCircle,
  Clock,
  Activity,
  Network,
  Zap,
  ArrowRight,
  RefreshCw,
} from "lucide-react";
import {
  LineChart,
  Line,
  Area,
  AreaChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Legend,
} from "recharts";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SimTicker {
  ticker: string;
  status: "PENDING" | "EXECUTED" | "CLOSED";
  direction: "BUY" | "SELL" | "HOLD";
  entry_price: number;
  current_price: number;
  predicted_pct: number;
  actual_pct: number | null;
  confidence: number;
}

interface PredictionLog {
  date: string;
  ticker: string;
  predicted_direction: "up" | "down" | "flat";
  actual_direction: "up" | "down" | "flat";
  predicted_pct: number;
  actual_pct: number;
  is_correct: boolean;
  confidence: number;
  correct_reason: string;
  error_reason: string;
}

interface CausalNode {
  id: string;
  label: string;
  type: "index" | "commodity" | "fx" | "stock";
}

interface CausalEdge {
  source: string;
  target: string;
  coefficient: number;
  lag_days: number;
  p_value: number;
}

interface InfluenceItem {
  source: string;
  source_change_pct: number;
  target: string;
  expected_impact_pct: number;
  coefficient: number;
}

// ── Mock Data ─────────────────────────────────────────────────────────────────

const MOCK_TICKERS: SimTicker[] = [
  { ticker: "BBCA.JK", status: "EXECUTED", direction: "BUY", entry_price: 8500, current_price: 8620, predicted_pct: 1.5, actual_pct: 1.41, confidence: 7.2 },
  { ticker: "BBRI.JK", status: "EXECUTED", direction: "BUY", entry_price: 5000, current_price: 5080, predicted_pct: 2.0, actual_pct: 1.60, confidence: 6.8 },
  { ticker: "INCO.JK", status: "PENDING", direction: "BUY", entry_price: 7800, current_price: 7800, predicted_pct: 3.2, actual_pct: null, confidence: 6.5 },
  { ticker: "TLKM.JK", status: "EXECUTED", direction: "HOLD", entry_price: 2800, current_price: 2815, predicted_pct: 0.5, actual_pct: 0.54, confidence: 5.0 },
  { ticker: "ADRO.JK", status: "CLOSED", direction: "SELL", entry_price: 2600, current_price: 2540, predicted_pct: -2.5, actual_pct: -2.31, confidence: 7.8 },
  { ticker: "UNTR.JK", status: "PENDING", direction: "BUY", entry_price: 24000, current_price: 24000, predicted_pct: 2.8, actual_pct: null, confidence: 6.2 },
  { ticker: "KLBF.JK", status: "EXECUTED", direction: "BUY", entry_price: 1600, current_price: 1625, predicted_pct: 1.2, actual_pct: 1.56, confidence: 5.5 },
  { ticker: "ASII.JK", status: "CLOSED", direction: "SELL", entry_price: 5200, current_price: 5180, predicted_pct: -1.0, actual_pct: -0.38, confidence: 4.2 },
];

const MOCK_PREDICTION_LOGS: PredictionLog[] = [
  { date: "2026-08-14", ticker: "BBCA.JK", predicted_direction: "up", actual_direction: "up", predicted_pct: 1.50, actual_pct: 1.41, is_correct: true, confidence: 7.2, correct_reason: "Cross-market signal dari S&P500 +1.2% dengan lag 1 hari terkonfirmasi", error_reason: "" },
  { date: "2026-08-14", ticker: "BBRI.JK", predicted_direction: "up", actual_direction: "up", predicted_pct: 2.00, actual_pct: 1.60, is_correct: true, confidence: 6.8, correct_reason: "Momentum positif dari foreign flow net buy Rp 120M", error_reason: "" },
  { date: "2026-08-14", ticker: "TLKM.JK", predicted_direction: "up", actual_direction: "up", predicted_pct: 0.50, actual_pct: 0.54, is_correct: true, confidence: 5.0, correct_reason: "Range-bound sesuai prediksi, volume normal", error_reason: "" },
  { date: "2026-08-14", ticker: "ADRO.JK", predicted_direction: "down", actual_direction: "down", predicted_pct: -2.50, actual_pct: -2.31, is_correct: true, confidence: 7.8, correct_reason: "Coal price drop -3.1% dari ICE futures terkonfirmasi", error_reason: "" },
  { date: "2026-08-14", ticker: "KLBF.JK", predicted_direction: "up", actual_direction: "up", predicted_pct: 1.20, actual_pct: 1.56, is_correct: true, confidence: 5.5, correct_reason: "Sector rotation ke healthcare terkonfirmasi", error_reason: "" },
  { date: "2026-08-14", ticker: "ASII.JK", predicted_direction: "down", actual_direction: "down", predicted_pct: -1.00, actual_pct: -0.38, is_correct: true, confidence: 4.2, correct_reason: "Tren penurunan sesuai prediksi meski magnitude lebih kecil", error_reason: "" },
  { date: "2026-08-13", ticker: "BBCA.JK", predicted_direction: "up", actual_direction: "down", predicted_pct: 0.80, actual_pct: -0.50, is_correct: false, confidence: 6.0, correct_reason: "", error_reason: "Unexpected news: FOMC rate hawkish tidak terprediksi oleh model" },
  { date: "2026-08-13", ticker: "BBRI.JK", predicted_direction: "up", actual_direction: "up", predicted_pct: 1.50, actual_pct: 0.90, is_correct: true, confidence: 7.0, correct_reason: "BI rate hold signal terkonfirmasi, meski magnitude lebih rendah", error_reason: "" },
  { date: "2026-08-13", ticker: "INCO.JK", predicted_direction: "up", actual_direction: "up", predicted_pct: 2.80, actual_pct: 3.10, is_correct: true, confidence: 6.5, correct_reason: "Nickel price surge +4.2% dari LME terkonfirmasi dengan lag 1 hari", error_reason: "" },
  { date: "2026-08-13", ticker: "UNTR.JK", predicted_direction: "up", actual_direction: "flat", predicted_pct: 2.00, actual_pct: 0.10, is_correct: false, confidence: 5.8, correct_reason: "", error_reason: "Q2 earnings miss -18% dari konsensus, model tidak mempertimbangkan earnings calendar" },
];

const MOCK_CAUSAL_NODES: CausalNode[] = [
  { id: "GSPC", label: "S&P 500", type: "index" },
  { id: "N225", label: "Nikkei 225", type: "index" },
  { id: "HSI", label: "Hang Seng", type: "index" },
  { id: "JKSE", label: "IHSG", type: "index" },
  { id: "NICK", label: "Nickel (NICK.L)", type: "commodity" },
  { id: "CL", label: "Crude Oil", type: "commodity" },
  { id: "USIDR", label: "USD/IDR", type: "fx" },
  { id: "BBCA", label: "BBCA.JK", type: "stock" },
  { id: "BBRI", label: "BBRI.JK", type: "stock" },
  { id: "INCO", label: "INCO.JK", type: "stock" },
  { id: "ADRO", label: "ADRO.JK", type: "stock" },
  { id: "UNTR", label: "UNTR.JK", type: "stock" },
];

const MOCK_CAUSAL_EDGES: CausalEdge[] = [
  { source: "GSPC", target: "JKSE", coefficient: 0.52, lag_days: 1, p_value: 0.0001 },
  { source: "N225", target: "JKSE", coefficient: 0.38, lag_days: 1, p_value: 0.003 },
  { source: "HSI", target: "JKSE", coefficient: 0.31, lag_days: 1, p_value: 0.012 },
  { source: "JKSE", target: "BBCA", coefficient: 0.85, lag_days: 0, p_value: 0.0000 },
  { source: "JKSE", target: "BBRI", coefficient: 0.78, lag_days: 0, p_value: 0.0000 },
  { source: "NICK", target: "INCO", coefficient: 0.95, lag_days: 1, p_value: 0.0000 },
  { source: "CL", target: "ADRO", coefficient: 0.68, lag_days: 1, p_value: 0.0002 },
  { source: "CL", target: "UNTR", coefficient: 0.45, lag_days: 2, p_value: 0.008 },
  { source: "USIDR", target: "BBCA", coefficient: -0.42, lag_days: 1, p_value: 0.005 },
  { source: "USIDR", target: "UNTR", coefficient: 0.55, lag_days: 1, p_value: 0.001 },
  { source: "JKSE", target: "INCO", coefficient: 0.62, lag_days: 0, p_value: 0.0001 },
  { source: "GSPC", target: "BBCA", coefficient: 0.35, lag_days: 1, p_value: 0.015 },
];

const MOCK_INFLUENCES: InfluenceItem[] = [
  { source: "S&P 500", source_change_pct: 0.8, target: "IHSG", expected_impact_pct: 0.42, coefficient: 0.52 },
  { source: "Nickel (NICK.L)", source_change_pct: -2.1, target: "INCO.JK", expected_impact_pct: -2.0, coefficient: 0.95 },
  { source: "USD/IDR", source_change_pct: 0.3, target: "Exporters (UNTR, INCO)", expected_impact_pct: 0.17, coefficient: 0.55 },
  { source: "Crude Oil", source_change_pct: -1.5, target: "ADRO.JK", expected_impact_pct: -1.02, coefficient: 0.68 },
  { source: "Hang Seng", source_change_pct: 0.5, target: "IHSG", expected_impact_pct: 0.16, coefficient: 0.31 },
];

// ── Chart Data Generator ──────────────────────────────────────────────────────

function generateChartHistory(ticker: string): Array<{
  date: string;
  actual: number | null;
  predicted: number | null;
  upper: number | null;
  lower: number | null;
}> {
  const basePrice = MOCK_TICKERS.find((t) => t.ticker === ticker)?.entry_price ?? 8500;
  const days = 30;
  const data: Array<{
    date: string;
    actual: number | null;
    predicted: number | null;
    upper: number | null;
    lower: number | null;
  }> = [];
  let price = basePrice * 0.97;
  let pred = basePrice * 0.97;
  const startDate = new Date("2026-07-15");
  for (let i = 0; i < days; i++) {
    const d = new Date(startDate);
    d.setDate(d.getDate() + i);
    const dateStr = d.toISOString().slice(0, 10);
    const noise = (Math.sin(i * 0.3) + Math.cos(i * 0.15)) * basePrice * 0.005;
    price = price + noise + (basePrice * 0.001);
    pred = pred + noise * 0.7 + (basePrice * 0.0012);
    const sigma = basePrice * 0.015;
    const isFuture = i >= days - 5;
    data.push({
      date: dateStr,
      actual: isFuture ? null : Math.round(price),
      predicted: Math.round(pred),
      upper: Math.round(pred + sigma * 2),
      lower: Math.round(pred - sigma * 2),
    });
  }
  return data;
}

// ── Network Graph Component ───────────────────────────────────────────────────

const NODE_COLORS: Record<string, string> = {
  index: "#3b82f6",
  commodity: "#f59e0b",
  fx: "#a855f7",
  stock: "#22c55e",
};

const NODE_POSITIONS: Record<string, { x: number; y: number }> = {
  GSPC: { x: 50, y: 30 },
  N225: { x: 50, y: 80 },
  HSI: { x: 50, y: 130 },
  JKSE: { x: 200, y: 80 },
  NICK: { x: 50, y: 200 },
  CL: { x: 50, y: 260 },
  USIDR: { x: 50, y: 320 },
  BBCA: { x: 350, y: 30 },
  BBRI: { x: 350, y: 90 },
  INCO: { x: 350, y: 170 },
  ADRO: { x: 350, y: 230 },
  UNTR: { x: 350, y: 290 },
};

function CausalGraph({ edges, nodes }: { edges: CausalEdge[]; nodes: CausalNode[] }) {
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);

  return (
    <div className="relative w-full" style={{ height: "380px" }}>
      <svg viewBox="0 0 450 360" className="w-full h-full">
        {/* Edges */}
        {edges.map((edge, i) => {
          const src = NODE_POSITIONS[edge.source];
          const tgt = NODE_POSITIONS[edge.target];
          if (!src || !tgt) return null;
          const midX = (src.x + tgt.x) / 2;
          const midY = (src.y + tgt.y) / 2 - 15;
          const edgeKey = `${edge.source}-${edge.target}`;
          const isHovered = hoveredEdge === edgeKey;
          const thickness = Math.max(1, Math.abs(edge.coefficient) * 4);
          const color = edge.coefficient > 0 ? "#22c55e" : "#ef4444";
          return (
            <g key={i}>
              <path
                d={`M ${src.x} ${src.y} Q ${midX} ${midY} ${tgt.x} ${tgt.y}`}
                fill="none"
                stroke={color}
                strokeWidth={isHovered ? thickness + 1.5 : thickness}
                strokeOpacity={isHovered ? 0.9 : 0.4}
                markerEnd="url(#arrowhead)"
                onMouseEnter={() => setHoveredEdge(edgeKey)}
                onMouseLeave={() => setHoveredEdge(null)}
                style={{ cursor: "pointer" }}
              />
              {isHovered && (
                <text
                  x={midX}
                  y={midY - 5}
                  fill={color}
                  fontSize="10"
                  textAnchor="middle"
                  className="font-mono"
                >
                  coef={edge.coefficient.toFixed(2)}, lag={edge.lag_days}d, p={edge.p_value.toFixed(4)}
                </text>
              )}
            </g>
          );
        })}
        {/* Arrow marker */}
        <defs>
          <marker
            id="arrowhead"
            markerWidth="6"
            markerHeight="4"
            refX="12"
            refY="2"
            orient="auto"
          >
            <polygon points="0 0, 6 2, 0 4" fill="hsl(var(--muted-foreground))" />
          </marker>
        </defs>
        {/* Nodes */}
        {nodes.map((node) => {
          const pos = NODE_POSITIONS[node.id];
          if (!pos) return null;
          const color = NODE_COLORS[node.type] ?? "#888";
          return (
            <g key={node.id}>
              <circle
                cx={pos.x}
                cy={pos.y}
                r="14"
                fill={color}
                fillOpacity="0.2"
                stroke={color}
                strokeWidth="1.5"
              />
              <text
                x={pos.x}
                y={pos.y + 28}
                fill="hsl(var(--foreground))"
                fontSize="9"
                textAnchor="middle"
                className="font-mono"
              >
                {node.label}
              </text>
            </g>
          );
        })}
      </svg>
      {/* Legend */}
      <div className="absolute bottom-0 left-0 flex gap-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-green-500" /> Positif
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-red-500" /> Negatif
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-blue-500" /> Index
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-amber-500" /> Komoditas
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-green-600" /> Saham
        </span>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function SimulationDashboardPage() {
  const [simDate, setSimDate] = useState("2026-08-14");
  const [selectedTicker, setSelectedTicker] = useState("BBCA.JK");
  const [tickers, setTickers] = useState<SimTicker[]>(MOCK_TICKERS);
  const [logs, setLogs] = useState<PredictionLog[]>(MOCK_PREDICTION_LOGS);
  const [advancing, setAdvancing] = useState(false);

  const chartData = useMemo(() => generateChartHistory(selectedTicker), [selectedTicker]);

  const handleAdvanceDate = useCallback(async () => {
    setAdvancing(true);
    // Simulate date advance
    await new Promise((r) => setTimeout(r, 800));
    const d = new Date(simDate);
    d.setDate(d.getDate() + 1);
    setSimDate(d.toISOString().slice(0, 10));
    // Update tickers: PENDING → EXECUTED, fill actual_pct
    setTickers((prev) =>
      prev.map((t) => {
        if (t.status === "PENDING") {
          const actual = t.predicted_pct * (0.7 + Math.random() * 0.6);
          return {
            ...t,
            status: "EXECUTED",
            actual_pct: Math.round(actual * 100) / 100,
            current_price: t.entry_price * (1 + actual / 100),
          };
        }
        if (t.status === "EXECUTED") {
          return { ...t, status: "CLOSED" };
        }
        return t;
      })
    );
    setAdvancing(false);
  }, [simDate]);

  // Stats
  const winRate = logs.filter((l) => l.is_correct).length / logs.length;
  const avgError = logs.reduce((s, l) => s + Math.abs(l.predicted_pct - l.actual_pct), 0) / logs.length;
  const correctCount = logs.filter((l) => l.is_correct).length;

  const statusColors: Record<string, string> = {
    PENDING: "text-yellow-500 bg-yellow-500/10",
    EXECUTED: "text-blue-500 bg-blue-500/10",
    CLOSED: "text-gray-500 bg-gray-500/10",
  };

  const directionIcons: Record<string, React.ReactNode> = {
    BUY: <TrendingUp className="w-3 h-3 text-green-500" />,
    SELL: <TrendingDown className="w-3 h-3 text-red-500" />,
    HOLD: <Activity className="w-3 h-3 text-yellow-500" />,
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Simulasi Trading</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Prediksi vs aktual dengan causal relationship tracking
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-card border border-border">
            <Clock className="w-4 h-4 text-muted-foreground" />
            <span className="text-sm font-mono">{simDate}</span>
          </div>
          <button
            onClick={handleAdvanceDate}
            disabled={advancing}
            className="flex items-center gap-2 px-4 py-1.5 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
          >
            {advancing ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <SkipForward className="w-4 h-4" />
            )}
            Maju 1 Hari
          </button>
        </div>
      </div>

      {/* Aggregate Stats Bar */}
      <div className="grid grid-cols-4 gap-3">
        <Card>
          <CardContent className="py-3">
            <div className="text-xs text-muted-foreground">Win Rate</div>
            <div className="text-xl font-bold text-primary">
              {(winRate * 100).toFixed(1)}%
            </div>
            <div className="text-xs text-muted-foreground">
              {correctCount}/{logs.length} benar
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-3">
            <div className="text-xs text-muted-foreground">Avg Error</div>
            <div className="text-xl font-bold">
              {avgError.toFixed(2)}%
            </div>
            <div className="text-xs text-muted-foreground">|pred - aktual|</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-3">
            <div className="text-xs text-muted-foreground">Ticker Aktif</div>
            <div className="text-xl font-bold">
              {tickers.filter((t) => t.status !== "CLOSED").length}
            </div>
            <div className="text-xs text-muted-foreground">
              {tickers.filter((t) => t.status === "PENDING").length} pending
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-3">
            <div className="text-xs text-muted-foreground">Confidence Avg</div>
            <div className="text-xl font-bold">
              {(tickers.reduce((s, t) => s + t.confidence, 0) / tickers.length).toFixed(1)}/10
            </div>
            <div className="text-xs text-muted-foreground">seluruh sinyal</div>
          </CardContent>
        </Card>
      </div>

      {/* Main Grid: 3 columns */}
      <div className="grid grid-cols-12 gap-4">
        {/* Panel Kiri: Ticker List */}
        <Card className="col-span-3">
          <CardHeader>
            <CardTitle className="text-sm">Ticker Simulasi</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 max-h-[450px] overflow-y-auto">
            {tickers.map((t) => (
              <button
                key={t.ticker}
                onClick={() => setSelectedTicker(t.ticker)}
                className={cn(
                  "w-full flex items-center justify-between px-2.5 py-2 rounded-md text-sm transition-colors text-left",
                  selectedTicker === t.ticker
                    ? "bg-primary/10 border border-primary/30"
                    : "hover:bg-accent border border-transparent"
                )}
              >
                <div className="flex items-center gap-2">
                  {directionIcons[t.direction]}
                  <span className="font-mono font-medium">{t.ticker}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={cn("text-xs px-1.5 py-0.5 rounded font-medium", statusColors[t.status])}>
                    {t.status}
                  </span>
                </div>
              </button>
            ))}
          </CardContent>
        </Card>

        {/* Panel Tengah: Chart Prediksi vs Aktual */}
        <Card className="col-span-6">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">
                Prediksi vs Aktual: {selectedTicker}
              </CardTitle>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="flex items-center gap-1">
                  <span className="w-3 h-0.5 bg-blue-400" /> Prediksi
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-0.5 bg-green-400" /> Aktual
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-3 h-2 bg-blue-400/20" /> ±2σ CI
                </span>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="ciGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.15} />
                    <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis
                  dataKey="date"
                  stroke="hsl(var(--muted-foreground))"
                  fontSize={10}
                  tickFormatter={(v) => v.slice(5)}
                />
                <YAxis
                  stroke="hsl(var(--muted-foreground))"
                  fontSize={10}
                  domain={["auto", "auto"]}
                  tickFormatter={(v) => v.toLocaleString("id-ID", { notation: "compact" })}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                  formatter={(v: number) => v?.toLocaleString("id-ID") ?? "-"}
                />
                <Area
                  type="monotone"
                  dataKey="upper"
                  stroke="none"
                  fill="url(#ciGradient)"
                  fillOpacity={1}
                  name="Upper 2σ"
                />
                <Area
                  type="monotone"
                  dataKey="lower"
                  stroke="none"
                  fill="hsl(var(--card))"
                  fillOpacity={1}
                  name="Lower 2σ"
                />
                <Line
                  type="monotone"
                  dataKey="predicted"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  strokeDasharray="5 3"
                  dot={false}
                  name="Prediksi"
                />
                <Line
                  type="monotone"
                  dataKey="actual"
                  stroke="#22c55e"
                  strokeWidth={2}
                  dot={{ r: 2 }}
                  name="Aktual"
                  connectNulls={false}
                />
              </AreaChart>
            </ResponsiveContainer>

            {/* Selected ticker detail */}
            {(() => {
              const t = tickers.find((x) => x.ticker === selectedTicker);
              if (!t) return null;
              const isCorrect = t.actual_pct !== null && Math.sign(t.predicted_pct) === Math.sign(t.actual_pct);
              return (
                <div className="mt-3 grid grid-cols-5 gap-2 text-xs">
                  <div className="px-2 py-1.5 rounded bg-muted">
                    <div className="text-muted-foreground">Entry</div>
                    <div className="font-mono font-medium">Rp {t.entry_price.toLocaleString("id-ID")}</div>
                  </div>
                  <div className="px-2 py-1.5 rounded bg-muted">
                    <div className="text-muted-foreground">Current</div>
                    <div className="font-mono font-medium">Rp {t.current_price.toLocaleString("id-ID")}</div>
                  </div>
                  <div className="px-2 py-1.5 rounded bg-muted">
                    <div className="text-muted-foreground">Prediksi</div>
                    <div className="font-mono font-medium text-blue-400">
                      {t.predicted_pct >= 0 ? "+" : ""}{t.predicted_pct.toFixed(2)}%
                    </div>
                  </div>
                  <div className="px-2 py-1.5 rounded bg-muted">
                    <div className="text-muted-foreground">Aktual</div>
                    <div className={cn("font-mono font-medium", t.actual_pct === null ? "text-muted-foreground" : isCorrect ? "text-green-500" : "text-red-500")}>
                      {t.actual_pct !== null ? `${t.actual_pct >= 0 ? "+" : ""}${t.actual_pct.toFixed(2)}%` : "—"}
                    </div>
                  </div>
                  <div className="px-2 py-1.5 rounded bg-muted">
                    <div className="text-muted-foreground">Confidence</div>
                    <div className="font-mono font-medium">{t.confidence.toFixed(1)}/10</div>
                  </div>
                </div>
              );
            })()}
          </CardContent>
        </Card>

        {/* Panel Kanan: Causal Graph + Influence Tracker */}
        <div className="col-span-3 space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Network className="w-4 h-4" /> Causal Graph
                </CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              <CausalGraph edges={MOCK_CAUSAL_EDGES} nodes={MOCK_CAUSAL_NODES} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Zap className="w-4 h-4" /> Faktor Penggerak Hari Ini
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="text-xs text-muted-foreground mb-1">
                Tanggal Simulasi: {simDate}
              </div>
              {MOCK_INFLUENCES.map((inf, i) => (
                <div key={i} className="px-2.5 py-2 rounded-md bg-muted/50 border border-border/50">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-mono font-medium">{inf.source}</span>
                    <span className={cn("font-mono", inf.source_change_pct >= 0 ? "text-green-500" : "text-red-500")}>
                      {inf.source_change_pct >= 0 ? "+" : ""}{inf.source_change_pct.toFixed(1)}%
                    </span>
                  </div>
                  <div className="flex items-center gap-1 mt-1 text-xs text-muted-foreground">
                    <ArrowRight className="w-3 h-3" />
                    <span>{inf.target}</span>
                    <span className="ml-auto font-mono">
                      Exp: {inf.expected_impact_pct >= 0 ? "+" : ""}{inf.expected_impact_pct.toFixed(2)}%
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    coef={inf.coefficient.toFixed(2)}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Panel Bawah: Prediction Scorecard Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Prediction Scorecard</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="text-left py-2 px-2 font-medium">Tanggal</th>
                  <th className="text-left py-2 px-2 font-medium">Ticker</th>
                  <th className="text-left py-2 px-2 font-medium">Pred. Arah</th>
                  <th className="text-left py-2 px-2 font-medium">Aktual Arah</th>
                  <th className="text-right py-2 px-2 font-medium">Prediksi %</th>
                  <th className="text-right py-2 px-2 font-medium">Aktual %</th>
                  <th className="text-center py-2 px-2 font-medium">Status</th>
                  <th className="text-right py-2 px-2 font-medium">Confidence</th>
                  <th className="text-left py-2 px-2 font-medium">Alasan</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log, i) => (
                  <tr
                    key={i}
                    className="border-b border-border/50 hover:bg-accent/30 transition-colors"
                  >
                    <td className="py-2 px-2 font-mono text-xs">{log.date}</td>
                    <td className="py-2 px-2 font-mono font-medium">{log.ticker}</td>
                    <td className="py-2 px-2">
                      <span className={cn(
                        "text-xs font-medium",
                        log.predicted_direction === "up" ? "text-green-500" :
                        log.predicted_direction === "down" ? "text-red-500" : "text-yellow-500"
                      )}>
                        {log.predicted_direction.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 px-2">
                      <span className={cn(
                        "text-xs font-medium",
                        log.actual_direction === "up" ? "text-green-500" :
                        log.actual_direction === "down" ? "text-red-500" : "text-yellow-500"
                      )}>
                        {log.actual_direction.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-2 px-2 text-right font-mono">
                      {log.predicted_pct >= 0 ? "+" : ""}{log.predicted_pct.toFixed(2)}%
                    </td>
                    <td className="py-2 px-2 text-right font-mono">
                      {log.actual_pct >= 0 ? "+" : ""}{log.actual_pct.toFixed(2)}%
                    </td>
                    <td className="py-2 px-2 text-center">
                      {log.is_correct ? (
                        <CheckCircle2 className="w-4 h-4 text-green-500 inline" />
                      ) : (
                        <XCircle className="w-4 h-4 text-red-500 inline" />
                      )}
                    </td>
                    <td className="py-2 px-2 text-right font-mono">{log.confidence.toFixed(1)}</td>
                    <td className="py-2 px-2 text-xs text-muted-foreground max-w-xs truncate" title={log.is_correct ? log.correct_reason : log.error_reason}>
                      {log.is_correct ? log.correct_reason : log.error_reason}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
