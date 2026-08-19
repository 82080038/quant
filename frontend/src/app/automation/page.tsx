"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Bot,
  ShieldCheck,
  AlertTriangle,
  Zap,
  FileCheck2,
  Loader2,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  TrendingUp,
} from "lucide-react";

interface GateRule {
  rule_id: string;
  description: string;
  status: "pass" | "fail" | "warning";
  detail: string;
  is_blocking: boolean;
}

interface GateResult {
  passed: boolean;
  rules: GateRule[];
  blocking_count: number;
  warning_count: number;
  summary: string;
}

interface PlanOrder {
  ticker: string;
  side: string;
  shares: number;
  price: number;
  source: string;
  confidence: number;
  readiness_level: string;
  risk_score: number;
  stop_loss: number;
  take_profit: number;
}

interface ExecutionPlan {
  plan_id: string;
  created_at: string;
  status: string;
  orders: PlanOrder[];
  total_value: number;
  total_risk: number;
  passed_count: number;
  rejected_count: number;
  rejection_reasons: string[];
  summary: string;
}

interface ExecutionResult {
  plan_id: string;
  executed_at: string;
  results: {
    ticker: string;
    side: string;
    shares: number;
    price: number;
    status: string;
    fill_price: number;
    commission: number;
    sales_tax: number;
    rejection_reason: string | null;
    order_id: string | null;
  }[];
  filled_count: number;
  rejected_count: number;
  total_commission: number;
  total_sales_tax: number;
  total_value: number;
  summary: string;
}

interface LeverageRecommendation {
  ticker: string;
  recommended_leverage: number;
  level: string;
  theoretical_kelly_leverage: number;
  asset_class_max: number;
  user_max: number;
  haircuts: { name: string; factor: number; detail: string }[];
  rationale: string;
  warnings: string[];
  conditions: string[];
  margin_required: number;
  liquidation_price: number;
  max_loss_at_leverage: number;
  effective_capital: number;
  leveraged_position_value: number;
  can_apply: boolean;
  rejection_reason: string | null;
}

interface AutomationState {
  config: {
    enabled_sources: string[];
    market_scope: string[];
    execution_mode: string;
    min_confidence: number;
    max_orders_per_session: number;
    max_value_per_session: number;
    auto_sell: boolean;
    auto_rebalance: boolean;
    confirmed_paper_30d: boolean;
    confirmed_risk_understood: boolean;
    confirmed_risk_limits: boolean;
  } | null;
  gate_result: GateResult | null;
  last_plan: ExecutionPlan | null;
  last_execution: ExecutionResult | null;
  available_sources: string[];
  available_scopes: string[];
  available_modes: string[];
}

const SIGNAL_SOURCES: { value: string; label: string; desc: string }[] = [
  { value: "screening_ai", label: "Screening AI/ML", desc: "Hasil screening dari engine AI/ML" },
  { value: "model_prediction", label: "Prediksi Model (LSTM/Ensemble)", desc: "Sinyal dari model prediksi harga" },
  { value: "advisory_recommendation", label: "Rekomendasi Advisory", desc: "Composite scoring dari AdvisoryEngine" },
  { value: "pattern_signal", label: "Sinyal Pola (Pattern Memory)", desc: "Pola historis dengan win-rate tinggi" },
  { value: "backtest_signal", label: "Sinyal Backtest", desc: "Sinyal dari strategi backtest terbaik" },
  { value: "walk_forward_signal", label: "Sinyal Walk-Forward", desc: "Sinyal dari walk-forward validation" },
];

const MARKET_SCOPES: { value: string; label: string; desc: string }[] = [
  { value: "idx", label: "Instrumen Indonesia (IDX)", desc: "Saham, ETF, obligasi di Bursa Efek Indonesia" },
  { value: "global", label: "Instrumen Pasar Global", desc: "Saham US, ETF internasional, komoditas global" },
  { value: "multi_asset", label: "Multi-Asset", desc: "Komoditas, forex, crypto, derivatif" },
];

const EXECUTION_MODES: { value: string; label: string; desc: string; color: string }[] = [
  { value: "manual", label: "Manual", desc: "Plan dibuat, user eksekusi sendiri", color: "text-blue-400" },
  { value: "semi_auto", label: "Semi-Auto", desc: "Plan dibuat & dieksekusi, user konfirmasi dulu", color: "text-yellow-400" },
  { value: "full_auto", label: "Full-Auto", desc: "Plan dibuat & dieksekusi otomatis tanpa konfirmasi", color: "text-red-400" },
];

