"use client";

/**
 * Widget wrapper for the dashboard grid.
 *
 * Provides a consistent chrome (header + scrollable body) with panel-level
 * scroll only — the page itself never scrolls. Optional `accent` colors the
 * header border; `right` renders a small control/status slot in the header.
 */

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface WidgetProps {
  title: string;
  icon?: ReactNode;
  accent?: string;          // tailwind text color class for the icon/title
  right?: ReactNode;        // header right slot (status badge, action)
  className?: string;       // extra classes on the widget root
  bodyClassName?: string;   // extra classes on the body
  children: ReactNode;
}

export function Widget({
  title,
  icon,
  accent,
  right,
  className,
  bodyClassName,
  children,
}: WidgetProps) {
  return (
    <section className={cn("widget", className)}>
      <div className="widget-head">
        <div className="flex items-center gap-1.5 min-w-0">
          {icon && <span className={cn("shrink-0", accent)}>{icon}</span>}
          <span className="truncate">{title}</span>
        </div>
        {right && <div className="shrink-0">{right}</div>}
      </div>
      <div className={cn("widget-body", bodyClassName)}>{children}</div>
    </section>
  );
}
