"use client";

/**
 * Astronacci Trading Dashboard — dense, real-time, single-user.
 *
 * Layout: fixed CSS grid (no page scroll). Seven widget zones:
 *   A: KPI (NAV / Return / PnL / positions)
 *   B: Movers (gainers / losers)
 *   C: IHSG live chart (recharts + WS tick sparkline, crosshair-synced)
 *   D: Portfolio positions table
 *   E: Signals live feed (WS `signals` channel + REST attribution fallback)
 *   F: Market breadth (gainers vs losers, derived from movers)
 *   G: BE Observability Console (SSE logs + status indicators)
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
  Gauge,
  Radio,
  TrendingDown,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { Widget } from "@/components/widget";
import { ObservabilityConsole } from "@/components/observability-console";
import { MarketClockWidget } from "@/components/market-clock-widget";
import { ExchangeTimelineHeader } from "@/components/exchange-timeline-header";
import { CelestialFibonacciChart } from "@/components/celestial-fibonacci-chart";
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
          {data.length > 1 ? `${data.length} tick live` : "menunggu WS tick…"}
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
        <div className="text-muted-foreground/60 italic">Menunggu sinyal…</div>
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
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<string>("");

  // WS tick ring buffer for the IHSG live chart (ref-backed, coalesced).
  const tickRingRef = useRef<{ t: number; p: number }[]>([]);
  const [, bumpRing] = useState(0);

  // ── REST initial load (kept; WS augments live) ──
  const loadData = useCallback(async () => {
    try {
      const [moversRes, ihsgRes, portfolioRes, sigRes] = await Promise.allSettled([
        fetch("/api/prices/movers?limit=5"),
        fetch("/api/prices/ihsg"),
        fetch("/api/portfolio"),
        fetch("/api/signals/attribution?days=7"),
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
      <div className="h-full w-full flex flex-col gap-2 p-2 overflow-hidden">
        {/* Exchange timeline header — global session strip sorted by WIB open time */}
        <ExchangeTimelineHeader />

        {/* IHSG / breadth / FPS compact bar */}
        <div className="flex items-center gap-4 px-3 h-7 rounded-md border border-border/60 bg-card/60 backdrop-blur-sm text-xs overflow-hidden shrink-0">
          <span className="font-semibold text-primary shrink-0">IHSG</span>
          <span className={cn("font-mono shrink-0", changeColor(ihsg?.pct_change))}>
            {ihsg?.price != null ? ihsg.price.toLocaleString("en-US", { maximumFractionDigits: 2 }) : "—"}
            {" "}
            {fmtPct(ihsg?.pct_change)}
          </span>
          <div className="w-px h-3 bg-border/60 shrink-0" />
          <span className="text-muted-foreground shrink-0">G:</span>
          <span className="text-emerald-400 font-mono shrink-0">{breadth.g}</span>
          <span className="text-muted-foreground shrink-0">L:</span>
          <span className="text-red-400 font-mono shrink-0">{breadth.l}</span>
          <div className="ml-auto flex items-center gap-3 shrink-0">
            <span className="text-muted-foreground">Update:</span>
            <span className="font-mono">{lastUpdate || "—"}</span>
            <div className="w-px h-3 bg-border/60" />
            <span className="text-muted-foreground">FPS:</span>
            <span className={cn("font-mono", fps >= 50 ? "text-emerald-400" : fps >= 30 ? "text-yellow-400" : "text-red-400")}>
              {fps.toFixed(0)}
            </span>
          </div>
        </div>

        {/* Main widget grid: 12 cols, 2 rows + observability row */}
        <div
          className="flex-1 min-h-0 grid gap-2"
          style={{
            gridTemplateColumns: "repeat(12, minmax(0, 1fr))",
            gridTemplateRows: "minmax(0, 1fr) minmax(0, 1fr) auto",
          }}
        >
          {/* Row 1 */}
          <Widget
            title="Portofolio"
            icon={<Wallet className="w-3.5 h-3.5" />}
            accent="text-primary"
            className="col-span-3"
            right={<span className="text-[10px] text-muted-foreground">{portfolio?.n_positions ?? 0} pos</span>}
          >
            <div className="space-y-3">
              <div>
                <p className="text-[10px] text-muted-foreground uppercase">NAV</p>
                <p className="text-xl font-bold tabular-nums">Rp {portfolio ? fmtIDR(portfolio.total_nav) : "—"}</p>
              </div>
              <div>
                <p className="text-[10px] text-muted-foreground uppercase">Unrealized PnL</p>
                <p className={cn("text-lg font-bold tabular-nums", totalPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                  {totalPnl >= 0 ? "+" : ""}Rp {fmtIDR(totalPnl)}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-muted-foreground uppercase">Cash</p>
                <p className="text-sm font-mono">Rp {portfolio ? fmtIDR(portfolio.cash) : "—"}</p>
              </div>
            </div>
          </Widget>

          <Widget
            title="Movers"
            icon={<TrendingUp className="w-3.5 h-3.5" />}
            accent="text-emerald-400"
            className="col-span-3"
            right={<span className="text-[10px] text-muted-foreground">{movers?.as_of ?? "—"}</span>}
          >
            <div className="space-y-2 text-xs">
              <div>
                <p className="text-[10px] text-emerald-400/80 uppercase mb-1 flex items-center gap-1">
                  <ArrowUp className="w-3 h-3" /> Gainers
                </p>
                {movers?.gainers.slice(0, 5).map((m) => (
                  <div key={m.ticker} className="flex items-center gap-2 py-0.5">
                    <span className="font-mono font-semibold w-14">{m.ticker}</span>
                    <span className="font-mono ml-auto">{m.close.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
                    <span className="text-emerald-400 font-mono w-16 text-right">{fmtPct(m.pct_change)}</span>
                  </div>
                )) ?? <span className="text-muted-foreground/60 italic">—</span>}
              </div>
              <div>
                <p className="text-[10px] text-red-400/80 uppercase mb-1 flex items-center gap-1">
                  <ArrowDown className="w-3 h-3" /> Losers
                </p>
                {movers?.losers.slice(0, 5).map((m) => (
                  <div key={m.ticker} className="flex items-center gap-2 py-0.5">
                    <span className="font-mono font-semibold w-14">{m.ticker}</span>
                    <span className="font-mono ml-auto">{m.close.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
                    <span className="text-red-400 font-mono w-16 text-right">{fmtPct(m.pct_change)}</span>
                  </div>
                )) ?? <span className="text-muted-foreground/60 italic">—</span>}
              </div>
            </div>
          </Widget>

          <CelestialFibonacciChart
            ticker="^JKSE"
            className="col-span-6"
          />

          {/* Row 2 */}
          <Widget
            title="Posisi"
            icon={<Wallet className="w-3.5 h-3.5" />}
            className="col-span-3"
            right={<span className="text-[10px] text-muted-foreground">{positions.length} pos</span>}
          >
            <div className="text-xs space-y-1">
              {positions.length === 0 ? (
                <div className="text-muted-foreground/60 italic">Belum ada posisi</div>
              ) : (
                positions.slice(0, 12).map(([ticker, p]) => (
                  <div key={ticker} className="flex items-center gap-2 py-0.5 border-b border-border/30 last:border-0">
                    <span className="font-mono font-semibold w-16 shrink-0">{ticker}</span>
                    <span className="font-mono text-muted-foreground text-[10px] w-12 shrink-0">{p.shares}</span>
                    <span className={cn("font-mono ml-auto text-right", p.unrealized_pnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                      {p.unrealized_pnl >= 0 ? "+" : ""}{fmtIDR(p.unrealized_pnl)}
                    </span>
                  </div>
                ))
              )}
            </div>
          </Widget>

          <Widget
            title="Sinyal"
            icon={<TrendingUp className="w-3.5 h-3.5" />}
            accent="text-primary"
            className="col-span-3"
            right={<span className="text-[10px] text-muted-foreground">live + REST</span>}
          >
            <SignalsFeed restSignals={signals} />
          </Widget>

          <Widget
            title="Market Breadth"
            icon={<Gauge className="w-3.5 h-3.5" />}
            accent="text-primary"
            className="col-span-6"
          >
            <div className="space-y-3">
              <div>
                <div className="flex justify-between text-[10px] text-muted-foreground mb-1">
                  <span>Gainers {breadth.g}</span>
                  <span>Losers {breadth.l}</span>
                </div>
                <div className="h-3 rounded-full overflow-hidden flex bg-border/40">
                  <div className="bg-emerald-500/80" style={{ width: `${breadth.gPct}%` }} />
                  <div className="bg-red-500/80" style={{ width: `${breadth.lPct}%` }} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-md border border-border/50 p-2">
                  <p className="text-[10px] text-muted-foreground uppercase">Top Gainer</p>
                  <p className="font-mono font-semibold">
                    {movers?.gainers[0]
                      ? `${movers.gainers[0].ticker} ${fmtPct(movers.gainers[0].pct_change)}`
                      : "—"}
                  </p>
                </div>
                <div className="rounded-md border border-border/50 p-2">
                  <p className="text-[10px] text-muted-foreground uppercase">Top Loser</p>
                  <p className="font-mono font-semibold">
                    {movers?.losers[0]
                      ? `${movers.losers[0].ticker} ${fmtPct(movers.losers[0].pct_change)}`
                      : "—"}
                  </p>
                </div>
              </div>
              <div className="text-[10px] text-muted-foreground italic">
                {loading ? "Memuat data pasar…" : `Diperbarui ${lastUpdate}`}
              </div>
            </div>
          </Widget>

          {/* Global Market Clock */}
          <div className="col-span-3">
            <MarketClockWidget />
          </div>

          {/* Row 3: BE Observability Console (full width) */}
          <div className="col-span-12">
            <ObservabilityConsole />
          </div>
        </div>
      </div>
    </CrosshairProvider>
  );
}
