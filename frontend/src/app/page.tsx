"use client";

/**
 * Dashboard Astronacci — padat, real-time, single-user.
 *
 * Layout: CSS grid tetap (tanpa scroll halaman). Tujuh zona widget:
 *   A: KPI (NAB / Imbal Hasil / PnL / posisi)
 *   B: Pergerakan (penguatan / pelemahan)
 *   C: Grafik Live IHSG (recharts + WS tick sparkline, crosshair-synced)
 *   D: Tabel posisi portofolio
 *   E: Feed sinyal live (WS kanal `signals` + REST atribusi fallback)
 *   F: Breadth pasar (penguatan vs pelemahan, diturunkan dari pergerakan)
 *   G: Konsol Observabilitas Backend (log SSE + indikator status)
 *
 * Anti-freeze:
 *   - REST for initial load; WS for live ticks. WS messages mutate refs and
 *     re-render at most once per frame via `useWsLatest` (rAF coalescing).
 *   - `useFpsGuard` watches FPS and sends bidirectional backpressure
 *     (`ws.sendThrottle` / `sendThrottleOff`) when the UI struggles.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  YAxis,
} from "recharts";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  Cpu,
  Moon,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { Widget } from "@/components/widget";
import { ObservabilityConsole } from "@/components/observability-console";
import { TickerTape } from "@/components/ticker-tape";
import { CelestialFibonacciChart } from "@/components/celestial-fibonacci-chart";
import { MultiHorizonProjection } from "@/components/multi-horizon-projection";
import { EngineOrchestrationLog } from "@/components/engine-orchestration-log";
import { CrosshairProvider, useCrosshairStore } from "@/components/crosshair-context";
import { getWsClient, useWsLatest, type WsMessage } from "@/lib/ws-client";
import { useFpsGuard } from "@/lib/use-fps-guard";
import { cn } from "@/lib/utils";

// ── Data shapes (kept from the previous dashboard) ─────────────────────

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
interface Position {
  shares: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  weight_pct: number;
}
interface PortfolioSummary {
  total_nav: number;
  cash: number;
  positions: Record<string, Position>;
  n_positions: number;
}
interface SignalAttr {
  date: string;
  ticker: string;
  engine: string;
  signal: number;
  direction: string;
  confidence: number;
  weight: number;
  contribution: number;
  rationale: string;
}

// ── FE Cache State (zero-wait from fe_dashboard_cache) ────────────────

interface FeCacheState {
  sim_date: string;
  equity: number;
  cash: number;
  positions: Record<string, { ticker: string; shares: number; entry_price: number; entry_date: string | null; asset_class: string }>;
  regime: string;
  active_cycles: number;
  n_positions: number;
  n_trades: number;
  lookahead_violations: number;
}

function getMoonPhase(): { phase: string; icon: string } {
  const phases = ["New", "Waxing Crescent", "First Quarter", "Waxing Gibbous", "Full", "Waning Gibbous", "Last Quarter", "Waning Crescent"];
  const lp = 2551443; // lunar period in seconds
  const now = Date.now() / 1000;
  const newMoon = 592500; // reference new moon
  const phase = ((now - newMoon) % lp) / lp;
  const idx = Math.floor(phase * 8) % 8;
  return { phase: phases[idx], icon: ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"][idx] };
}

// ── Helpers ────────────────────────────────────────────────────────────

function fmtIDR(n: number, frac = 0): string {
  return n.toLocaleString("id-ID", { maximumFractionDigits: frac });
}
function fmtPct(n: number | null | undefined, decimals = 2): string {
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(decimals)}%`;
}
function changeColor(n: number | null | undefined): string {
  if (n == null) return "text-muted-foreground";
  return n > 0 ? "text-emerald-400" : n < 0 ? "text-red-400" : "text-muted-foreground";
}

// ── Widget C: IHSG live chart (crosshair-synced) ───────────────────────

function IhsgChart({ ihsg, tickRing }: { ihsg: IhsgData | null; tickRing: { t: number; p: number }[] }) {
  const store = useCrosshairStore();
  const data = useMemo(() => {
    if (tickRing.length >= 2) {
      return tickRing.map((d) => ({ t: d.t, p: d.p }));
    }
    // Fallback: single point from REST so the chart isn't empty.
    if (ihsg?.price != null) return [{ t: Date.now(), p: ihsg.price }];
    return [];
  }, [tickRing, ihsg]);

  const latest = data.length ? data[data.length - 1].p : ihsg?.price ?? null;
  const chg = ihsg?.change ?? null;
  const pct = ihsg?.pct_change ?? null;

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-baseline gap-3 mb-2">
        <span className="text-2xl font-bold tabular-nums">
          {latest != null ? latest.toLocaleString("en-US", { maximumFractionDigits: 2 }) : "—"}
        </span>
        <span className={cn("text-sm font-mono", changeColor(chg))}>
          {chg != null ? `${chg > 0 ? "+" : ""}${chg.toFixed(2)}` : "—"} ({fmtPct(pct)})
        </span>
        <span className="text-[10px] text-muted-foreground ml-auto">
          {data.length > 1 ? `${data.length} tick live` : "menunggu tick WS…"}
        </span>
      </div>
      <div
        className="flex-1 min-h-0"
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const x = e.clientX - rect.left;
          const ratio = data.length > 1 ? x / rect.width : 0;
          const idx = Math.min(data.length - 1, Math.max(0, Math.round(ratio * (data.length - 1))));
          store.set(data[idx]?.t ?? null, "ihsg");
        }}
        onMouseLeave={() => store.set(null, null)}
      >
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="ihsgFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#22c55e" stopOpacity={0.4} />
                <stop offset="100%" stopColor="#22c55e" stopOpacity={0} />
              </linearGradient>
            </defs>
            <YAxis
              domain={["auto", "auto"]}
              tick={{ fill: "#64748b", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={48}
              orientation="right"
            />
            <Tooltip
              contentStyle={{
                background: "rgba(10,14,26,0.9)",
                border: "1px solid hsl(217 33% 25%)",
                borderRadius: 6,
                fontSize: 11,
              }}
              labelFormatter={(t) => new Date(t as number).toLocaleTimeString("en-GB", { hour12: false })}
              formatter={(v: number) => [v.toLocaleString("en-US", { maximumFractionDigits: 2 }), "IHSG"]}
            />
            <Area
              type="monotone"
              dataKey="p"
              stroke="#22c55e"
              strokeWidth={1.5}
              fill="url(#ihsgFill)"
              isAnimationActive={false}
              dot={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Widget E: Signals live feed ─────────────────────────────────────────

function SignalsFeed({ restSignals }: { restSignals: SignalAttr[] }) {
  // Live WS signals (when BE broadcasts on `signals` channel).
  const live = useWsLatest("signals");
  const liveRef = useRef<WsMessage | undefined>(undefined);
  liveRef.current = live;

  const items = useMemo(() => {
    const out: { ticker: string; engine: string; dir: string; conf: number; ts: number }[] = [];
    if (live?.sig && typeof live.sig === "object") {
      const s = live.sig as Record<string, unknown>;
      out.unshift({
        ticker: String(s.ticker ?? "—"),
        engine: String(s.engine ?? "—"),
        dir: String(s.direction ?? "—"),
        conf: Number(s.confidence ?? 0),
        ts: Number(live.ts ?? Date.now()),
      });
    }
    for (const r of restSignals.slice(0, 19)) {
      out.push({
        ticker: r.ticker,
        engine: r.engine,
        dir: r.direction,
        conf: r.confidence,
        ts: new Date(r.date).getTime(),
      });
    }
    return out.slice(0, 20);
  }, [live, restSignals]);

  return (
    <div className="space-y-1 text-xs">
      {items.length === 0 ? (
        <div className="text-muted-foreground/60 italic">Menunggu sinyal masuk…</div>
      ) : (
        items.map((s, i) => {
          const dirColor =
            s.dir === "BUY" || s.dir === "BULLISH" ? "text-emerald-400"
              : s.dir === "SELL" || s.dir === "BEARISH" ? "text-red-400"
                : "text-muted-foreground";
          return (
            <div key={i} className="flex items-center gap-2 py-0.5 border-b border-border/30 last:border-0">
              <span className="font-mono font-semibold w-16 shrink-0">{s.ticker}</span>
              <span className="text-muted-foreground text-[10px] w-20 shrink-0 truncate">{s.engine}</span>
              <span className={cn("font-medium w-16 shrink-0", dirColor)}>{s.dir}</span>
              <span className="text-muted-foreground ml-auto font-mono text-[10px]">
                {(s.conf * 100).toFixed(0)}%
              </span>
            </div>
          );
        })
      )}
    </div>
  );
}

// ── Main dashboard page ────────────────────────────────────────────────

export default function DashboardPage() {
  const [movers, setMovers] = useState<MoversData | null>(null);
  const [ihsg, setIhsg] = useState<IhsgData | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [signals, setSignals] = useState<SignalAttr[]>([]);
  const [feState, setFeState] = useState<FeCacheState | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<string>("");
  const moon = useMemo(() => getMoonPhase(), []);

  // WS tick ring buffer for the IHSG live chart (ref-backed, coalesced).
  const tickRingRef = useRef<{ t: number; p: number }[]>([]);
  const [tickRing, setTickRing] = useState<{ t: number; p: number }[]>([]);
  const [, bumpRing] = useState(0);

  // ── REST initial load (kept; WS augments live) ──
  const loadData = useCallback(async () => {
    try {
      const [moversRes, ihsgRes, portfolioRes, sigRes, feRes] = await Promise.allSettled([
        fetch("/api/prices/movers?limit=5"),
        fetch("/api/prices/ihsg"),
        fetch("/api/portfolio"),
        fetch("/api/signals/attribution?days=7"),
        fetch("/api/fe-cache/latest-state"),
      ]);
      if (moversRes.status === "fulfilled" && moversRes.value.ok) {
        try { setMovers(await moversRes.value.json()); } catch {}
      }
      if (ihsgRes.status === "fulfilled" && ihsgRes.value.ok) {
        try { setIhsg(await ihsgRes.value.json()); } catch {}
      }
      if (portfolioRes.status === "fulfilled" && portfolioRes.value.ok) {
        try { setPortfolio(await portfolioRes.value.json()); } catch {}
      }
      if (sigRes.status === "fulfilled" && sigRes.value.ok) {
        try { setSignals(await sigRes.value.json()); } catch {}
      }
      if (feRes.status === "fulfilled" && feRes.value.ok) {
        try {
          const feData = await feRes.value.json();
          if (feData.status === "ok" && feData.state) setFeState(feData.state as FeCacheState);
        } catch {}
      }
    } catch {
      // Network error — silently keep previous data
    }
    setLoading(false);
    setLastUpdate(new Date().toLocaleTimeString("id-ID", { hour12: false }));
  }, []);

  useEffect(() => {
    loadData();
    const id = setInterval(loadData, 60_000);
    return () => clearInterval(id);
  }, [loadData]);

  // ── WS: subscribe to prices.tick + signals, feed the IHSG ring ──
  useEffect(() => {
    const client = getWsClient();
    client.connect();
    const unsub = client.subscribe(["prices.tick", "signals"], (msg) => {
      if (msg.ch === "prices.tick" && msg.t === "^JKSE" && typeof msg.p === "number") {
        const ring = tickRingRef.current;
        if (ring.length >= 240) ring.shift();
        ring.push({ t: Number(msg.ts ?? Date.now()), p: msg.p });
        setTickRing([...ring]);
        // Coalesced re-render via rAF (shared flush in ws-client).
        bumpRing((n) => n + 1);
      }
    });
    return unsub;
  }, []);

  // ── Bidirectional backpressure: throttle BE when FPS drops ──
  const fps = useFpsGuard({
    onThrottle: (rate) => getWsClient().sendThrottle(rate),
    onRelease: () => getWsClient().sendThrottleOff(),
  });

  // ── Derived values ──
  const totalPnl = useMemo(
    () =>
      portfolio
        ? Object.values(portfolio.positions).reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0)
        : 0,
    [portfolio],
  );
  const positions = useMemo(
    () => (portfolio ? Object.entries(portfolio.positions) : []),
    [portfolio],
  );
  const breadth = useMemo(() => {
    const g = movers?.gainers.length ?? 0;
    const l = movers?.losers.length ?? 0;
    const total = g + l || 1;
    return { g, l, gPct: (g / total) * 100, lPct: (l / total) * 100 };
  }, [movers]);

  return (
    <CrosshairProvider>
      <div className="min-h-full w-full flex flex-col gap-4 p-4" style={{ contain: "layout" }}>
        {/* Ticker Tape — GPU-accelerated running text */}
        <TickerTape />

        {/* Status bar: IHSG + Moon Phase + Breadth + FPS */}
        <div
          className="flex items-center gap-4 px-4 h-8 rounded-lg border border-border/40 bg-card/40 text-xs overflow-hidden shrink-0"
          style={{ contain: "strict", backdropFilter: "blur(8px)" }}
        >
          <span className="font-semibold text-primary shrink-0">IHSG</span>
          <span className={cn("font-mono tabular-nums shrink-0", changeColor(ihsg?.pct_change))}>
            {ihsg?.price != null ? ihsg.price.toLocaleString("en-US", { maximumFractionDigits: 2 }) : "—"}
            {" "}
            {fmtPct(ihsg?.pct_change)}
          </span>
          <div className="w-px h-3.5 bg-border/40 shrink-0" />
          <span className="shrink-0 flex items-center gap-1" title={moon.phase}>
            <Moon className="w-3 h-3 text-blue-300" />
            <span className="text-muted-foreground">{moon.phase}</span>
          </span>
          <div className="w-px h-3.5 bg-border/40 shrink-0" />
          <span className="text-muted-foreground shrink-0">Naik:</span>
          <span className="text-emerald-400 font-mono tabular-nums shrink-0">{breadth.g}</span>
          <span className="text-muted-foreground shrink-0">Turun:</span>
          <span className="text-red-400 font-mono tabular-nums shrink-0">{breadth.l}</span>
          {feState && (
            <>
              <div className="w-px h-3.5 bg-border/40 shrink-0" />
              <span className="text-muted-foreground shrink-0">Sim:</span>
              <span className="font-mono tabular-nums shrink-0 text-emerald-400">
                {(feState.equity / 1_000_000).toFixed(2)}M
              </span>
              <span className={cn("shrink-0 font-mono", feState.regime === "bull" ? "text-emerald-400" : feState.regime === "bear" ? "text-red-400" : "text-muted-foreground")}>
                {feState.regime}
              </span>
            </>
          )}
          <div className="ml-auto flex items-center gap-3 shrink-0">
            <span className="text-muted-foreground">Pembaruan:</span>
            <span className="font-mono tabular-nums">{lastUpdate || "—"}</span>
            <div className="w-px h-3.5 bg-border/40" />
            <span className="text-muted-foreground">FPS:</span>
            <span className={cn("font-mono tabular-nums", fps >= 50 ? "text-emerald-400" : fps >= 30 ? "text-yellow-400" : "text-red-400")}>
              {fps.toFixed(0)}
            </span>
          </div>
        </div>

        {/* Bento Grid: 12 cols, tier-based sizing */}
        <div
          className="grid gap-4"
          style={{
            gridTemplateColumns: "repeat(12, minmax(0, 1fr))",
            gridAutoRows: "minmax(280px, auto)",
          }}
        >
          {/* Tier 1 Hero: Celestial Fibonacci Chart (6 cols × 2 rows) */}
          <CelestialFibonacciChart
            ticker="^JKSE"
            className="col-span-6 row-span-2"
          />

          {/* Tier 1 Hero: Portfolio NAV (3 cols × 1 row) */}
          <Widget
            title="Nilai Aset Bersih"
            icon={<Wallet className="w-3.5 h-3.5" />}
            accent="text-primary"
            className="col-span-3"
            right={<span className="text-[10px] text-muted-foreground tabular-nums">{portfolio?.n_positions ?? 0} pos</span>}
          >
            <div className="space-y-2">
              <div>
                <p className="text-[10px] text-muted-foreground uppercase">NAB</p>
                <p className="text-xl font-bold tabular-nums">Rp {portfolio ? fmtIDR(portfolio.total_nav) : "—"}</p>
              </div>
              <div>
                <p className="text-[10px] text-muted-foreground uppercase">PnL Belum Terealisasi</p>
                <p className={cn("text-lg font-bold tabular-nums", totalPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                  {totalPnl >= 0 ? "+" : ""}Rp {fmtIDR(totalPnl)}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-muted-foreground uppercase">Kas</p>
                <p className="text-sm font-mono tabular-nums">Rp {portfolio ? fmtIDR(portfolio.cash) : "—"}</p>
              </div>
              {feState && (
                <div className="pt-1 border-t border-border/30">
                  <p className="text-[10px] text-muted-foreground uppercase">Ekuitas Simulasi (cache)</p>
                  <p className="text-sm font-bold tabular-nums text-emerald-400">
                    Rp {fmtIDR(feState.equity)} <span className="text-[10px] text-muted-foreground font-normal">({feState.sim_date})</span>
                  </p>
                </div>
              )}
            </div>
          </Widget>

          {/* Tier 2 Feature: Movers & Breadth (3 cols × 1 row) */}
          <Widget
            title="Pergerakan & Breadth Pasar"
            icon={<TrendingUp className="w-3.5 h-3.5" />}
            accent="text-emerald-400"
            className="col-span-3"
            right={<span className="text-[10px] text-muted-foreground">{movers?.as_of ?? "—"}</span>}
          >
            <div className="space-y-2 text-xs">
              <div>
                <div className="flex justify-between text-[10px] text-muted-foreground mb-1">
                  <span>Penguatan {breadth.g}</span>
                  <span>Pelemahan {breadth.l}</span>
                </div>
                <div className="h-2 rounded-full overflow-hidden flex bg-border/40">
                  <div className="bg-emerald-500/80" style={{ width: `${breadth.gPct}%` }} />
                  <div className="bg-red-500/80" style={{ width: `${breadth.lPct}%` }} />
                </div>
              </div>
              <div>
                <p className="text-[10px] text-emerald-400/80 uppercase mb-1 flex items-center gap-1">
                  <ArrowUp className="w-3 h-3" /> Saham Penguatan
                </p>
                {movers?.gainers.slice(0, 4).map((m) => (
                  <div key={m.ticker} className="flex items-center gap-2 py-0.5">
                    <span className="font-mono font-semibold w-14 tabular-nums">{m.ticker}</span>
                    <span className="font-mono ml-auto tabular-nums">{m.close.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
                    <span className="text-emerald-400 font-mono w-16 text-right tabular-nums">{fmtPct(m.pct_change)}</span>
                  </div>
                )) ?? <span className="text-muted-foreground/60 italic">—</span>}
              </div>
              <div>
                <p className="text-[10px] text-red-400/80 uppercase mb-1 flex items-center gap-1">
                  <ArrowDown className="w-3 h-3" /> Saham Pelemahan
                </p>
                {movers?.losers.slice(0, 4).map((m) => (
                  <div key={m.ticker} className="flex items-center gap-2 py-0.5">
                    <span className="font-mono font-semibold w-14 tabular-nums">{m.ticker}</span>
                    <span className="font-mono ml-auto tabular-nums">{m.close.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
                    <span className="text-red-400 font-mono w-16 text-right tabular-nums">{fmtPct(m.pct_change)}</span>
                  </div>
                )) ?? <span className="text-muted-foreground/60 italic">—</span>}
              </div>
            </div>
          </Widget>

          {/* Tier 2 Feature: Positions (3 cols × 1 row) */}
          <Widget
            title="Posisi Portofolio"
            icon={<Wallet className="w-3.5 h-3.5" />}
            className="col-span-3"
            right={<span className="text-[10px] text-muted-foreground tabular-nums">{positions.length} pos</span>}
          >
            <div className="text-xs space-y-1">
              {positions.length === 0 && !feState ? (
                <div className="text-muted-foreground/60 italic">Belum ada posisi terbuka</div>
              ) : (
                <>
                  {positions.slice(0, 8).map(([ticker, p]) => (
                    <div key={ticker} className="flex items-center gap-2 py-0.5 border-b border-border/30 last:border-0">
                      <span className="font-mono font-semibold w-16 shrink-0 tabular-nums">{ticker}</span>
                      <span className="font-mono text-muted-foreground text-[10px] w-12 shrink-0 tabular-nums">{p.shares}</span>
                      <span className={cn("font-mono ml-auto text-right tabular-nums", p.unrealized_pnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                        {p.unrealized_pnl >= 0 ? "+" : ""}{fmtIDR(p.unrealized_pnl)}
                      </span>
                    </div>
                  ))}
                  {feState && Object.keys(feState.positions).length > 0 && (
                    <div className="pt-1 border-t border-border/30 mt-1">
                      <p className="text-[10px] text-muted-foreground uppercase mb-1">Posisi Simulasi (cache)</p>
                      {Object.entries(feState.positions).slice(0, 4).map(([ticker, p]) => (
                        <div key={ticker} className="flex items-center gap-2 py-0.5">
                          <span className="font-mono font-semibold w-16 shrink-0 tabular-nums">{ticker}</span>
                          <span className="font-mono text-muted-foreground text-[10px] w-12 shrink-0 tabular-nums">{p.shares}</span>
                          <span className="font-mono text-[10px] ml-auto text-muted-foreground tabular-nums">{p.asset_class}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </Widget>

          {/* Tier 2 Feature: Signals (3 cols × 1 row) */}
          <Widget
            title="Feed Sinyal"
            icon={<TrendingUp className="w-3.5 h-3.5" />}
            accent="text-primary"
            className="col-span-3"
            right={<span className="text-[10px] text-muted-foreground">live + REST</span>}
          >
            <SignalsFeed restSignals={signals} />
          </Widget>

          {/* Tier 2 Feature: IHSG Live Chart (6 cols × 1 row) */}
          <Widget
            title="Grafik Live IHSG"
            icon={<Activity className="w-3.5 h-3.5" />}
            accent="text-emerald-400"
            className="col-span-6"
            right={<span className="text-[10px] text-muted-foreground tabular-nums">{tickRing.length} tick</span>}
          >
            <IhsgChart ihsg={ihsg} tickRing={tickRing} />
          </Widget>

          {/* Tier 3: Multi-Horizon Projection (6 cols) */}
          <MultiHorizonProjection />

          {/* Tier 3: Engine Orchestration Log (6 cols) */}
          <Widget
            title="Manajemen Engine & Log Orkestrasi"
            icon={<Cpu className="w-3.5 h-3.5" />}
            accent="text-purple-400"
            className="col-span-6"
            bodyClassName="!p-3"
          >
            <EngineOrchestrationLog />
          </Widget>

          {/* Tier 4: BE Observability Console (full width, auto height) */}
          <div className="col-span-12" style={{ gridAutoRows: "auto" }}>
            <ObservabilityConsole />
          </div>
        </div>
      </div>
    </CrosshairProvider>
  );
}
