"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  TrendingUp,
  Wallet,
  FlaskConical,
  Search,
  Settings,
  FileText,
  Database,
  BellRing,
  Orbit,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const navSections: NavSection[] = [
  {
    title: "Analisis",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/signals", label: "Sinyal", icon: BellRing },
      { href: "/screener", label: "Screener", icon: Search },
      { href: "/stock", label: "Saham", icon: TrendingUp },
    ],
  },
  {
    title: "Trading",
    items: [
      { href: "/portfolio", label: "Portofolio", icon: Wallet },
      { href: "/backtest", label: "Backtest", icon: FlaskConical },
    ],
  },
  {
    title: "Sistem",
    items: [
      { href: "/reports", label: "Laporan", icon: FileText },
      { href: "/cosmos", label: "Kosmos", icon: Orbit },
      { href: "/data", label: "Data & Sumber", icon: Database },
      { href: "/scheduler", label: "Scheduler", icon: Clock },
      { href: "/settings", label: "Pengaturan", icon: Settings },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-64 border-r border-border bg-card flex flex-col">
      <div className="p-6 border-b border-border">
        <h1 className="text-xl font-bold text-primary">Quant</h1>
        <p className="text-xs text-muted-foreground mt-1">
          Gigantic AI Trading System
        </p>
      </div>
      <nav className="flex-1 p-4 space-y-4 overflow-y-auto">
        {navSections.map((section) => (
          <div key={section.title}>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 px-3 mb-1">
              {section.title}
            </p>
            <div className="space-y-1">
              {section.items.map((item) => {
                const Icon = item.icon;
                const active = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
                      active
                        ? "bg-primary/10 text-primary font-medium"
                        : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                    )}
                  >
                    <Icon className="w-4 h-4" />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
      <div className="p-4 border-t border-border">
        <p className="text-xs text-muted-foreground">
          v0.1.0 · Gigantic AI · PIT-Native
        </p>
      </div>
    </aside>
  );
}
