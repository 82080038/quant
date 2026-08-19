"use client";

/**
 * Crosshair synchronization context.
 *
 * Lets chart widgets share a single hover/crosshair state so moving the
 * pointer over one chart highlights the same timestamp on every other
 * subscribed chart. Lightweight: a single ref + coalesced listeners.
 */

import { createContext, useContext, useRef, type ReactNode } from "react";

export interface CrosshairState {
  ts: number | null;     // timestamp (ms) under the cursor, or null when cleared
  source: string | null; // widget id that emitted the current state
}

type Listener = (state: CrosshairState) => void;

class CrosshairStore {
  private state: CrosshairState = { ts: null, source: null };
  private listeners: Set<Listener> = new Set();

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  get(): CrosshairState {
    return this.state;
  }

  set(ts: number | null, source: string | null): void {
    this.state = { ts, source };
    for (const l of this.listeners) {
      try {
        l(this.state);
      } catch {
        /* ignore */
      }
    }
  }
}

const CrosshairContext = createContext<CrosshairStore | null>(null);

export function CrosshairProvider({ children }: { children: ReactNode }) {
  const storeRef = useRef<CrosshairStore | null>(null);
  if (!storeRef.current) storeRef.current = new CrosshairStore();
  return (
    <CrosshairContext.Provider value={storeRef.current}>
      {children}
    </CrosshairContext.Provider>
  );
}

export function useCrosshairStore(): CrosshairStore {
  const ctx = useContext(CrosshairContext);
  if (!ctx) throw new Error("useCrosshairStore must be used within CrosshairProvider");
  return ctx;
}
