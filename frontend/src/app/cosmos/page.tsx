"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Orbit,
  Satellite,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Activity,
  Globe2,
  Minus,
} from "lucide-react";

// ── Tipe data dari /api/cosmos ────────────────────────────────────────────────

interface Body {
  name: string;
  kind: string;
  lon_deg: number;
  zodiac: string;
  distance_au: number;
  orbit_ring: number;
  retrograde?: boolean;
  phase?: number;
  phase_name?: string;
  illumination_pct?: number;
  age_days?: number;
}

interface ActiveCycle {
  cycle_type: string;
  title: string;
  start_at: string;
  end_at: string;
  potential_impact: string;
  expected_reversal: string;
  description: string;
}

interface AstronacciResponse {
  as_of: string;
  bodies: Body[];
  zodiac_signs: string[];
  active_cycles: ActiveCycle[];
  signal: {
    active_cycles: string[];
    time_signal: number;
    volatility_signal: number;
    confidence: number;
    cycle_count: number;
    confluence: {
      matched: boolean;
      ratio: number;
      fib_price: number;
      current_price: number;
      distance_pct: number;
      direction: string;
      swing_high: number;
      swing_low: number;
    } | null;
  };
}

interface LatestObs {
  metric: string;
  value: number;
  date: string | null;
  source: string;
}

interface SatelliteItem {
  location_name: string;
  lat: number;
  lon: number;
  sector: string | null;
  ticker: string | null;
  source: string;
  metrics: string[];
  latest: LatestObs[];
}

interface SatellitesResponse {
  as_of: string;
  count: number;
  satellites: SatelliteItem[];
  metric_legend: { code: string; label: string }[];
}

interface ExchangeIndex {
  ticker: string;
  name: string;
  close: number;
  open: number;
  high: number;
  low: number;
  change_pct: number | null;
  timestamp: string | null;
}

interface Exchange {
  mic: string;
  city: string;
  lat: number;
  lon: number;
  country_code: string;
  timezone: string;
  currency: string;
  trading_hours: string;
  index: ExchangeIndex | null;
  market_status: {
    is_open: boolean;
    local_time: string | null;
    reason: string;
  };
}

interface SolarPosition {
  lat: number;
  lon: number;
  utc_time: string;
}

interface DominoEntry {
  mic: string;
  city: string;
  local_open: string;
  is_open: boolean;
  index_change_pct: number | null;
}

interface SectorCount {
  name: string;
  count: number;
}

interface FearGreed {
  value: number;
  label: string;
  date: string;
}

interface Commodity {
  ticker: string;
  name: string;
  close: number;
  change_pct: number | null;
}

interface Kurs {
  ticker: string;
  pair: string;
  close: number | null;
  change_pct: number | null;
  as_of: string;
}

interface IdStock {
  ticker: string;
  name: string;
  close: number;
  change_pct: number | null;
}

interface ExchangesResponse {
  as_of: string;
  open_count: number;
  total_count: number;
  exchanges: Exchange[];
  solar_position: SolarPosition | null;
  domino: {
    chain: DominoEntry[];
    last_closed: DominoEntry | null;
    next_to_open: DominoEntry | null;
  };
  sectors: SectorCount[];
  fear_greed: FearGreed | null;
  commodities: Commodity[];
  ihsg_sparkline: number[];
}

// ── Konstanta visual ──────────────────────────────────────────────────────────

const PLANET_COLORS: Record<string, string> = {
  SUN: "#FFD23F",
  MOON: "#E8E8E8",
  MERCURY: "#A9A9A9",
  VENUS: "#E8B873",
  EARTH: "#4A90D9",
  MARS: "#E27B58",
  JUPITER: "#D8A47F",
  SATURN: "#E3C28B",
  URANUS: "#9DD9D2",
  NEPTUNE: "#5B7FFF",
  PLUTO: "#B8A088",
};

const PLANET_RADIUS: Record<string, number> = {
  SUN: 10,
  MOON: 3,
  MERCURY: 2.5,
  VENUS: 3,
  EARTH: 3.5,
  MARS: 2.5,
  JUPITER: 5,
  SATURN: 4,
  URANUS: 3.5,
  NEPTUNE: 3.5,
  PLUTO: 2,
};

const ORBIT_SPEED: Record<number, number> = {
  1: 0.35, 2: 0.22, 3: 0.16, 4: 0.12, 5: 0.07, 6: 0.05, 7: 0.035, 8: 0.025, 9: 0.018,
};

const IMPACT_COLOR: Record<string, string> = {
  CRITICAL: "#FF3B3B",
  HIGH: "#FF8C42",
  MEDIUM: "#FFD23F",
  LOW: "#6CB4EE",
};

const REVERSAL_ICON: Record<string, string> = {
  BEARISH_REVERSAL: "▼",
  BULLISH_REVERSAL: "▲",
  VOLATILITY: "◆",
  NEUTRAL: "●",
};

type LandPolygon = number[][];

// ── Komponen utama ────────────────────────────────────────────────────────────

