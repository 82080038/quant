"use client";

/**
 * Celestial Fibonacci Chart — candlestick + Fibonacci retracement + time zones.
 *
 * Renders a Canvas 2D candlestick chart with:
 *   - Fibonacci Price Retracement levels (0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100%)
 *     drawn as horizontal support/resistance lines on the Y-axis.
 *   - Fibonacci Time Zones (1, 2, 3, 5, 8, 13, 21, 34, 55, 89...) drawn as
 *     vertical lines on the X-axis, synced with astronomical cycle durations.
 *   - Celestial theme: dark space background, star particles, orbital rings.
 *
 * Performance:
 *   - Canvas 2D with `will-change: transform` for GPU acceleration.
 *   - requestAnimationFrame throttling for smooth 60 FPS rendering.
 *   - Only redraws when data changes or on interaction.
 *
 * Data source: /api/prices/candles?ticker=^JKSE&limit=120 (REST initial),
 *              WS prices.tick for live updates.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Activity } from "lucide-react";
import { Widget } from "@/components/widget";
import { useWsLatest } from "@/lib/ws-client";
import { cn } from "@/lib/utils";

const FIB_LEVELS = [
  { level: 0, pct: "0%", color: "#64748b" },
  { level: 0.236, pct: "23.6%", color: "#f59e0b" },
  { level: 0.382, pct: "38.2%", color: "#3b82f6" },
  { level: 0.5, pct: "50%", color: "#a855f7" },
  { level: 0.618, pct: "61.8%", color: "#ec4899" },
  { level: 0.786, pct: "78.6%", color: "#06b6d4" },
  { level: 1.0, pct: "100%", color: "#64748b" },
];

const FIB_TIME_ZONES = [1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144];

const ASTRO_CYCLES = [
  { name: "Moon", days: 29.53, color: "rgba(200,200,255,0.15)" },
  { name: "Mercury", days: 88, color: "rgba(180,180,200,0.1)" },
  { name: "Venus", days: 225, color: "rgba(255,200,150,0.1)" },
  { name: "Earth", days: 365.25, color: "rgba(100,200,255,0.1)" },
];

interface Candle {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface CelestialFibonacciChartProps {
  ticker?: string;
  className?: string;
}

function generateStars(count: number, w: number, h: number) {
  const stars: { x: number; y: number; r: number; o: number; tw: number }[] = [];
  for (let i = 0; i < count; i++) {
    stars.push({
      x: Math.random() * w,
      y: Math.random() * h,
      r: Math.random() * 1.2 + 0.3,
      o: Math.random() * 0.5 + 0.2,
      tw: Math.random() * Math.PI * 2,
    });
  }
  return stars;
}

function drawChart(
  ctx: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  candles: Candle[],
  livePrice: number | null,
  animationTime: number,
) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.width / dpr;
  const h = canvas.height / dpr;

  ctx.fillStyle = "#0a0e1a";
  ctx.fillRect(0, 0, w, h);

  const stars = generateStars(40, w, h);
  for (const s of stars) {
    const twinkle = 0.7 + 0.3 * Math.sin(animationTime * 0.001 + s.tw);
    ctx.fillStyle = `rgba(255,255,255,${s.o * twinkle})`;
    ctx.beginPath();
    ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
    ctx.fill();
  }

  if (candles.length < 2) {
    ctx.fillStyle = "#64748b";
    ctx.font = "11px monospace";
    ctx.textAlign = "center";
    ctx.fillText("Menunggu data candlestick...", w / 2, h / 2);
    return;
  }

  const padLeft = 10;
  const padRight = 68;
  const padTop = 12;
  const padBottom = 22;
  const chartW = w - padLeft - padRight;
  const chartH = h - padTop - padBottom;

  const allHighs = candles.map((c) => c.high);
  const allLows = candles.map((c) => c.low);
  if (livePrice != null) {
    allHighs.push(livePrice);
    allLows.push(livePrice);
  }
  const maxPrice = Math.max(...allHighs);
  const minPrice = Math.min(...allLows);
  const priceRange = maxPrice - minPrice || 1;
  const chartMax = maxPrice + priceRange * 0.05;
  const chartMin = minPrice - priceRange * 0.05;

  const priceToY = (p: number) =>
    padTop + ((chartMax - p) / (chartMax - chartMin)) * chartH;
  const indexToX = (i: number) =>
    padLeft + (i / (candles.length - 1)) * chartW;

  ctx.strokeStyle = "rgba(100,150,255,0.06)";
  ctx.lineWidth = 0.5;
  for (let r = 0.2; r < 1.0; r += 0.2) {
    const arcRadius = Math.max(0, chartW * r * 0.5);
    if (arcRadius < 1) continue;
    ctx.beginPath();
    ctx.arc(padLeft + chartW / 2, padTop + chartH / 2, arcRadius, 0, Math.PI * 2);
    ctx.stroke();
  }

  for (const cycle of ASTRO_CYCLES) {
    const cyclePixels = (cycle.days / candles.length) * chartW;
    if (cyclePixels < 5 || cyclePixels > chartW) continue;
    ctx.strokeStyle = cycle.color;
    ctx.lineWidth = 0.5;
    for (let x = padLeft; x < padLeft + chartW; x += cyclePixels) {
      ctx.beginPath();
      ctx.moveTo(x, padTop);
      ctx.lineTo(x, padTop + chartH);
      ctx.stroke();
    }
  }

  ctx.font = "10px monospace";
  ctx.textAlign = "center";
  for (const zone of FIB_TIME_ZONES) {
    if (zone >= candles.length) break;
    const x = indexToX(zone - 1);
    ctx.strokeStyle = zone === 1 || zone === 2 ? "rgba(168,85,247,0.2)" : "rgba(168,85,247,0.1)";
    ctx.lineWidth = zone === 1 || zone === 2 ? 1 : 0.5;
    ctx.setLineDash(zone === 1 ? [] : [3, 3]);
    ctx.beginPath();
    ctx.moveTo(x, padTop);
    ctx.lineTo(x, padTop + chartH);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "rgba(168,85,247,0.6)";
    ctx.fillText(String(zone), x, padTop + chartH + 12);
  }

  const fibHigh = maxPrice;
  const fibLow = minPrice;
  const fibRange = fibHigh - fibLow;

  ctx.font = "11px monospace";
  ctx.textAlign = "left";
  for (const fib of FIB_LEVELS) {
    const price = fibHigh - fibRange * fib.level;
    const y = priceToY(price);

    ctx.strokeStyle = fib.color;
    ctx.lineWidth = fib.level === 0.5 ? 1 : 0.5;
    ctx.setLineDash(fib.level === 0 || fib.level === 1 ? [] : [4, 4]);
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(padLeft + chartW, y);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = fib.color;
    ctx.fillText(`${fib.pct} ${price.toFixed(2)}`, padLeft + chartW + 4, y + 4);
  }

  const candleSpacing = chartW / candles.length;
  const candleWidth = Math.max(1.5, Math.min(8, candleSpacing * 0.65));

  for (let i = 0; i < candles.length; i++) {
    const c = candles[i];
    const x = indexToX(i);
    const isBull = c.close >= c.open;
    const color = isBull ? "#22c55e" : "#ef4444";

    ctx.strokeStyle = color;
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    ctx.moveTo(x, priceToY(c.high));
    ctx.lineTo(x, priceToY(c.low));
    ctx.stroke();

    const yOpen = priceToY(c.open);
    const yClose = priceToY(c.close);
    const bodyTop = Math.min(yOpen, yClose);
    const bodyH = Math.max(1, Math.abs(yClose - yOpen));
    ctx.fillStyle = color;
    ctx.fillRect(x - candleWidth / 2, bodyTop, candleWidth, bodyH);
  }

  if (livePrice != null) {
    const y = priceToY(livePrice);
    ctx.strokeStyle = "rgba(34,197,94,0.6)";
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 2]);
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(padLeft + chartW, y);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = "#22c55e";
    ctx.font = "11px monospace";
    ctx.textAlign = "left";
    ctx.fillText(`> ${livePrice.toFixed(2)}`, padLeft + chartW + 4, y + 4);
  }

  const lastCandle = candles[candles.length - 1];
  const displayPrice = livePrice ?? lastCandle.close;
  ctx.fillStyle = "#e2e8f0";
  ctx.font = "bold 13px monospace";
  ctx.textAlign = "left";
  ctx.fillText(displayPrice.toFixed(2), padLeft + 4, padTop + 14);
}

export function CelestialFibonacciChart({
  ticker = "^JKSE",
  className,
}: CelestialFibonacciChartProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationRef = useRef<number>(0);
  const candlesRef = useRef<Candle[]>([]);
  const livePriceRef = useRef<number | null>(null);
  const [candleCount, setCandleCount] = useState(0);
  const [loading, setLoading] = useState(true);

  const liveMsg = useWsLatest("prices.tick");

  const loadCandles = useCallback(async () => {
    try {
      const res = await fetch(`/api/prices/candles?ticker=${encodeURIComponent(ticker)}&limit=120`);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0) {
          candlesRef.current = data;
          setCandleCount(data.length);
        }
      }
    } catch {
      // keep previous
    }
    setLoading(false);
  }, [ticker]);

  useEffect(() => {
    loadCandles();
    const id = setInterval(loadCandles, 60_000);
    return () => clearInterval(id);
  }, [loadCandles]);

  useEffect(() => {
    if (liveMsg?.ch === "prices.tick" && liveMsg?.t === ticker && typeof liveMsg?.p === "number") {
      livePriceRef.current = liveMsg.p;
    }
  }, [liveMsg, ticker]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let lastDraw = 0;
    const minFrameTime = 1000 / 60;

    const render = (time: number) => {
      animationRef.current = requestAnimationFrame(render);
      if (time - lastDraw < minFrameTime) return;
      lastDraw = time;

      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      if (canvas.width !== rect.width * dpr || canvas.height !== rect.height * dpr) {
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.scale(dpr, dpr);
      }

      drawChart(ctx, canvas, candlesRef.current, livePriceRef.current, time);
    };

    animationRef.current = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animationRef.current);
  }, []);

  return (
    <Widget
      title="Celestial Fibonacci"
      icon={<Activity className="w-3.5 h-3.5" />}
      accent="text-purple-400"
      className={cn(className)}
      right={
        <span className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
          <span className="font-mono text-purple-300">{ticker}</span>
          <span className="text-[8px]">&middot;</span>
          <span>{candleCount} candles</span>
        </span>
      }
      bodyClassName="!p-0"
    >
      <div
        className="relative w-full h-full min-h-[280px]"
        style={{ willChange: "transform" }}
      >
        <canvas
          ref={canvasRef}
          className="absolute inset-0 w-full h-full"
          style={{ willChange: "transform" }}
        />
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
            <span className="animate-pulse">Memuat chart...</span>
          </div>
        )}
      </div>
    </Widget>
  );
}
