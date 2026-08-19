"use client";

/**
 * Multi-Asset Class Selector — tabbed interface for switching between
 * asset classes (Equity, Forex, Commodity, Crypto, Index, Bond, Macro).
 *
 * Fetches from /api/asset-classes and /api/instruments/by-asset-class.
 * Designed for smooth rendering on Epson HDMI-0 1920x1080 display.
 */

import { useEffect, useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  LineChart,
  Coins,
  DollarSign,
  TrendingUp,
  BarChart3,
  Landmark,
  Gauge,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface AssetClassInfo {
  code: string;
  name: string;
  market_hours_24h: boolean;
  holiday_calendar_source: string;
  default_currency: string;
  default_data_source: string;
  default_fetch_frequency: string;
  is_tradeable: boolean;
  sort_order: number;
}

interface AssetClassCount {
  asset_class: string;
  name: string;
  total: number;
  active: number;
  ok: number;
  stale: number;
  never_fetched: number;
  failed: number;
}

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  equity: LineChart,
  index: BarChart3,
  forex: DollarSign,
  commodity: Coins,
  crypto: TrendingUp,
  bond: Landmark,
  macro_rate: Gauge,
};

const COLORS: Record<string, string> = {
  equity: "text-blue-400 border-blue-500/30",
  index: "text-purple-400 border-purple-500/30",
  forex: "text-green-400 border-green-500/30",
  commodity: "text-yellow-400 border-yellow-500/30",
  crypto: "text-orange-400 border-orange-500/30",
  bond: "text-cyan-400 border-cyan-500/30",
  macro_rate: "text-slate-400 border-slate-500/30",
};

export function MultiAssetSelector({
  onSelect,
  selected,
}: {
  onSelect?: (assetClass: string) => void;
  selected?: string;
}) {
  const [classes, setClasses] = useState<AssetClassInfo[]>([]);
  const [counts, setCounts] = useState<Record<string, AssetClassCount>>({});
  const [loading, setLoading] = useState(true);
  const [internalSelected, setInternalSelected] = useState("equity");

  const active = selected ?? internalSelected;

  const fetchData = useCallback(async () => {
    try {
      const [clsRes, cntRes] = await Promise.all([
        fetch("/api/asset-classes"),
        fetch("/api/instruments/by-asset-class"),
      ]);
      if (clsRes.ok) {
        const data = await clsRes.json();
        if (Array.isArray(data)) setClasses(data);
      }
      if (cntRes.ok) {
        const data = await cntRes.json();
        if (Array.isArray(data)) {
          const map: Record<string, AssetClassCount> = {};
          for (const item of data) {
            map[item.asset_class] = item;
          }
          setCounts(map);
        }
      }
    } catch {
      // silent fail — non-critical widget
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleSelect = (code: string) => {
    setInternalSelected(code);
    onSelect?.(code);
  };

  if (loading && classes.length === 0) {
    return (
      <Card className="border-slate-800 bg-slate-900/50">
        <CardContent className="p-4">
          <div className="animate-pulse text-sm text-slate-500">
            Loading asset classes...
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-slate-800 bg-slate-900/50">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-slate-300">
          Multi-Asset Classes
        </CardTitle>
      </CardHeader>
      <CardContent className="p-3">
        <div className="flex flex-wrap gap-2">
          {classes.map((cls) => {
            const Icon = ICONS[cls.code] ?? LineChart;
            const cnt = counts[cls.code];
            const isActive = active === cls.code;
            const colorClass = COLORS[cls.code] ?? "text-slate-400 border-slate-500/30";

            return (
              <button
                key={cls.code}
                onClick={() => handleSelect(cls.code)}
                className={cn(
                  "flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs transition-all",
                  colorClass,
                  isActive
                    ? "bg-slate-800 ring-1 ring-slate-600"
                    : "hover:bg-slate-800/50"
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                <span className="font-medium">{cls.name.split(" / ")[0]}</span>
                {cnt && (
                  <Badge
                    variant="outline"
                    className="ml-1 border-slate-700 px-1.5 text-[10px] text-slate-400"
                  >
                    {cnt.active}
                  </Badge>
                )}
                {cls.market_hours_24h && (
                  <span className="text-[10px] text-green-500">24h</span>
                )}
              </button>
            );
          })}
        </div>

        {/* Detail bar for selected asset class */}
        {classes.find((c) => c.code === active) && (
          <div className="mt-3 flex flex-wrap gap-3 border-t border-slate-800 pt-3 text-[11px] text-slate-400">
            <span>
              Source:{" "}
              <span className="text-slate-300">
                {classes.find((c) => c.code === active)?.default_data_source}
              </span>
            </span>
            <span>
              Freq:{" "}
              <span className="text-slate-300">
                {classes.find((c) => c.code === active)?.default_fetch_frequency}
              </span>
            </span>
            <span>
              Currency:{" "}
              <span className="text-slate-300">
                {classes.find((c) => c.code === active)?.default_currency}
              </span>
            </span>
            <span>
              Tradeable:{" "}
              <span
                className={
                  classes.find((c) => c.code === active)?.is_tradeable
                    ? "text-green-400"
                    : "text-red-400"
                }
              >
                {classes.find((c) => c.code === active)?.is_tradeable ? "Yes" : "No"}
              </span>
            </span>
            {counts[active] && (
              <>
                <span>
                  OK: <span className="text-green-400">{counts[active].ok}</span>
                </span>
                <span>
                  Stale:{" "}
                  <span className="text-yellow-400">{counts[active].stale}</span>
                </span>
                <span>
                  Failed:{" "}
                  <span className="text-red-400">{counts[active].failed}</span>
                </span>
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