export default function CosmosPage() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const starsRef = useRef<{ x: number; y: number; r: number; tw: number }[]>([]);
  const animRef = useRef<number>(0);
  const startTimeRef = useRef<number>(0);
  const landRef = useRef<LandPolygon[]>([]);
  const dataRef = useRef<{
    astro: AstronacciResponse | null;
    sats: SatelliteItem[];
    exchanges: Exchange[];
    solar: SolarPosition | null;
  }>({ astro: null, sats: [], exchanges: [], solar: null });

  // Bottom strip data
  const [domino, setDomino] = useState<ExchangesResponse["domino"] | null>(null);
  const [sectors, setSectors] = useState<SectorCount[]>([]);
  const [fearGreed, setFearGreed] = useState<FearGreed | null>(null);
  const [commodities, setCommodities] = useState<Commodity[]>([]);
  const [ihsgSparkline, setIhsgSparkline] = useState<number[]>([]);
  const [kurs, setKurs] = useState<Kurs[]>([]);
  const [idStocks, setIdStocks] = useState<IdStock[]>([]);
  const [topTab, setTopTab] = useState<"zodiak" | "komoditas" | "jam" | "ihsg">("zodiak");
  const [rotateTab, setRotateTab] = useState<"sinyal" | "siklus" | "bulan">("sinyal");

  const [astro, setAstro] = useState<AstronacciResponse | null>(null);
  const [sats, setSats] = useState<SatelliteItem[]>([]);
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [solarPos, setSolarPos] = useState<SolarPosition | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<string>("");
  const [paused, setPaused] = useState(false);

  // ── Fetch data ──
  const fetchData = useCallback(async () => {
    try {
      const [aRes, sRes, eRes, kRes, idRes] = await Promise.all([
        fetch("/api/cosmos/astronacci?days=7"),
        fetch("/api/cosmos/satellites?limit=80"),
        fetch("/api/cosmos/exchanges"),
        fetch("/api/cosmos/kurs"),
        fetch("/api/cosmos/id_stocks"),
      ]);
      if (!aRes.ok || !sRes.ok || !eRes.ok || !kRes.ok || !idRes.ok)
        throw new Error(`HTTP ${aRes.status}/${sRes.status}/${eRes.status}/${kRes.status}/${idRes.status}`);
      const a: AstronacciResponse = await aRes.json();
      const s: SatellitesResponse = await sRes.json();
      const e: ExchangesResponse = await eRes.json();
      const k: Kurs[] = await kRes.json();
      const i: IdStock[] = await idRes.json();
      setAstro(a);
      setSats(s.satellites);
      setExchanges(e.exchanges);
      setSolarPos(e.solar_position);
      setDomino(e.domino);
      setSectors(e.sectors);
      setFearGreed(e.fear_greed);
      setCommodities(e.commodities);
      setIhsgSparkline(e.ihsg_sparkline);
      setKurs(k);
      setIdStocks(i);
      dataRef.current = { astro: a, sats: s.satellites, exchanges: e.exchanges, solar: e.solar_position };
      setLastUpdate(new Date().toLocaleTimeString("id-ID", { hour12: false }));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal memuat data kosmos");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 60_000);
    return () => clearInterval(id);
  }, [fetchData]);

  // ── Fetch land polygon data sekali ──
  useEffect(() => {
    let cancelled = false;
    fetch("/world-land-simple.json")
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled && data.polygons) {
          landRef.current = data.polygons as LandPolygon[];
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

// ── Helper: format jam lokal bursa ────────────────────────────────────────────

/** Format ISO timestamp ke "HH:MM" dalam timezone bursa. */
/** Component untuk menampilkan % change dengan simbol segitiga ▲ ▼ */
function ChangeBadge({
  value,
  decimals = 2,
  className = "",
}: {
  value: number | null | undefined;
  decimals?: number;
  className?: string;
}) {
  if (value == null) return <span className={`text-white/30 ${className}`}>—</span>;
  const sign = value > 0 ? "+" : "";
  const color = value > 0 ? "text-emerald-400" : value < 0 ? "text-red-400" : "text-white/50";
  const arrow = value > 0 ? "▲" : value < 0 ? "▼" : "—";
  return (
    <span className={`inline-flex items-center gap-0.5 font-mono ${color} ${className}`}>
      {arrow} {sign}{value.toFixed(decimals)}%
    </span>
  );
}

function formatLocalTime(iso: string, timezone: string): string {
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return "—";
    return d.toLocaleTimeString("en-GB", {
      timeZone: timezone,
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  } catch {
    return "—";
  }
}

  // ── Generate starfield sekali ──
  useEffect(() => {
    const stars: { x: number; y: number; r: number; tw: number }[] = [];
    for (let i = 0; i < 200; i++) {
      stars.push({
        x: Math.random(),
        y: Math.random(),
        r: Math.random() * 1.2 + 0.2,
        tw: Math.random() * Math.PI * 2,
      });
    }
    starsRef.current = stars;
  }, []);

  // ── Orthographic projection helper ──
  const project = (
    lonDeg: number,
    latDeg: number,
    rotation: number,
    cx: number,
    cy: number,
    r: number,
  ) => {
    const lonRad = (lonDeg * Math.PI) / 180 + rotation;
    const latRad = (latDeg * Math.PI) / 180;
    const x3d = Math.cos(latRad) * Math.cos(lonRad);
    const y3d = Math.cos(latRad) * Math.sin(lonRad);
    const z3d = Math.sin(latRad);
    return {
      x: cx + y3d * r,
      y: cy - z3d * r,
      visible: x3d > -0.02,
      depth: x3d,
    };
  };

  // ── Main canvas: EARTH GLOBE (full screen) ──
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      canvas.style.width = `${window.innerWidth}px`;
      canvas.style.height = `${window.innerHeight}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    if (!startTimeRef.current) startTimeRef.current = performance.now();

    const draw = (now: number) => {
      const t = paused ? 0 : (now - startTimeRef.current) / 1000;
      const W = window.innerWidth;
      const H = window.innerHeight;
      const cx = W / 2;
      const cy = H / 2;
      const earthR = Math.min(W, H) * 0.38; // globe besar di tengah
      const rotation = t * 0.08;

      // Background
      ctx.fillStyle = "#05060f";
      ctx.fillRect(0, 0, W, H);

      // Stars (background)
      const stars = starsRef.current;
      for (const s of stars) {
        const sx = s.x * W;
        const sy = s.y * H;
        const alpha = 0.3 + 0.5 * Math.abs(Math.sin(s.tw + t * 0.3));
        ctx.fillStyle = `rgba(255,255,255,${alpha * 0.6})`;
        ctx.beginPath();
        ctx.arc(sx, sy, s.r, 0, Math.PI * 2);
        ctx.fill();
      }

      // Atmosphere glow (outer)
      const atmGrad = ctx.createRadialGradient(cx, cy, earthR, cx, cy, earthR + 30);
      atmGrad.addColorStop(0, "rgba(100,180,255,0.25)");
      atmGrad.addColorStop(1, "rgba(100,180,255,0)");
      ctx.fillStyle = atmGrad;
      ctx.beginPath();
      ctx.arc(cx, cy, earthR + 30, 0, Math.PI * 2);
      ctx.fill();

      // Ocean base
      const oceanGrad = ctx.createRadialGradient(
        cx - earthR * 0.3,
        cy - earthR * 0.3,
        earthR * 0.1,
        cx,
        cy,
        earthR,
      );
      oceanGrad.addColorStop(0, "#3a7bd5");
      oceanGrad.addColorStop(0.6, "#1a4a8a");
      oceanGrad.addColorStop(1, "#0a2a5a");
      ctx.fillStyle = oceanGrad;
      ctx.beginPath();
      ctx.arc(cx, cy, earthR, 0, Math.PI * 2);
      ctx.fill();

      // ── Continents ──
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, earthR, 0, Math.PI * 2);
      ctx.clip();

      const landPolygons = landRef.current;
      for (const polygon of landPolygons) {
        if (polygon.length < 3) continue;
        const projected = polygon.map((pt) =>
          project(pt[0], pt[1], rotation, cx, cy, earthR),
        );
        const anyVisible = projected.some((p) => p.visible);
        if (!anyVisible) continue;

        ctx.beginPath();
        let started = false;
        for (const p of projected) {
          if (!p.visible) {
            if (started) {
              ctx.fill();
              ctx.beginPath();
              started = false;
            }
            continue;
          }
          if (!started) {
            ctx.moveTo(p.x, p.y);
            started = true;
          } else {
            ctx.lineTo(p.x, p.y);
          }
        }
        if (started) {
          const visiblePts = projected.filter((p) => p.visible);
          const avgDepth =
            visiblePts.reduce((s, p) => s + p.depth, 0) / visiblePts.length;
          const shade = 0.5 + avgDepth * 0.4;
          ctx.fillStyle = `rgba(${Math.round(55 * shade)}, ${Math.round(130 * shade)}, ${Math.round(
            68 * shade,
          )}, 0.9)`;
          ctx.fill();
          ctx.strokeStyle = `rgba(35, 80, 45, ${0.3 * shade})`;
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }
      }

      // Graticule
      ctx.strokeStyle = "rgba(100,140,200,0.06)";
      ctx.lineWidth = 0.5;
      for (let lon = -180; lon < 180; lon += 30) {
        ctx.beginPath();
        let first = true;
        for (let lat = -90; lat <= 90; lat += 5) {
          const p = project(lon, lat, rotation, cx, cy, earthR);
          if (p.visible) {
            if (first) { ctx.moveTo(p.x, p.y); first = false; }
            else ctx.lineTo(p.x, p.y);
          } else first = true;
        }
        ctx.stroke();
      }
      for (let lat = -60; lat <= 60; lat += 30) {
        ctx.beginPath();
        let first = true;
        for (let lon = -180; lon <= 180; lon += 5) {
          const p = project(lon, lat, rotation, cx, cy, earthR);
          if (p.visible) {
            if (first) { ctx.moveTo(p.x, p.y); first = false; }
            else ctx.lineTo(p.x, p.y);
          } else first = true;
        }
        ctx.stroke();
      }
      // Equator
      ctx.strokeStyle = "rgba(255,200,100,0.1)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      let first = true;
      for (let lon = -180; lon <= 180; lon += 5) {
        const p = project(lon, 0, rotation, cx, cy, earthR);
        if (p.visible) {
          if (first) { ctx.moveTo(p.x, p.y); first = false; }
          else ctx.lineTo(p.x, p.y);
        } else first = true;
      }
      ctx.stroke();

      // ── Exchange markers ──
      const exchanges = dataRef.current.exchanges;
      for (const ex of exchanges) {
        const p = project(ex.lon, ex.lat, rotation, cx, cy, earthR);
        if (!p.visible) continue;

        const isOpen = ex.market_status.is_open;
        const markerColor = isOpen ? "#22c55e" : "#64748b";
        const glowColor = isOpen ? "rgba(34,197,94,0.4)" : "rgba(100,116,139,0.2)";

        // Pulsing glow for open markets
        if (isOpen) {
          const pulse = 0.5 + 0.5 * Math.sin(t * 2.5 + ex.lon * 0.05);
          const glowR = 8 + pulse * 4;
          const glow = ctx.createRadialGradient(p.x, p.y, 2, p.x, p.y, glowR);
          glow.addColorStop(0, `rgba(34,197,94,${0.5 + pulse * 0.3})`);
          glow.addColorStop(1, "rgba(34,197,94,0)");
          ctx.fillStyle = glow;
          ctx.beginPath();
          ctx.arc(p.x, p.y, glowR, 0, Math.PI * 2);
          ctx.fill();
        }

        // Marker dot
        ctx.fillStyle = markerColor;
        ctx.beginPath();
        ctx.arc(p.x, p.y, isOpen ? 4 : 3, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,0.6)";
        ctx.lineWidth = 0.8;
        ctx.stroke();

        // Label: city name + index value + local time
        const idx = ex.index;
        const arrow = idx?.change_pct != null ? (idx.change_pct > 0 ? "▲" : idx.change_pct < 0 ? "▼" : "—") : "";
        const changeStr = idx?.change_pct != null
          ? `${arrow} ${idx.change_pct > 0 ? "+" : ""}${idx.change_pct.toFixed(2)}%`
          : "";
        const changeColor = idx?.change_pct != null
          ? idx.change_pct > 0
            ? "#4ade80"
            : idx.change_pct < 0
              ? "#f87171"
              : "#94a3b8"
          : "#94a3b8";

        // Label background — 3 baris: kota, jam lokal, indeks+change
        const label1 = ex.city;
        const localTimeStr = ex.market_status.local_time
          ? formatLocalTime(ex.market_status.local_time, ex.timezone)
          : "—";
        const label2 = `${localTimeStr}${isOpen ? " ●" : ""}`;
        const label3 = idx ? `${idx.close.toLocaleString("en-US", { maximumFractionDigits: 0 })} ${changeStr}` : "—";
        ctx.font = "bold 10px monospace";
        const w1 = ctx.measureText(label1).width;
        ctx.font = "9px monospace";
        const w2 = ctx.measureText(label2).width;
        const w3 = ctx.measureText(label3).width;
        const labelW = Math.max(w1, w2, w3) + 8;
        const labelH = 40;
        const labelX = p.x + 8;
        const labelY = p.y - labelH / 2;

        ctx.fillStyle = "rgba(0,0,0,0.55)";
        ctx.fillRect(labelX, labelY, labelW, labelH);
        ctx.strokeStyle = `${markerColor}66`;
        ctx.lineWidth = 0.5;
        ctx.strokeRect(labelX, labelY, labelW, labelH);

        ctx.textAlign = "left";
        ctx.textBaseline = "top";
        ctx.fillStyle = "rgba(255,255,255,0.9)";
        ctx.font = "bold 10px monospace";
        ctx.fillText(label1, labelX + 4, labelY + 3);
        ctx.fillStyle = isOpen ? "#4ade80" : "rgba(180,180,200,0.6)";
        ctx.font = "9px monospace";
        ctx.fillText(label2, labelX + 4, labelY + 15);
        ctx.fillStyle = changeColor;
        ctx.font = "9px monospace";
        ctx.fillText(label3, labelX + 4, labelY + 27);
      }

      // ── Satellite markers (small dots) ──
      const sats = dataRef.current.sats;
      const maxSats = Math.min(sats.length, 60);
      for (let i = 0; i < maxSats; i++) {
        const s = sats[i];
        const p = project(s.lon, s.lat, rotation, cx, cy, earthR);
        if (!p.visible) continue;
        const hasObs = s.latest.length > 0;
        ctx.fillStyle = hasObs ? "rgba(120,220,255,0.7)" : "rgba(120,180,220,0.3)";
        ctx.beginPath();
        ctx.arc(p.x, p.y, hasObs ? 1.5 : 1, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.restore(); // end clip

      // ── Day/night terminator + Sun marker ──
      // Matahari di depan viewer (tidak mengelilingi Bumi).
      // Sisi globe yang terlihat user = siang, sisi belakang = malam.
      const sunGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, earthR * 1.4);
      sunGlow.addColorStop(0, "rgba(255,220,100,0)");
      sunGlow.addColorStop(0.55, "rgba(255,220,100,0.05)");
      sunGlow.addColorStop(0.8, "rgba(255,220,80,0.12)");
      sunGlow.addColorStop(1, "rgba(255,180,40,0)");
      ctx.fillStyle = sunGlow;
      ctx.beginPath();
      ctx.arc(cx, cy, earthR * 1.4, 0, Math.PI * 2);
      ctx.fill();

      // Night gradient: sisi depan (tengah) terang, menuju rim semakin gelap (senja/malam)
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, earthR, 0, Math.PI * 2);
      ctx.clip();
      const nightGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, earthR);
      nightGrad.addColorStop(0, "rgba(0,0,20,0)");
      nightGrad.addColorStop(0.65, "rgba(0,0,20,0)");
      nightGrad.addColorStop(0.85, "rgba(0,0,20,0.15)");
      nightGrad.addColorStop(1, "rgba(0,0,20,0.45)");
      ctx.fillStyle = nightGrad;
      ctx.fillRect(cx - earthR, cy - earthR, earthR * 2, earthR * 2);

      // City lights: titik-titik kuning di area senja (depth rendah) dan malam
      for (const ex of exchanges) {
        const p = project(ex.lon, ex.lat, rotation, cx, cy, earthR);
        if (!p.visible) continue;
        if (p.depth > 0.25) continue; // day side
        const flicker = 0.6 + 0.4 * Math.sin(t * 3 + ex.lon * 0.1);
        ctx.fillStyle = `rgba(255,220,100,${flicker * 0.5})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 1.5, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();

      // Sun marker di depan viewer (pojok kanan atas, tidak mengorbit)
      const sunX = cx + earthR * 0.9;
      const sunY = cy - earthR * 0.7;
      const sunGlow2 = ctx.createRadialGradient(sunX, sunY, 4, sunX, sunY, 35);
      sunGlow2.addColorStop(0, "rgba(255,220,80,0.5)");
      sunGlow2.addColorStop(0.5, "rgba(255,180,40,0.2)");
      sunGlow2.addColorStop(1, "rgba(255,180,40,0)");
      ctx.fillStyle = sunGlow2;
      ctx.beginPath();
      ctx.arc(sunX, sunY, 35, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "rgba(255,235,100,0.9)";
      ctx.beginPath();
      ctx.arc(sunX, sunY, 5, 0, Math.PI * 2);
      ctx.fill();
      // Sun rays (statis, tidak berputar)
      for (let a = 0; a < 8; a++) {
        const ang = (a / 8) * Math.PI * 2 + t * 0.1;
        const r1 = 7, r2 = 12;
        ctx.strokeStyle = "rgba(255,220,80,0.3)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(sunX + Math.cos(ang) * r1, sunY + Math.sin(ang) * r1);
        ctx.lineTo(sunX + Math.cos(ang) * r2, sunY + Math.sin(ang) * r2);
        ctx.stroke();
      }

      // Rim light
      ctx.strokeStyle = "rgba(120,200,255,0.35)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(cx, cy, earthR, 0, Math.PI * 2);
      ctx.stroke();

      // ── Moon orbiting Earth ──
      const moon = dataRef.current.astro?.bodies.find((b) => b.name === "MOON");
      if (moon) {
        const moonOrbitR = earthR + 40;
        const moonAng = (moon.lon_deg * Math.PI) / 180 + t * 0.3;
        const mx = cx + Math.cos(moonAng) * moonOrbitR;
        const my = cy + Math.sin(moonAng) * moonOrbitR * 0.35;
        ctx.strokeStyle = "rgba(232,232,232,0.1)";
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        ctx.ellipse(cx, cy, moonOrbitR, moonOrbitR * 0.35, 0, 0, Math.PI * 2);
        ctx.stroke();
        // Moon glow
        const moonGlow = ctx.createRadialGradient(mx, my, 1, mx, my, 12);
        moonGlow.addColorStop(0, "rgba(232,232,232,0.4)");
        moonGlow.addColorStop(1, "rgba(232,232,232,0)");
        ctx.fillStyle = moonGlow;
        ctx.beginPath();
        ctx.arc(mx, my, 12, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#E8E8E8";
        ctx.beginPath();
        ctx.arc(mx, my, 5, 0, Math.PI * 2);
        ctx.fill();
        if (moon.phase !== undefined) {
          const illum = moon.phase <= 0.5 ? moon.phase * 2 : (1 - moon.phase) * 2;
          if (illum < 0.95) {
            ctx.fillStyle = `rgba(10,10,30,${1 - illum})`;
            ctx.beginPath();
            ctx.arc(mx + (1 - illum) * 2.5, my, 5, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }

      // ── Capital flow arcs (domino effect) ──
      // Arc antar bursa + arc penutup New York → Sydney (siklus)
      const exchangesData = dataRef.current.exchanges;
      const dominoChain = exchangesData
        .slice()
        .sort((a, b) => b.lon - a.lon); // east first
      const arcPairs: [number, number][] = [];
      for (let i = 0; i < dominoChain.length - 1; i++) {
        arcPairs.push([i, i + 1]);
      }
      if (dominoChain.length > 2) {
        arcPairs.push([dominoChain.length - 1, 0]); // New York → Sydney
      }
      for (const [fromIdx, toIdx] of arcPairs) {
        const i = fromIdx;
        const from = dominoChain[fromIdx];
        const to = dominoChain[toIdx];
        const pFrom = project(from.lon, from.lat, rotation, cx, cy, earthR);
        const pTo = project(to.lon, to.lat, rotation, cx, cy, earthR);
        if (!pFrom.visible || !pTo.visible) continue;

        const midX = (pFrom.x + pTo.x) / 2;
        const midY = (pFrom.y + pTo.y) / 2;
        const dist = Math.hypot(pTo.x - pFrom.x, pTo.y - pFrom.y);
        const arcHeight = Math.min(dist * 0.2, 25);
        const apexX = midX;
        const apexY = midY - arcHeight;

        const fromChg = from.index?.change_pct;
        const arcColor = fromChg != null
          ? fromChg > 0 ? "rgba(74,222,128," : fromChg < 0 ? "rgba(248,113,113," : "rgba(148,163,184,"
          : "rgba(100,200,255,";

        ctx.strokeStyle = arcColor + "0.25)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pFrom.x, pFrom.y);
        ctx.quadraticCurveTo(apexX, apexY, pTo.x, pTo.y);
        ctx.stroke();

        // Animated arrow
        const progress = ((t * 0.25 + i * 0.12) % 1);
        const px = pFrom.x * (1 - progress) * (1 - progress) + 2 * apexX * progress * (1 - progress) + pTo.x * progress * progress;
        const py = pFrom.y * (1 - progress) * (1 - progress) + 2 * apexY * progress * (1 - progress) + pTo.y * progress * progress;
        const dt = 0.01;
        const p2x = pFrom.x * (1 - progress - dt) * (1 - progress - dt) + 2 * apexX * (progress + dt) * (1 - progress - dt) + pTo.x * (progress + dt) * (progress + dt);
        const p2y = pFrom.y * (1 - progress - dt) * (1 - progress - dt) + 2 * apexY * (progress + dt) * (1 - progress - dt) + pTo.y * (progress + dt) * (progress + dt);
        const angle = Math.atan2(p2y - py, p2x - px);
        ctx.save();
        ctx.translate(px, py);
        ctx.rotate(angle);
        ctx.fillStyle = arcColor + "0.9)";
        ctx.beginPath();
        ctx.moveTo(4, 0);
        ctx.lineTo(-3, -2.5);
        ctx.lineTo(-3, 2.5);
        ctx.closePath();
        ctx.fill();
        ctx.restore();

        // Label % change mengikuti panah (bergerak bersama)
        if (fromChg != null) {
          const arrow = fromChg > 0 ? "▲" : fromChg < 0 ? "▼" : "—";
          const label = `${arrow} ${fromChg > 0 ? "+" : ""}${fromChg.toFixed(2)}%`;
          ctx.font = "bold 8px monospace";
          const labelW = ctx.measureText(label).width + 4;
          const labelH = 10;
          const labelX = px - labelW / 2;
          const labelY = py - 16;
          ctx.fillStyle = "rgba(0,0,0,0.5)";
          ctx.fillRect(labelX, labelY, labelW, labelH);
          ctx.strokeStyle = arcColor + "0.4)";
          ctx.lineWidth = 0.5;
          ctx.strokeRect(labelX, labelY, labelW, labelH);
          ctx.fillStyle = fromChg > 0 ? "#4ade80" : fromChg < 0 ? "#f87171" : "#94a3b8";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(label, px, labelY + labelH / 2);
        }
      }

      animRef.current = requestAnimationFrame(draw);
    };

    animRef.current = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(animRef.current);
      window.removeEventListener("resize", resize);
    };
  }, [paused, project]);

  // ── Derived display values ──
  const moonBody = useMemo(() => astro?.bodies.find((b) => b.name === "MOON"), [astro]);
  const signal = astro?.signal;
  const openExchanges = useMemo(
    () => exchanges.filter((e) => e.market_status.is_open),
    [exchanges],
  );

  const signalTone =
    signal && signal.time_signal < -0.05
      ? "bearish"
      : signal && signal.time_signal > 0.05
        ? "bullish"
        : "neutral";

  return (
    <div className="fixed inset-0 z-50 bg-[#05060f] overflow-hidden cosmos-no-scrollbar">
      <canvas ref={canvasRef} className="absolute inset-0" />

      {/* ── Tombol kembali + Judul + Pause (top, minimal) ── */}
      <div className="absolute top-3 left-4 z-10 flex items-center gap-3">
        <Link
          href="/"
          className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-white/5 hover:bg-white/10 border border-white/10 text-white/80 text-sm backdrop-blur-sm transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Dashboard
        </Link>
        <div className="text-white/60 text-sm flex items-center gap-1.5 pointer-events-none">
          <Globe2 className="w-4 h-4 text-sky-300" />
          Bursa Global & Alam Semesta
        </div>
      </div>

      <div className="absolute top-3 right-4 z-10 flex items-center gap-2">
        <span className="text-white/40 text-[10px]">
          {lastUpdate ? `${lastUpdate} WIB` : "memuat…"} · {openExchanges.length}/{exchanges.length} buka
        </span>
        <button
          onClick={() => setPaused((p) => !p)}
          className="px-2.5 py-1.5 rounded-md bg-white/5 hover:bg-white/10 border border-white/10 text-white/80 text-xs backdrop-blur-sm transition-colors"
        >
          {paused ? "▶ Lanjut" : "⏸ Jeda"}
        </button>
      </div>

      {/* ── Panel kiri: Saham LQ & Likuid (penuh) ── */}
      <div className="absolute top-20 bottom-40 left-4 z-10 w-60 rounded-lg bg-black/10 border border-white/10 backdrop-blur-md p-3 flex flex-col">
        <div className="flex items-center gap-1.5 mb-2">
          <TrendingUp className="w-4 h-4 text-emerald-400" />
          <h2 className="text-white/90 text-sm font-semibold">Saham LQ & Likuid</h2>
        </div>
        {idStocks.length > 0 ? (
          <div className="flex-1 overflow-y-auto space-y-1">
            {idStocks.map((s) => (
              <div key={s.ticker} className="flex items-center justify-between gap-2 text-[10px] py-0.5 border-b border-white/5 last:border-0">
                <div className="truncate">
                  <div className="text-white/80 font-medium truncate">{s.name}</div>
                  <div className="text-white/40 text-[9px] font-mono">{s.ticker.replace(".JK", "")}</div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-white/80 font-mono">{s.close.toLocaleString("en-US", { maximumFractionDigits: 0 })}</div>
                  <ChangeBadge value={s.change_pct} decimals={2} className="text-[9px]" />
                </div>
              </div>
            ))}
          </div>
        ) : <p className="text-white/40 text-xs">memuat…</p>}
      </div>

      {/* ── Panel kanan: Indonesia, Forex, Komoditas (stack) ── */}
      <div className="absolute top-20 right-4 z-10 w-56 flex flex-col gap-2">
        {/* Indonesia & IHSG */}
        <div className="rounded-lg bg-black/10 border border-white/10 backdrop-blur-md p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <Globe2 className="w-4 h-4 text-emerald-400" />
            <h2 className="text-white/90 text-sm font-semibold">Indonesia & IHSG</h2>
          </div>
          {(() => {
            const ihsg = exchanges.find((e) => e.mic === "XIDX");
            const idx = ihsg?.index;
            return ihsg ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-white/70 text-[10px]">IHSG</span>
                  <div className="flex items-center gap-1 text-xs font-mono font-bold text-white/80">
                    {idx ? idx.close.toLocaleString("en-US", { maximumFractionDigits: 0 }) : "—"}
                    <ChangeBadge value={idx?.change_pct} decimals={2} className="text-xs" />
                  </div>
                </div>
                <IhsgSparkline sparkline={ihsgSparkline} exchanges={exchanges} />
                <div className="text-[10px] text-white/50">
                  <span className="text-white/70">Bursa:</span> {ihsg.city} · {ihsg.market_status.is_open ? "Buka" : "Tutup"}
                </div>
                <div className="text-[10px] text-white/50">
                  <span className="text-white/70">Waktu lokal:</span> {ihsg.market_status.local_time ? new Date(ihsg.market_status.local_time).toLocaleTimeString("en-GB", { timeZone: ihsg.timezone, hour: "2-digit", minute: "2-digit" }) : "—"}
                </div>
              </div>
            ) : <p className="text-white/40 text-xs">data tidak tersedia</p>;
          })()}
        </div>

        {/* Forex */}
        <div className="rounded-lg bg-black/10 border border-white/10 backdrop-blur-md p-3">
          <div className="text-[10px] text-white/70 font-semibold mb-1.5">Forex</div>
          {kurs.length > 0 ? (
            <div className="grid grid-cols-2 gap-x-2 gap-y-1">
              {kurs.map((k) => (
                <div key={k.ticker} className="flex items-center justify-between text-[9px]">
                  <span className="text-white/60">{k.pair.split("/")[0]}</span>
                  <div className="text-right">
                    <div className="text-white/80 font-mono">{k.close != null ? k.close.toLocaleString("en-US", { maximumFractionDigits: 0 }) : "—"}</div>
                    <ChangeBadge value={k.change_pct} decimals={2} className="text-[8px]" />
                  </div>
                </div>
              ))}
            </div>
          ) : <p className="text-white/40 text-[9px]">memuat…</p>}
        </div>

        {/* Komoditas & VIX */}
        <div className="rounded-lg bg-black/10 border border-white/10 backdrop-blur-md p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <TrendingUp className="w-4 h-4 text-amber-300" />
            <h2 className="text-white/90 text-sm font-semibold">Komoditas & VIX</h2>
          </div>
          <div className="space-y-1">
            {commodities.length > 0 ? commodities.map((c) => {
              const chg = c.change_pct;
              return (
                <div key={c.ticker} className="flex items-center justify-between text-[11px]">
                  <span className="text-white/80 font-medium">{c.name}</span>
                  <div className="text-right">
                    <div className="text-white/80 font-mono">{c.close.toLocaleString("en-US", { maximumFractionDigits: 2 })}</div>
                    <ChangeBadge value={chg} decimals={2} className="text-[9px]" />
                  </div>
                </div>
              );
            }) : <p className="text-white/40 text-xs">memuat…</p>}
          </div>
        </div>
      </div>

      {/* ── Bottom strip: semua panel horizontal ── */}
      <div className="absolute bottom-7 left-0 right-0 z-10 flex items-stretch gap-2 px-3">
        {/* Panel 1: Efek Domino Bursa */}
        {domino && domino.chain.length > 0 && (
          <div className="rounded-lg bg-black/10 border border-white/10 backdrop-blur-md p-2 flex-shrink-0 w-64 max-h-32 overflow-y-auto">
            <div className="flex items-center gap-1.5 mb-1.5">
              <TrendingUp className="w-3 h-3 text-amber-300" />
              <h2 className="text-white/80 text-[11px] font-semibold">Efek Domino Bursa</h2>
            </div>
            <div className="grid grid-cols-2 gap-0.5">
              {domino.chain.map((d, i) => {
                const chg = d.index_change_pct;
                const chgColor =
                  chg != null
                    ? chg > 0 ? "text-emerald-400" : chg < 0 ? "text-red-400" : "text-white/50"
                    : "text-white/30";
                const isLast = domino.last_closed?.mic === d.mic;
                const isNext = domino.next_to_open?.mic === d.mic;
                const borderColor = d.is_open
                  ? "border-emerald-500/40"
                  : isLast ? "border-amber-500/40"
                  : isNext ? "border-emerald-500/40"
                  : "border-red-500/30";
                const bgColor = d.is_open
                  ? "bg-emerald-500/15"
                  : isLast ? "bg-amber-500/15"
                  : isNext ? "bg-emerald-500/10"
                  : "bg-red-500/10";
                const blinkClass = d.is_open ? "animate-blink" : "";
                return (
                  <div
                    key={d.mic + i}
                    className={`flex items-center justify-between gap-1 px-1.5 py-1 rounded border ${borderColor} ${bgColor} ${blinkClass}`}
                    title={`${d.city} (${d.mic})`}
                  >
                    <span className="text-[10px] text-white/80 font-medium truncate">{d.city}</span>
                    <span className={`flex items-center gap-0.5 text-[10px] font-mono font-bold ${chgColor} shrink-0`}>
                      {chg != null ? (
                        `${chg > 0 ? "▲" : chg < 0 ? "▼" : "—"} ${chg > 0 ? "+" : ""}${chg.toFixed(2)}%`
                      ) : "—"}
                    </span>
                  </div>
                );
              })}
            </div>
            {domino.last_closed && domino.next_to_open && (
              <div className="mt-1.5 text-[8px] text-white/50">
                <span className="text-amber-400">{domino.last_closed.city}</span>
                {" tutup → "}
                <span className="text-sky-400">{domino.next_to_open.city}</span>
                {" buka"}
              </div>
            )}
          </div>
        )}

        {/* Panel 2: Sektor Instrument */}
        {sectors.length > 0 && (
          <div className="rounded-lg bg-black/10 border border-white/10 backdrop-blur-md p-2 flex-shrink-0 w-52 max-h-32 overflow-y-auto">
            <div className="flex items-center gap-1.5 mb-1.5">
              <Activity className="w-3 h-3 text-sky-300" />
              <h2 className="text-white/80 text-[11px] font-semibold">Sektor</h2>
              <span className="text-white/30 text-[9px] ml-auto">{sectors.reduce((s, x) => s + x.count, 0)}</span>
            </div>
            <div className="flex flex-wrap gap-0.5">
              {sectors.slice(0, 12).map((s) => {
                const maxCount = Math.max(...sectors.map((x) => x.count));
                const intensity = s.count / maxCount;
                return (
                  <span
                    key={s.name}
                    className="text-[8px] px-1 py-0.5 rounded font-mono"
                    style={{
                      background: `rgba(100,180,255,${0.08 + intensity * 0.15})`,
                      color: `rgba(180,220,255,${0.5 + intensity * 0.4})`,
                      border: `1px solid rgba(100,180,255,${0.1 + intensity * 0.1})`,
                    }}
                    title={`${s.name}: ${s.count}`}
                  >
                    {s.name.slice(0, 12)} <span className="text-white/40">{s.count}</span>
                  </span>
                );
              })}
            </div>
          </div>
        )}

        {/* Panel 3: Sinyal / Siklus / Bulan (bergantian) */}
        <div className="rounded-lg bg-black/10 border border-white/10 backdrop-blur-md p-2 flex-shrink-0 w-48 max-h-32 overflow-y-auto">
          <div className="flex items-center gap-1 mb-1.5">
            {(["sinyal", "siklus", "bulan"] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setRotateTab(tab)}
                className={`px-1.5 py-0.5 rounded text-[8px] font-medium transition-colors ${
                  rotateTab === tab ? "bg-white/15 text-white/90" : "text-white/30 hover:text-white/50"
                }`}
              >
                {tab === "sinyal" ? "Sinyal" : tab === "siklus" ? "Siklus" : "Bulan"}
              </button>
            ))}
          </div>

          {rotateTab === "sinyal" && (
            <div className="space-y-1">
              {signal ? (
                <>
                  <div className="flex items-center justify-between">
                    <span className="text-white/50 text-[10px]">Time Signal</span>
                    <span className={`text-xs font-mono font-bold flex items-center gap-1 ${
                      signalTone === "bearish" ? "text-red-400" : signalTone === "bullish" ? "text-emerald-400" : "text-white/70"
                    }`}>
                      {signalTone === "bearish" ? <TrendingDown className="w-3 h-3" />
                       : signalTone === "bullish" ? <TrendingUp className="w-3 h-3" /> : null}
                      {signal.time_signal.toFixed(3)}
                    </span>
                  </div>
                  <Bar label="Volatilitas" value={signal.volatility_signal} color="#FFD23F" />
                  <Bar label="Confidence" value={signal.confidence} color="#6CB4EE" />
                  {signal.confluence && signal.confluence.matched && (
                    <div className="rounded bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-1 mt-1">
                      <div className="flex items-center justify-between">
                        <span className="text-emerald-300/80 text-[9px]">Confluence</span>
                        <span className="text-emerald-300 text-[9px] font-mono">
                          Fib {(signal.confluence.ratio * 100).toFixed(1)}% @ {signal.confluence.fib_price.toFixed(0)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between mt-0.5">
                        <span className="text-white/40 text-[9px]">{signal.confluence.direction}</span>
                        <span className="text-white/40 text-[9px]">dist {signal.confluence.distance_pct.toFixed(2)}%</span>
                      </div>
                    </div>
                  )}
                </>
              ) : <p className="text-white/40 text-[10px]">memuat…</p>}
            </div>
          )}

          {rotateTab === "siklus" && (
            <div className="space-y-1">
              {astro?.active_cycles.slice(0, 3).map((c) => (
                <div key={c.cycle_type + c.start_at} className="rounded bg-white/5 border border-white/5 p-1.5">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-white/90 text-[10px] font-medium truncate">{c.title}</span>
                    <span className="text-[8px] px-1 rounded font-mono shrink-0"
                      style={{ color: IMPACT_COLOR[c.potential_impact] ?? "#888", background: `${IMPACT_COLOR[c.potential_impact] ?? "#888"}22` }}>
                      {c.potential_impact}
                    </span>
                  </div>
                  <div className="text-[8px] text-white/40 mt-0.5">
                    {new Date(c.start_at).toLocaleDateString("id-ID", { day: "2-digit", month: "short" })}
                  </div>
                </div>
              ))}
              {(!astro || astro.active_cycles.length === 0) && <p className="text-white/40 text-[10px]">Tidak ada siklus aktif.</p>}
            </div>
          )}

          {rotateTab === "bulan" && (
            <div className="space-y-1">
              {moonBody && (
                <>
                  <div className="text-white/80 text-xs">{moonBody.phase_name}</div>
                  <div className="text-white/50 text-[10px]">Iluminasi {moonBody.illumination_pct?.toFixed(1)}%</div>
                  <div className="text-white/40 text-[10px]">Zodiak: {moonBody.zodiac}</div>
                </>
              )}
              <div className="pt-1 border-t border-white/10">
                <div className="flex items-center gap-1 text-white/50 text-[10px]">
                  <Satellite className="w-3 h-3 text-sky-300" />
                  {sats.length} satelit · {sats.filter((s) => s.latest.length > 0).length} observasi
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Panel 4: Zodiak / Komoditas / Jam / IHSG (bergantian) */}
        <div className="rounded-lg bg-black/10 border border-white/10 backdrop-blur-md p-2 flex-shrink-0 w-48 max-h-32 overflow-y-auto">
          <div className="flex items-center gap-1 mb-1.5">
            {([
              ["zodiak", "Zodiak"],
              ["komoditas", "Komoditas"],
              ["jam", "Jam"],
              ["ihsg", "IHSG"],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setTopTab(key)}
                className={`px-1.5 py-0.5 rounded text-[8px] font-medium transition-colors ${
                  topTab === key ? "bg-white/15 text-white/90" : "text-white/30 hover:text-white/50"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {topTab === "zodiak" && (
            <div className="text-[10px] text-white/60">
              {astro?.bodies.filter(b => b.name !== "SUN" && b.name !== "MOON").slice(0, 5).map(b => (
                <div key={b.name} className="flex justify-between">
                  <span style={{ color: PLANET_COLORS[b.name] ?? "#888" }}>{b.name.slice(0, 3)}</span>
                  <span>{b.lon_deg.toFixed(1)}°{b.retrograde ? " ℞" : ""}</span>
                </div>
              ))}
              <div className="text-white/40 mt-1">{astro?.active_cycles.length ?? 0} siklus aktif</div>
            </div>
          )}

          {topTab === "komoditas" && (
            <div className="space-y-0.5">
              {commodities.map((c) => {
                const chg = c.change_pct;
                const chgColor = chg != null ? (chg > 0 ? "text-emerald-400" : chg < 0 ? "text-red-400" : "text-white/50") : "text-white/30";
                return (
                  <div key={c.ticker} className="flex items-center justify-between text-[10px]">
                    <span className="text-white/70">{c.name.slice(0, 8)}</span>
                    <span className={`font-mono ${chgColor}`}>
                      {chg != null ? `${chg > 0 ? "▲" : chg < 0 ? "▼" : "—"} ${chg > 0 ? "+" : ""}${chg.toFixed(1)}%` : ""}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {topTab === "jam" && <WorldClock exchanges={exchanges} />}

          {topTab === "ihsg" && <IhsgSparkline sparkline={ihsgSparkline} exchanges={exchanges} />}
        </div>

        {/* Panel 5: Fear & Greed (compact) */}
        {fearGreed && (
          <div className="rounded-lg bg-black/10 border border-white/10 backdrop-blur-md p-2 flex-shrink-0">
            <div className="flex items-center gap-1 mb-1">
              <Activity className="w-3 h-3 text-amber-300" />
              <span className="text-white/60 text-[9px] font-semibold uppercase">F&G</span>
            </div>
            <FearGreedGauge value={fearGreed.value} label={fearGreed.label} date={fearGreed.date} />
          </div>
        )}

        {/* Panel 6: Legenda */}
        <div className="rounded-lg bg-black/10 border border-white/10 backdrop-blur-md p-2 flex-shrink-0 flex flex-col justify-center gap-1 text-[8px] text-white/40">
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" /> Buka</span>
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> Baru tutup</span>
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-red-500" /> Tutup</span>
          <span className="flex items-center gap-1 text-amber-300">☀ Matahari</span>
          <span className="flex items-center gap-1 text-sky-300">→ Arc aliran</span>
        </div>
      </div>

      {/* ── Ticker strip berjalan (bottom, full width) ── */}
      <TickerStrip exchanges={exchanges} />

    </div>
  );
}

// ── MiniCosmos: tata surya ringkas di panel ───────────────────────────────────

function MiniCosmos({
  astro,
  paused,
}: {
  astro: AstronacciResponse | null;
  paused: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animRef = useRef<number>(0);
  const startTimeRef = useRef<number>(0);
  const astroRef = useRef(astro);
  astroRef.current = astro;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const SIZE = 180;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = SIZE * dpr;
    canvas.height = SIZE * dpr;
    canvas.style.width = `${SIZE}px`;
    canvas.style.height = `${SIZE}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    if (!startTimeRef.current) startTimeRef.current = performance.now();

    const draw = (now: number) => {
      const t = paused ? 0 : (now - startTimeRef.current) / 1000;
      const cx = SIZE / 2;
      const cy = SIZE / 2;
      const baseR = 8;
      const ringStep = 7;

      ctx.clearRect(0, 0, SIZE, SIZE);

      // Orbit rings
      ctx.strokeStyle = "rgba(120,140,200,0.1)";
      ctx.lineWidth = 0.5;
      for (let r = 1; r <= 9; r++) {
        ctx.beginPath();
        ctx.arc(cx, cy, baseR + r * ringStep, 0, Math.PI * 2);
        ctx.stroke();
      }

      // Sun
      const sunGrad = ctx.createRadialGradient(cx, cy, 2, cx, cy, 18);
      sunGrad.addColorStop(0, "rgba(255,235,120,1)");
      sunGrad.addColorStop(0.4, "rgba(255,180,40,0.6)");
      sunGrad.addColorStop(1, "rgba(255,120,0,0)");
      ctx.fillStyle = sunGrad;
      ctx.beginPath();
      ctx.arc(cx, cy, 18, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = PLANET_COLORS.SUN;
      ctx.beginPath();
      ctx.arc(cx, cy, PLANET_RADIUS.SUN, 0, Math.PI * 2);
      ctx.fill();

      // Planets
      const data = astroRef.current;
      if (data) {
        for (const b of data.bodies) {
          if (b.name === "SUN") continue;
          const ring = b.orbit_ring;
          if (ring === 0) continue;
          const baseAngle = (b.lon_deg - 90) * (Math.PI / 180);
          const drift = t * (ORBIT_SPEED[ring] ?? 0.05);
          const angle = baseAngle + drift;
          const r = baseR + ring * ringStep;
          const px = cx + Math.cos(angle) * r;
          const py = cy + Math.sin(angle) * r;

          // Glow
          const pr = PLANET_RADIUS[b.name] ?? 2.5;
          const g = ctx.createRadialGradient(px, py, 0.5, px, py, pr * 2);
          g.addColorStop(0, `${PLANET_COLORS[b.name] ?? "#888"}aa`);
          g.addColorStop(1, `${PLANET_COLORS[b.name] ?? "#888"}00`);
          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.arc(px, py, pr * 2, 0, Math.PI * 2);
          ctx.fill();
          // Body
          ctx.fillStyle = PLANET_COLORS[b.name] ?? "#888";
          ctx.beginPath();
          ctx.arc(px, py, pr, 0, Math.PI * 2);
          ctx.fill();
          // Retrograde marker
          if (b.retrograde) {
            ctx.strokeStyle = "#FF3B3B";
            ctx.lineWidth = 0.8;
            ctx.beginPath();
            ctx.arc(px, py, pr + 2, 0, Math.PI * 2);
            ctx.stroke();
          }
        }
      }

      animRef.current = requestAnimationFrame(draw);
    };

    animRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(animRef.current);
  }, [paused]);

  return <canvas ref={canvasRef} className="mx-auto" />;
}

// ── Bar component ─────────────────────────────────────────────────────────────
function Bar({ label, value, color }: { label: string; value: number; color: string }) {
  const pct = Math.max(0, Math.min(100, (value + 1) * 50));
  return (
    <div>
      <div className="flex justify-between text-[9px] text-white/50 mb-0.5">
        <span>{label}</span>
        <span className="font-mono">{value.toFixed(2)}</span>
      </div>
      <div className="h-1.5 w-full bg-white/10 rounded overflow-hidden">
        <div className="h-full rounded" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

// ── Fear & Greed Gauge component ─────────────────────────────────────────────
function FearGreedGauge({ value, label, date }: { value: number; label: string; date: string }) {
  const color =
    value < 25 ? "#ef4444" : value < 45 ? "#f97316" : value < 55 ? "#eab308" : value < 75 ? "#84cc16" : "#22c55e";
  const size = 70;
  const cx = size / 2;
  const cy = size * 0.75;
  const r = size * 0.4;
  const needleAngle = Math.PI - (value / 100) * Math.PI;
  const arcSegments = [
    { from: 0, to: 25, color: "#ef4444" },
    { from: 25, to: 45, color: "#f97316" },
    { from: 45, to: 55, color: "#eab308" },
    { from: 55, to: 75, color: "#84cc16" },
    { from: 75, to: 100, color: "#22c55e" },
  ];
  return (
    <div>
      <svg width={size} height={size * 0.65} className="block">
        {arcSegments.map((seg) => {
          const a1 = Math.PI - (seg.from / 100) * Math.PI;
          const a2 = Math.PI - (seg.to / 100) * Math.PI;
          const x1 = cx + Math.cos(a1) * r;
          const y1 = cy - Math.sin(a1) * r;
          const x2 = cx + Math.cos(a2) * r;
          const y2 = cy - Math.sin(a2) * r;
          return (
            <path
              key={seg.from}
              d={`M ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2}`}
              fill="none"
              stroke={seg.color}
              strokeWidth={4}
              strokeLinecap="round"
              opacity={0.7}
            />
          );
        })}
        <line
          x1={cx}
          y1={cy}
          x2={cx + Math.cos(needleAngle) * r * 0.85}
          y2={cy - Math.sin(needleAngle) * r * 0.85}
          stroke={color}
          strokeWidth={2}
          strokeLinecap="round"
        />
        <circle cx={cx} cy={cy} r={2.5} fill={color} />
      </svg>
      <div className="text-center -mt-1">
        <div className="text-sm font-bold font-mono" style={{ color }}>
          {value.toFixed(0)}
        </div>
        <div className="text-white/50 text-[7px]">{label}</div>
      </div>
    </div>
  );
}

// ── WorldClock: jam real-time pusat finansial ─────────────────────────────────
function WorldClock({ exchanges }: { exchanges: Exchange[] }) {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const centers = ["XIDX", "XTSE", "XHKG", "XFRA", "XLON", "XNYS"];
  const clocks = centers
    .map((mic) => exchanges.find((e) => e.mic === mic))
    .filter((e): e is Exchange => e !== undefined);

  return (
    <div className="space-y-0.5">
      {clocks.map((ex) => {
        const isOpen = ex.market_status.is_open;
        let timeStr = "—";
        try {
          timeStr = now.toLocaleTimeString("en-GB", {
            timeZone: ex.timezone,
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          });
        } catch {}
        return (
          <div key={ex.mic} className="flex items-center justify-between text-[10px]">
            <div className="flex items-center gap-1">
              <span className={`w-1 h-1 rounded-full ${isOpen ? "bg-emerald-400 animate-pulse" : "bg-slate-500"}`} />
              <span className="text-white/70">{ex.city.slice(0, 8)}</span>
            </div>
            <span className={`font-mono font-bold ${isOpen ? "text-emerald-400" : "text-white/40"}`}>
              {timeStr}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── IhsgSparkline: mini chart IHSG 30 hari ───────────────────────────────────
function IhsgSparkline({ sparkline, exchanges }: { sparkline: number[]; exchanges: Exchange[] }) {
  if (sparkline.length < 2) return <p className="text-white/40 text-[10px]">data tidak tersedia</p>;

  const w = 160;
  const h = 50;
  const padding = 4;
  const min = Math.min(...sparkline);
  const max = Math.max(...sparkline);
  const range = max - min || 1;
  const step = (w - padding * 2) / (sparkline.length - 1);

  const points = sparkline.map((v, i) => {
    const x = padding + i * step;
    const y = h - padding - ((v - min) / range) * (h - padding * 2);
    return `${x},${y}`;
  });

  const pathD = `M ${points.join(" L ")}`;
  const areaD = `${pathD} L ${padding + (sparkline.length - 1) * step},${h - padding} L ${padding},${h - padding} Z`;
  const lastVal = sparkline[sparkline.length - 1];
  const firstVal = sparkline[0];
  const changePct = ((lastVal - firstVal) / firstVal) * 100;
  const isUp = changePct >= 0;
  const lineColor = isUp ? "#4ade80" : "#f87171";

  const ihsg = exchanges.find((e) => e.mic === "XIDX");
  const idxChange = ihsg?.index?.change_pct;

  return (
    <div>
      <div className="flex items-center justify-between mb-0.5">
        <span className="text-[10px] text-white/70 font-medium">IHSG</span>
        <span className="text-xs font-mono font-bold text-white/90">
          {lastVal.toLocaleString("en-US", { maximumFractionDigits: 0 })}
        </span>
      </div>
      <svg width={w} height={h} className="block">
        <defs>
          <linearGradient id="ihsgGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity={0.3} />
            <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
          </linearGradient>
        </defs>
        <path d={areaD} fill="url(#ihsgGrad)" />
        <path d={pathD} fill="none" stroke={lineColor} strokeWidth={1} />
        <circle
          cx={padding + (sparkline.length - 1) * step}
          cy={h - padding - ((lastVal - min) / range) * (h - padding * 2)}
          r={2}
          fill={lineColor}
        />
      </svg>
      <div className="flex items-center justify-between text-[8px] mt-0.5">
        <span className="text-white/40">30d</span>
        <span className={isUp ? "text-emerald-400" : "text-red-400"}>
          {isUp ? "▲" : "▼"} {changePct > 0 ? "+" : ""}{changePct.toFixed(2)}%
          {idxChange != null && ` (${idxChange > 0 ? "+" : ""}${idxChange.toFixed(2)}%)`}
        </span>
      </div>
    </div>
  );
}

// ── Ticker strip component ───────────────────────────────────────────────────
function TickerStrip({ exchanges }: { exchanges: Exchange[] }) {
  const pairs = exchanges.map((ex) => {
    const idx = ex.index;
    const chg = idx?.change_pct;
    return { city: ex.city, close: idx?.close ?? 0, chg };
  });

  return (
    <div className="absolute bottom-0 left-0 right-0 z-10 overflow-hidden bg-black/10 border-t border-white/10 backdrop-blur-md">
      <div className="flex items-center gap-8 py-1.5 px-2 animate-ticker whitespace-nowrap text-[11px] font-mono">
        {[...pairs, ...pairs].map((p, i) => {
          const color = p.chg == null ? "text-white/50" : p.chg > 0 ? "text-emerald-400" : p.chg < 0 ? "text-red-400" : "text-white/50";
          const arrow = p.chg == null ? "" : p.chg > 0 ? "▲" : p.chg < 0 ? "▼" : "—";
          return (
            <span key={i} className={`flex items-center gap-1 ${color}`}>
              <span className="text-white/70 font-medium">{p.city}</span>
              <span className="text-white/60">{p.close.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
              <span>{arrow} {p.chg != null ? `${p.chg > 0 ? "+" : ""}${p.chg.toFixed(2)}%` : "—"}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

