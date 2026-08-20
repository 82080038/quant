"use client";

/**
 * Ticker Tape — horizontal running text of global market prices.
 *
 * Consolidates secondary market data (global indices, forex, commodities,
 * macro rates) into a single GPU-accelerated scrolling strip. Replaces
 * the need for separate exchange status cards and market clock widgets
 * on the dashboard.
 *
 * Performance:
 *   - CSS `will-change: transform` for GPU compositing
 *   - `requestAnimationFrame` drives the scroll, pauses on hover
 *   - Content duplicated x2 for seamless infinite loop
 *   - No React re-renders during scroll — pure transform animation
 */

import { useEffect, useRef, useState, useCallback } from "react";

interface TickerItem {
  label: string;
  value: string;
  change: number | null;
  unit?: string;
}

export function TickerTape() {
  const [items, setItems] = useState<TickerItem[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number>(0);
  const offsetRef = useRef<number>(0);
  const hoveredRef = useRef<boolean>(false);
  const contentWidthRef = useRef<number>(0);

  const loadData = useCallback(async () => {
    try {
      const [sessionsRes, macroRes, ihsgRes] = await Promise.all([
        fetch("/api/scheduler/sessions-with-indices"),
        fetch("/api/cosmos/kurs"),
        fetch("/api/prices/ihsg"),
      ]);

      const tickerItems: TickerItem[] = [];

      // IHSG
      if (ihsgRes.ok) {
        try {
          const ihsg = await ihsgRes.json();
          if (ihsg.price != null) {
            tickerItems.push({
              label: "IHSG",
              value: ihsg.price.toLocaleString("en-US", { maximumFractionDigits: 2 }),
              change: ihsg.pct_change ?? null,
            });
          }
        } catch {}
      }

      // Global indices from sessions
      if (sessionsRes.ok) {
        try {
          const data = await sessionsRes.json();
          for (const session of data.sessions ?? []) {
            for (const idx of session.indices ?? []) {
              if (idx.price != null) {
                tickerItems.push({
                  label: idx.symbol || idx.name,
                  value: idx.price.toLocaleString("en-US", { maximumFractionDigits: 2 }),
                  change: idx.change_pct ?? null,
                });
              }
            }
          }
        } catch {}
      }

      // USD/IDR
      if (macroRes.ok) {
        try {
          const kurs = await macroRes.json();
          if (kurs.rate != null) {
            tickerItems.push({
              label: "USD/IDR",
              value: kurs.rate.toLocaleString("en-US", { maximumFractionDigits: 0 }),
              change: null,
              unit: "IDR",
            });
          }
        } catch {}
      }

      if (tickerItems.length > 0) setItems(tickerItems);
    } catch {
      // keep previous
    }
  }, []);

  useEffect(() => {
    loadData();
    const id = setInterval(loadData, 30_000);
    return () => clearInterval(id);
  }, [loadData]);

  // Auto-scroll animation
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || items.length === 0) return;

    const measure = () => {
      const firstChild = el.firstElementChild as HTMLElement | null;
      if (firstChild) contentWidthRef.current = firstChild.scrollWidth;
    };

    measure();
    const measureTimer = setInterval(measure, 5000);

    const animate = () => {
      rafRef.current = requestAnimationFrame(animate);
      if (hoveredRef.current) return;
      const w = contentWidthRef.current;
      if (w <= 0) return;
      offsetRef.current -= 0.4; // px per frame ~24fps at 60fps
      if (offsetRef.current <= -w) offsetRef.current = 0;
      el.style.transform = `translateX(${offsetRef.current}px)`;
    };

    rafRef.current = requestAnimationFrame(animate);

    const onEnter = () => { hoveredRef.current = true; };
    const onLeave = () => { hoveredRef.current = false; };
    el.addEventListener("mouseenter", onEnter);
    el.addEventListener("mouseleave", onLeave);

    return () => {
      cancelAnimationFrame(rafRef.current);
      clearInterval(measureTimer);
      el.removeEventListener("mouseenter", onEnter);
      el.removeEventListener("mouseleave", onLeave);
    };
  }, [items]);

  if (items.length === 0) return null;

  const renderItem = (item: TickerItem, key: string) => {
    const chgColor = item.change == null
      ? "text-muted-foreground"
      : item.change > 0
        ? "text-emerald-400"
        : item.change < 0
          ? "text-red-400"
          : "text-muted-foreground";
    const arrow = item.change == null ? "" : item.change > 0 ? "▲" : item.change < 0 ? "▼" : "";
    return (
      <span key={key} className="inline-flex items-center gap-1.5 px-3 shrink-0">
        <span className="text-muted-foreground font-medium text-xs">{item.label}</span>
        <span className="font-mono text-xs text-foreground">{item.value}</span>
        {item.change != null && (
          <span className={`font-mono text-xs ${chgColor}`}>
            {arrow} {Math.abs(item.change).toFixed(2)}%
          </span>
        )}
        <span className="text-border">|</span>
      </span>
    );
  };

  return (
    <div
      className="relative h-7 overflow-hidden border-b border-border/60 bg-card/40 backdrop-blur-sm shrink-0"
      style={{ contain: "strict" }}
    >
      <div
        ref={scrollRef}
        className="absolute inset-0 flex items-center whitespace-nowrap"
        style={{ willChange: "transform", transform: "translateX(0px)" }}
      >
        {items.map((item) => renderItem(item, `a-${item.label}`))}
        {items.map((item) => renderItem(item, `b-${item.label}`))}
      </div>
    </div>
  );
}