export default function AutomationPage() {
  const [state, setState] = useState<AutomationState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRules, setExpandedRules] = useState(false);

  // Local form state
  const [enabledSources, setEnabledSources] = useState<Set<string>>(new Set());
  const [marketScope, setMarketScope] = useState<Set<string>>(new Set());
  const [executionMode, setExecutionMode] = useState("manual");
  const [minConfidence, setMinConfidence] = useState(65);
  const [maxOrders, setMaxOrders] = useState(5);
  const [maxValue, setMaxValue] = useState(50_000_000);
  const [autoSell, setAutoSell] = useState(false);
  const [autoRebalance, setAutoRebalance] = useState(false);

  // Leverage state
  const [levEnabled, setLevEnabled] = useState(false);
  const [levMax, setLevMax] = useState(2.0);
  const [levConfRisk, setLevConfRisk] = useState(false);
  const [levConfMargin, setLevConfMargin] = useState(false);
  const [levConfLiq, setLevConfLiq] = useState(false);
  const [levResult, setLevResult] = useState<LeverageRecommendation | null>(null);
  const [levLoading, setLevLoading] = useState(false);

  const [confPaper30d, setConfPaper30d] = useState(false);
  const [confRisk, setConfRisk] = useState(false);
  const [confLimits, setConfLimits] = useState(false);

  // Mock signals for testing
  const [mockSignals, setMockSignals] = useState(true);

  const fetchState = useCallback(async () => {
    try {
      const res = await fetch("/api/automation/config");
      if (!res.ok) throw new Error("Gagal memuat konfigurasi");
      const data = await res.json();
      setState(data);
      if (data.config) {
        setEnabledSources(new Set(data.config.enabled_sources || []));
        setMarketScope(new Set(data.config.market_scope || []));
        setExecutionMode(data.config.execution_mode || "manual");
        setMinConfidence(data.config.min_confidence || 65);
        setMaxOrders(data.config.max_orders_per_session || 5);
        setMaxValue(data.config.max_value_per_session || 50_000_000);
        setAutoSell(data.config.auto_sell || false);
        setAutoRebalance(data.config.auto_rebalance || false);
        setConfPaper30d(data.config.confirmed_paper_30d || false);
        setConfRisk(data.config.confirmed_risk_understood || false);
        setConfLimits(data.config.confirmed_risk_limits || false);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchState();
  }, [fetchState]);

  const toggleSource = (src: string) => {
    const next = new Set(enabledSources);
    if (next.has(src)) next.delete(src);
    else next.add(src);
    setEnabledSources(next);
  };

  const toggleScope = (scope: string) => {
    const next = new Set(marketScope);
    if (next.has(scope)) next.delete(scope);
    else next.add(scope);
    setMarketScope(next);
  };

  const saveConfig = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch("/api/automation/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled_sources: Array.from(enabledSources),
          market_scope: Array.from(marketScope),
          execution_mode: executionMode,
          min_confidence: minConfidence,
          max_orders_per_session: maxOrders,
          max_value_per_session: maxValue,
          auto_sell: autoSell,
          auto_rebalance: autoRebalance,
          confirmed_paper_30d: confPaper30d,
          confirmed_risk_understood: confRisk,
          confirmed_risk_limits: confLimits,
        }),
      });
      if (!res.ok) throw new Error("Gagal menyimpan konfigurasi");
      const data = await res.json();
      setState((prev) => prev ? { ...prev, config: data.config, gate_result: data.gate_result } : prev);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setSaving(false);
    }
  };

  const preparePlan = async () => {
    setPlanning(true);
    setError(null);
    try {
      const signals = mockSignals
        ? [
            { ticker: "BBCA.JK", side: "buy", source: "screening_ai", confidence: 78, price: 8500, recommendation: "strong_buy" },
            { ticker: "ADRO.JK", side: "buy", source: "model_prediction", confidence: 72, price: 2750, recommendation: "buy" },
            { ticker: "TLKM.JK", side: "buy", source: "advisory_recommendation", confidence: 68, price: 3200, recommendation: "buy" },
            { ticker: "AALI.JK", side: "buy", source: "pattern_signal", confidence: 61, price: 7800, recommendation: "buy" },
          ]
        : [];
      const res = await fetch("/api/automation/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signals }),
      });
      if (!res.ok) throw new Error("Gagal membuat plan");
      const plan = await res.json();
      setState((prev) => prev ? { ...prev, last_plan: plan } : prev);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setPlanning(false);
    }
  };

  const executePlan = async () => {
    setExecuting(true);
    setError(null);
    try {
      const signals = mockSignals
        ? [
            { ticker: "BBCA.JK", side: "buy", source: "screening_ai", confidence: 78, price: 8500, recommendation: "strong_buy" },
            { ticker: "ADRO.JK", side: "buy", source: "model_prediction", confidence: 72, price: 2750, recommendation: "buy" },
            { ticker: "TLKM.JK", side: "buy", source: "advisory_recommendation", confidence: 68, price: 3200, recommendation: "buy" },
            { ticker: "AALI.JK", side: "buy", source: "pattern_signal", confidence: 61, price: 7800, recommendation: "buy" },
          ]
        : [];
      const res = await fetch("/api/automation/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ signals }),
      });
      if (!res.ok) throw new Error("Gagal eksekusi");
      const result = await res.json();
      setState((prev) => prev ? { ...prev, last_execution: result } : prev);
      // Refresh state to get updated plan
      void fetchState();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setExecuting(false);
    }
  };

  const gate = state?.gate_result;
  const canProceed = gate?.passed && (gate?.blocking_count ?? 1) === 0;
  const isManual = executionMode === "manual";
  const needsConfirmations = !isManual;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Bot className="w-6 h-6 text-primary" />
          Otomasi Trading Robot
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          Pilih sinyal yang dieksekusi otomatis, cakupan pasar, dan aturan keamanan
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3">
          <p className="text-xs text-destructive flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" />
            {error}
          </p>
        </div>
      )}

      {/* === GATE STATUS BANNER === */}
      {gate && (
        <div
          className={`rounded-md border p-4 ${
            canProceed
              ? "border-primary/30 bg-primary/5"
              : "border-destructive/30 bg-destructive/5"
          }`}
        >
          <div className="flex items-center gap-3">
            {canProceed ? (
              <ShieldCheck className="w-5 h-5 text-primary" />
            ) : (
              <XCircle className="w-5 h-5 text-destructive" />
            )}
            <div className="flex-1">
              <p className={`text-sm font-medium ${canProceed ? "text-primary" : "text-destructive"}`}>
                {canProceed ? "Gate: LULUS — Otomatisasi siap diaktifkan" : "Gate: GAGAL — Perbaiki aturan berikut"}
              </p>
              <p className="text-xs text-muted-foreground mt-1">{gate.summary}</p>
            </div>
            <button
              onClick={() => setExpandedRules(!expandedRules)}
              className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
            >
              {expandedRules ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
              {gate.rules.length} aturan
            </button>
          </div>

          {expandedRules && (
            <div className="mt-3 space-y-1.5">
              {gate.rules.map((rule) => (
                <div
                  key={rule.rule_id}
                  className="flex items-start gap-2 text-xs py-1.5 px-2 rounded border border-border/50"
                >
                  {rule.status === "pass" ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-primary flex-shrink-0 mt-0.5" />
                  ) : rule.status === "warning" ? (
                    <AlertTriangle className="w-3.5 h-3.5 text-yellow-500 flex-shrink-0 mt-0.5" />
                  ) : (
                    <XCircle className="w-3.5 h-3.5 text-destructive flex-shrink-0 mt-0.5" />
                  )}
                  <div className="flex-1">
                    <span className={`font-medium ${rule.status === "fail" && rule.is_blocking ? "text-destructive" : rule.status === "warning" ? "text-yellow-500" : "text-foreground"}`}>
                      {rule.rule_id}
                    </span>
                    <span className="text-muted-foreground"> — {rule.description}</span>
                    {rule.detail && (
                      <p className="text-muted-foreground/70 mt-0.5">{rule.detail}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* === SIGNAL SOURCES === */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-primary" />
            Sumber Sinyal yang Dieksekusi Otomatis
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {SIGNAL_SOURCES.map((src) => {
              const checked = enabledSources.has(src.value);
              const canEnable = !isManual || true; // Can always toggle in manual
              return (
                <div
                  key={src.value}
                  className={`flex items-center justify-between p-3 rounded-md border ${
                    checked ? "border-primary/30 bg-primary/5" : "border-border"
                  } ${!canEnable ? "opacity-50" : ""}`}
                >
                  <div className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!canEnable}
                      onChange={() => toggleSource(src.value)}
                      className="w-4 h-4 mt-0.5"
                    />
                    <div>
                      <p className="text-sm font-medium">{src.label}</p>
                      <p className="text-xs text-muted-foreground">{src.desc}</p>
                    </div>
                  </div>
                  {checked && (
                    <span className="text-xs text-primary font-medium">Aktif</span>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* === MARKET SCOPE === */}
      <Card>
        <CardHeader>
          <CardTitle>Cakupan Pasar Portofolio</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {MARKET_SCOPES.map((scope) => {
              const checked = marketScope.has(scope.value);
              return (
                <div
                  key={scope.value}
                  className={`flex items-center justify-between p-3 rounded-md border ${
                    checked ? "border-primary/30 bg-primary/5" : "border-border"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleScope(scope.value)}
                      className="w-4 h-4 mt-0.5"
                    />
                    <div>
                      <p className="text-sm font-medium">{scope.label}</p>
                      <p className="text-xs text-muted-foreground">{scope.desc}</p>
                    </div>
                  </div>
                  {checked && (
                    <span className="text-xs text-primary font-medium">Dipilih</span>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* === EXECUTION MODE === */}
      <Card>
        <CardHeader>
          <CardTitle>Mode Eksekusi</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {EXECUTION_MODES.map((mode) => (
              <button
                key={mode.value}
                onClick={() => setExecutionMode(mode.value)}
                className={`p-4 rounded-md border text-left transition-colors ${
                  executionMode === mode.value
                    ? "border-primary bg-primary/10"
                    : "border-border hover:border-primary/50"
                }`}
              >
                <p className={`text-sm font-medium ${mode.color}`}>{mode.label}</p>
                <p className="text-xs text-muted-foreground mt-1">{mode.desc}</p>
              </button>
            ))}
          </div>

          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="text-sm font-medium block mb-1">Min Confidence</label>
              <input
                type="number"
                value={minConfidence}
                onChange={(e) => setMinConfidence(Number(e.target.value))}
                min={0}
                max={100}
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm"
              />
            </div>
            <div>
              <label className="text-sm font-medium block mb-1">Max Order/Sesi</label>
              <input
                type="number"
                value={maxOrders}
                onChange={(e) => setMaxOrders(Number(e.target.value))}
                min={1}
                max={20}
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm"
              />
            </div>
            <div>
              <label className="text-sm font-medium block mb-1">Max Value/Sesi (Rp)</label>
              <input
                type="number"
                value={maxValue}
                onChange={(e) => setMaxValue(Number(e.target.value))}
                min={1_000_000}
                step={1_000_000}
                className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm"
              />
            </div>
          </div>

          <div className="mt-4 space-y-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={autoSell}
                onChange={(e) => setAutoSell(e.target.checked)}
                className="w-4 h-4"
              />
              Auto-Sell (eksekusi sinyal sell/exit otomatis)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={autoRebalance}
                onChange={(e) => setAutoRebalance(e.target.checked)}
                className="w-4 h-4"
              />
              Auto-Rebalance (re-balancing portofolio otomatis)
            </label>
          </div>
        </CardContent>
      </Card>

      {/* === LEVERAGE === */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-yellow-500" />
            Saran Leverage
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="rounded-md border border-yellow-500/30 bg-yellow-500/5 p-3">
              <p className="text-xs text-yellow-600 dark:text-yellow-500">
                ⚠️ Leverage memperbesar keuntungan sekaligus kerugian. Margin call dan likuidasi paksa dapat terjadi.
                Sistem akan memberikan saran leverage berdasarkan Kelly criterion, volatilitas, drawdown, dan confidence sinyal.
              </p>
            </div>

            <label className="flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={levEnabled}
                onChange={(e) => setLevEnabled(e.target.checked)}
                className="w-4 h-4"
              />
              Aktifkan Saran Leverage
            </label>

            {levEnabled && (
              <>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="text-sm font-medium block mb-1">Max Leverage (x)</label>
                    <input
                      type="number"
                      value={levMax}
                      onChange={(e) => setLevMax(Number(e.target.value))}
                      min={1}
                      max={50}
                      step={0.5}
                      className="w-full px-3 py-2 rounded-md border border-input bg-background text-sm"
                    />
                    <p className="text-xs text-muted-foreground mt-1">
                      Batas maksimum leverage yang Anda izinkan. Sistem tidak akan melebihi nilai ini.
                    </p>
                  </div>
                </div>

                <div className="space-y-2">
                  <label className="flex items-start gap-3 p-3 rounded-md border border-border">
                    <input
                      type="checkbox"
                      checked={levConfRisk}
                      onChange={(e) => setLevConfRisk(e.target.checked)}
                      className="w-4 h-4 mt-0.5"
                    />
                    <div>
                      <p className="text-sm font-medium">Saya memahami risiko leverage</p>
                      <p className="text-xs text-muted-foreground">Leverage memperbesar kerugian secara proporsional</p>
                    </div>
                  </label>
                  <label className="flex items-start gap-3 p-3 rounded-md border border-border">
                    <input
                      type="checkbox"
                      checked={levConfMargin}
                      onChange={(e) => setLevConfMargin(e.target.checked)}
                      className="w-4 h-4 mt-0.5"
                    />
                    <div>
                      <p className="text-sm font-medium">Saya memahami risiko margin call</p>
                      <p className="text-xs text-muted-foreground">Broker dapat meminta tambahan dana jika nilai posisi turun</p>
                    </div>
                  </label>
                  <label className="flex items-start gap-3 p-3 rounded-md border border-border">
                    <input
                      type="checkbox"
                      checked={levConfLiq}
                      onChange={(e) => setLevConfLiq(e.target.checked)}
                      className="w-4 h-4 mt-0.5"
                    />
                    <div>
                      <p className="text-sm font-medium">Saya memahami risiko likuidasi paksa</p>
                      <p className="text-xs text-muted-foreground">Broker dapat menutup posisi tanpa persetujuan jika margin tidak terpenuhi</p>
                    </div>
                  </label>
                </div>

                <button
                  onClick={async () => {
                    setLevLoading(true);
                    try {
                      const res = await fetch("/api/leverage/advise", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                          ticker: "BBCA.JK",
                          capital: 10_000_000,
                          price: 8500,
                          asset_class: "equity",
                          win_rate: 0.62,
                          avg_win: 3.5,
                          avg_loss: 1.8,
                          volatility_pct: 25,
                          drawdown_pct: 3,
                          confidence: 78,
                          stop_loss: 8075,
                          leverage_enabled: levEnabled,
                          max_leverage: levMax,
                          confirmed_risk: levConfRisk,
                          confirmed_margin_call: levConfMargin,
                          confirmed_liquidation: levConfLiq,
                        }),
                      });
                      if (!res.ok) throw new Error("Gagal mendapatkan saran leverage");
                      const rec = await res.json();
                      setLevResult(rec);
                    } catch (e) {
                      setError(e instanceof Error ? e.message : "Unknown error");
                    } finally {
                      setLevLoading(false);
                    }
                  }}
                  disabled={levLoading || !levConfRisk || !levConfMargin || !levConfLiq}
                  className="px-6 py-2 rounded-md border border-border text-sm font-medium hover:bg-accent disabled:opacity-50 flex items-center gap-2"
                >
                  {levLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <TrendingUp className="w-4 h-4" />}
                  Minta Saran Leverage
                </button>
              </>
            )}

            {/* Leverage Recommendation Result */}
            {levResult && (
              <div className="mt-4 space-y-3">
                <div className={`rounded-md border p-4 ${
                  levResult.can_apply
                    ? "border-primary/30 bg-primary/5"
                    : "border-destructive/30 bg-destructive/5"
                }`}>
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium">
                        Leverage Disarankan: {levResult.recommended_leverage.toFixed(2)}x
                      </p>
                      <p className="text-xs text-muted-foreground capitalize">
                        Level: {levResult.level}
                      </p>
                    </div>
                    {levResult.can_apply ? (
                      <CheckCircle2 className="w-5 h-5 text-primary" />
                    ) : (
                      <XCircle className="w-5 h-5 text-destructive" />
                    )}
                  </div>

                  <p className="text-xs text-muted-foreground mt-2">{levResult.rationale}</p>

                  {levResult.haircuts.length > 0 && (
                    <div className="mt-2 space-y-1">
                      <p className="text-xs font-medium text-muted-foreground">Haircuts:</p>
                      {levResult.haircuts.map((h, i) => (
                        <p key={i} className="text-xs text-muted-foreground/70">• {h.detail}</p>
                      ))}
                    </div>
                  )}

                  {levResult.warnings.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {levResult.warnings.map((w, i) => (
                        <p key={i} className="text-xs text-yellow-500 flex items-start gap-1">
                          <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                          {w}
                        </p>
                      ))}
                    </div>
                  )}

                  <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                    <div>
                      <p className="text-muted-foreground">Modal</p>
                      <p className="font-medium">Rp {levResult.effective_capital.toLocaleString()}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Posisi Leveraged</p>
                      <p className="font-medium">Rp {levResult.leveraged_position_value.toLocaleString()}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Liquidation Price</p>
                      <p className="font-medium text-destructive">Rp {levResult.liquidation_price.toLocaleString()}</p>
                    </div>
                    <div>
                      <p className="text-muted-foreground">Max Loss</p>
                      <p className="font-medium text-destructive">Rp {levResult.max_loss_at_leverage.toLocaleString()}</p>
                    </div>
                  </div>

                  {levResult.conditions.length > 0 && (
                    <div className="mt-3 space-y-1">
                      <p className="text-xs font-medium text-muted-foreground">Kondisi:</p>
                      {levResult.conditions.map((c, i) => (
                        <p key={i} className="text-xs text-muted-foreground/70">• {c}</p>
                      ))}
                    </div>
                  )}

                  {levResult.rejection_reason && (
                    <p className="text-xs text-destructive mt-2">
                      Ditolak: {levResult.rejection_reason}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* === CONFIRMATIONS === */}
      {needsConfirmations && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileCheck2 className="w-4 h-4 text-yellow-500" />
              Konfirmasi User (Wajib untuk Semi-Auto & Full-Auto)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <label className="flex items-start gap-3 p-3 rounded-md border border-border">
                <input
                  type="checkbox"
                  checked={confPaper30d}
                  onChange={(e) => setConfPaper30d(e.target.checked)}
                  className="w-4 h-4 mt-0.5"
                />
                <div>
                  <p className="text-sm font-medium">Saya telah menjalankan paper trading minimal 30 hari</p>
                  <p className="text-xs text-muted-foreground">
                    Paper trading harus menunjukkan hasil yang memadai sebelum live
                  </p>
                </div>
              </label>
              <label className="flex items-start gap-3 p-3 rounded-md border border-border">
                <input
                  type="checkbox"
                  checked={confRisk}
                  onChange={(e) => setConfRisk(e.target.checked)}
                  className="w-4 h-4 mt-0.5"
                />
                <div>
                  <p className="text-sm font-medium">Saya memahami risiko kehilangan modal</p>
                  <p className="text-xs text-muted-foreground">
                    Trading otomatis dapat mengakibatkan kerugian
                  </p>
                </div>
              </label>
              <label className="flex items-start gap-3 p-3 rounded-md border border-border">
                <input
                  type="checkbox"
                  checked={confLimits}
                  onChange={(e) => setConfLimits(e.target.checked)}
                  className="w-4 h-4 mt-0.5"
                />
                <div>
                  <p className="text-sm font-medium">Saya menyetujui daily loss limit dan max drawdown settings</p>
                  <p className="text-xs text-muted-foreground">
                    Circuit breaker akan menghentikan otomatisasi jika limit tercapai
                  </p>
                </div>
              </label>
            </div>
          </CardContent>
        </Card>
      )}

      {/* === ACTIONS === */}
      <div className="flex gap-3">
        <button
          onClick={saveConfig}
          disabled={saving}
          className="px-6 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 flex items-center gap-2"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
          Simpan & Periksa Gate
        </button>
        <button
          onClick={preparePlan}
          disabled={planning || !canProceed}
          className="px-6 py-2 rounded-md border border-border text-sm font-medium hover:bg-accent disabled:opacity-50 flex items-center gap-2"
        >
          {planning ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileCheck2 className="w-4 h-4" />}
          Siapkan Rencana Eksekusi
        </button>
        <button
          onClick={executePlan}
          disabled={executing || !canProceed || isManual}
          className="px-6 py-2 rounded-md bg-yellow-600 text-white text-sm font-medium hover:bg-yellow-700 disabled:opacity-50 flex items-center gap-2"
        >
          {executing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
          Eksekusi ke Pasar
        </button>
      </div>

      {isManual && canProceed && (
        <p className="text-xs text-muted-foreground">
          Mode manual: plan dibuat tapi tidak dieksekusi otomatis. Ubah ke Semi-Auto atau Full-Auto untuk eksekusi otomatis.
        </p>
      )}

      {/* === EXECUTION PLAN PREVIEW === */}
      {state?.last_plan && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileCheck2 className="w-4 h-4 text-primary" />
              Rencana Eksekusi: {state.last_plan.plan_id}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-4">{state.last_plan.summary}</p>

            {state.last_plan.orders.length > 0 ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="text-left py-2">Ticker</th>
                    <th className="text-left">Side</th>
                    <th className="text-left">Source</th>
                    <th className="text-right">Shares</th>
                    <th className="text-right">Price</th>
                    <th className="text-right">Value</th>
                    <th className="text-right">Confidence</th>
                    <th className="text-right">SL</th>
                    <th className="text-right">TP</th>
                    <th className="text-left">Readiness</th>
                  </tr>
                </thead>
                <tbody>
                  {state.last_plan.orders.map((order, i) => (
                    <tr key={i} className="border-b border-border/50">
                      <td className="py-2 font-medium">{order.ticker}</td>
                      <td className={order.side === "buy" ? "text-primary" : "text-destructive"}>
                        {order.side}
                      </td>
                      <td className="text-xs text-muted-foreground">{order.source}</td>
                      <td className="text-right">{order.shares.toLocaleString()}</td>
                      <td className="text-right">Rp {order.price.toLocaleString()}</td>
                      <td className="text-right">Rp {(order.shares * order.price).toLocaleString()}</td>
                      <td className="text-right">{order.confidence.toFixed(1)}%</td>
                      <td className="text-right text-destructive">Rp {order.stop_loss.toLocaleString()}</td>
                      <td className="text-right text-primary">Rp {order.take_profit.toLocaleString()}</td>
                      <td>
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          order.readiness_level === "ready"
                            ? "bg-primary/10 text-primary"
                            : order.readiness_level === "conditional"
                            ? "bg-yellow-500/10 text-yellow-500"
                            : "bg-muted text-muted-foreground"
                        }`}>
                          {order.readiness_level}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="text-sm text-muted-foreground">Tidak ada order yang lolos filter.</p>
            )}

            {state.last_plan.rejection_reasons.length > 0 && (
              <div className="mt-4 space-y-1">
                <p className="text-xs font-medium text-muted-foreground">Ditolak ({state.last_plan.rejected_count}):</p>
                {state.last_plan.rejection_reasons.map((reason, i) => (
                  <p key={i} className="text-xs text-muted-foreground/70">• {reason}</p>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* === EXECUTION RESULT === */}
      {state?.last_execution && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Zap className="w-4 h-4 text-yellow-500" />
              Hasil Eksekusi
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-4">{state.last_execution.summary}</p>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
              <div>
                <p className="text-xs text-muted-foreground">Filled</p>
                <p className="text-lg font-bold text-primary">{state.last_execution.filled_count}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Rejected</p>
                <p className="text-lg font-bold text-destructive">{state.last_execution.rejected_count}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Total Value</p>
                <p className="text-lg font-bold">Rp {state.last_execution.total_value.toLocaleString()}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Commission</p>
                <p className="text-lg font-bold">Rp {state.last_execution.total_commission.toLocaleString()}</p>
              </div>
            </div>

            {state.last_execution.results.length > 0 && (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="text-left py-2">Ticker</th>
                    <th className="text-left">Side</th>
                    <th className="text-right">Shares</th>
                    <th className="text-right">Fill Price</th>
                    <th className="text-right">Commission</th>
                    <th className="text-left">Status</th>
                    <th className="text-left">Order ID</th>
                  </tr>
                </thead>
                <tbody>
                  {state.last_execution.results.map((res, i) => (
                    <tr key={i} className="border-b border-border/50">
                      <td className="py-2 font-medium">{res.ticker}</td>
                      <td className={res.side === "buy" ? "text-primary" : "text-destructive"}>{res.side}</td>
                      <td className="text-right">{res.shares.toLocaleString()}</td>
                      <td className="text-right">Rp {res.fill_price.toLocaleString()}</td>
                      <td className="text-right">Rp {res.commission.toLocaleString()}</td>
                      <td>
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          res.status === "filled"
                            ? "bg-primary/10 text-primary"
                            : "bg-destructive/10 text-destructive"
                        }`}>
                          {res.status}
                        </span>
                      </td>
                      <td className="text-xs text-muted-foreground">{res.order_id}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
