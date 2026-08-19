"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";

interface ExchangeStatus {
  name: string;
  mic: string;
  city: string;
  tz: string;
  open: string; // "HH:00"
  close: string; // "HH:50"
  status: "active" | "closed" | "pre-open" | "closing" | "after-hours";
  localTime: string;
}

interface MarketContextValue {
  now: Date | null;
  utcTime: string;
  wibTime: string;
  mode: "simulasi" | "real";
  setMode: (m: "simulasi" | "real") => void;
  simulatedDate: Date | null;
  setSimulatedDate: (d: Date | null) => void;
  exchanges: ExchangeStatus[];
  activeExchange: ExchangeStatus | null;
  nextOpenExchange: ExchangeStatus | null;
  lastClosedExchange: ExchangeStatus | null;
  idxSession: { label: string; color: string };
}

const MarketContext = createContext<MarketContextValue | null>(null);

const EXCHANGES = [
  { name: "IDX", mic: "XIDX", city: "Jakarta", tz: "Asia/Jakarta", open: "09:00", close: "15:50" },
  { name: "NYSE", mic: "XNYS", city: "New York", tz: "America/New_York", open: "09:30", close: "16:00" },
  { name: "NASDAQ", mic: "XNAS", city: "New York", tz: "America/New_York", open: "09:30", close: "16:00" },
  { name: "LSE", mic: "XLON", city: "London", tz: "Europe/London", open: "08:00", close: "16:30" },
  { name: "TSE", mic: "XTKS", city: "Tokyo", tz: "Asia/Tokyo", open: "09:00", close: "15:00" },
  { name: "HKEX", mic: "XHKG", city: "Hong Kong", tz: "Asia/Hong_Kong", open: "09:30", close: "16:00" },
  { name: "SGX", mic: "XSES", city: "Singapore", tz: "Asia/Singapore", open: "09:00", close: "17:00" },
  { name: "ASX", mic: "XASX", city: "Sydney", tz: "Australia/Sydney", open: "10:00", close: "16:00" },
];

function getExchangeStatus(ex: typeof EXCHANGES[0], now: Date): ExchangeStatus {
  const localStr = now.toLocaleString("en-GB", {
    timeZone: ex.tz,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const localTime = localStr;

  // Parse local hour/minute in exchange timezone
  const parts = now.toLocaleString("en-GB", {
    timeZone: ex.tz,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const [h, m] = parts.split(":").map(Number);
  const totalMin = h * 60 + m;
  const [oh, om] = ex.open.split(":").map(Number);
  const [ch, cm] = ex.close.split(":").map(Number);
  const openMin = oh * 60 + om;
  const closeMin = ch * 60 + cm;

  // Check weekend
  const dowStr = now.toLocaleString("en-GB", { timeZone: ex.tz, weekday: "short" });
  const isWeekend = dowStr === "Sat" || dowStr === "Sun";

  let status: ExchangeStatus["status"] = "closed";
  if (!isWeekend) {
    if (totalMin >= openMin - 15 && totalMin < openMin) {
      status = "pre-open";
    } else if (totalMin >= openMin && totalMin < closeMin - 10) {
      status = "active";
    } else if (totalMin >= closeMin - 10 && totalMin < closeMin) {
      status = "closing";
    } else if (totalMin >= closeMin && totalMin < closeMin + 60) {
      status = "after-hours";
    }
  }

  return {
    ...ex,
    status,
    localTime,
  };
}

function getIdxSession(exchanges: ExchangeStatus[]): { label: string; color: string } {
  const idx = exchanges.find(e => e.name === "IDX");
  if (!idx) return { label: "—", color: "text-muted-foreground" };
  switch (idx.status) {
    case "active": return { label: "Regular (09:00-15:50 WIB)", color: "text-green-500" };
    case "pre-open": return { label: "Pre-Open", color: "text-yellow-500" };
    case "closing": return { label: "Closing Auction", color: "text-yellow-500" };
    case "after-hours": return { label: "After-Hours", color: "text-blue-500" };
    default: return { label: "Tutup", color: "text-muted-foreground" };
  }
}

export function MarketProvider({ children }: { children: ReactNode }) {
  const [now, setNow] = useState<Date | null>(null);
  const [mode, setMode] = useState<"simulasi" | "real">("real");
  const [simulatedDate, setSimulatedDate] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const effectiveDate = mode === "simulasi" && simulatedDate ? simulatedDate : now;

  const exchanges = effectiveDate
    ? EXCHANGES.map(ex => getExchangeStatus(ex, effectiveDate))
    : [];

  const activeExchange = exchanges.find(e => e.status === "active") || null;
  const nextOpenExchange = exchanges.find(e => e.status === "pre-open") || null;
  const lastClosedExchange = [...exchanges].reverse().find(e => e.status === "after-hours" || e.status === "closed") || null;

  const utcTime = effectiveDate
    ? effectiveDate.toLocaleString("en-GB", {
        timeZone: "UTC",
        weekday: "short", day: "numeric", month: "short", year: "numeric",
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
      }) + " UTC"
    : "Memuat...";

  const wibTime = effectiveDate
    ? effectiveDate.toLocaleString("id-ID", {
        timeZone: "Asia/Jakarta",
        weekday: "short", day: "numeric", month: "short", year: "numeric",
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
      }) + " WIB"
    : "Memuat...";

  const value: MarketContextValue = {
    now,
    utcTime,
    wibTime,
    mode,
    setMode,
    simulatedDate,
    setSimulatedDate,
    exchanges,
    activeExchange,
    nextOpenExchange,
    lastClosedExchange,
    idxSession: getIdxSession(exchanges),
  };

  return <MarketContext.Provider value={value}>{children}</MarketContext.Provider>;
}

export function useMarket() {
  const ctx = useContext(MarketContext);
  if (!ctx) throw new Error("useMarket must be used within MarketProvider");
  return ctx;
}
