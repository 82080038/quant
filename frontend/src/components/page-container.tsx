"use client";

/**
 * Route-aware page container.
 *
 * The dashboard (`/`) needs a fixed, no-scroll grid that fills the viewport.
 * Every other route keeps the legacy padded, scrollable layout. Deciding per
 * route here (client-side via `usePathname`) means we don't have to edit the
 * 15+ existing pages — they keep their own `p-6` roots and scroll naturally.
 */

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const FIXED_ROUTES = new Set(["/"]);

export function PageContainer({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const fixed = FIXED_ROUTES.has(pathname);

  if (fixed) {
    // Dashboard manages its own grid; fill the main area edge-to-edge.
    return <div className="h-full w-full overflow-hidden">{children}</div>;
  }
  // Legacy pages: padded, vertically scrollable.
  return <div className="h-full w-full overflow-auto p-6">{children}</div>;
}
