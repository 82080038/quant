"use client";

/**
 * FPS guard hook — measures animation-frame rate and triggers bidirectional
 * backpressure when the UI struggles.
 *
 * When FPS stays below `lowFps` for `lowWindowMs`, calls `onThrottle(maxRate)`
 * (which should tell the BE to slow its push rate). When FPS recovers above
 * `highFps` for `highWindowMs`, calls `onRelease()`.
 *
 * Cheap: one rAF loop, sampled every 500ms. Returns the latest FPS for display.
 */

import { useEffect, useRef, useState } from "react";

interface FpsGuardOptions {
  lowFps?: number;
  highFps?: number;
  lowWindowMs?: number;
  highWindowMs?: number;
  sampleMs?: number;
  maxRate?: number;
  onThrottle: (maxRate: number) => void;
  onRelease: () => void;
}

export function useFpsGuard(opts: FpsGuardOptions): number {
  const {
    lowFps = 30,
    highFps = 55,
    lowWindowMs = 2000,
    highWindowMs = 2000,
    sampleMs = 500,
    maxRate = 50,
    onThrottle,
    onRelease,
  } = opts;

  const [fps, setFps] = useState(60);
  const lowSinceRef = useRef<number | null>(null);
  const highSinceRef = useRef<number | null>(null);
  const throttledRef = useRef(false);
  const cbRef = useRef({ onThrottle, onRelease });
  cbRef.current = { onThrottle, onRelease };

  useEffect(() => {
    let rafId = 0;
    let lastFrame = performance.now();
    let samples: number[] = [];
    let lastSample = performance.now();

    const loop = (now: number) => {
      const dt = now - lastFrame;
      lastFrame = now;
      if (dt > 0) samples.push(1000 / dt);

      if (now - lastSample >= sampleMs) {
        const avg = samples.length
          ? samples.reduce((a, b) => a + b, 0) / samples.length
          : 60;
        samples = [];
        lastSample = now;
        setFps(avg);

        if (avg < lowFps) {
          if (lowSinceRef.current === null) lowSinceRef.current = now;
          else if (now - lowSinceRef.current >= lowWindowMs && !throttledRef.current) {
            throttledRef.current = true;
            highSinceRef.current = null;
            cbRef.current.onThrottle(maxRate);
          }
          highSinceRef.current = null;
        } else if (avg > highFps) {
          if (highSinceRef.current === null) highSinceRef.current = now;
          else if (now - highSinceRef.current >= highWindowMs && throttledRef.current) {
            throttledRef.current = false;
            lowSinceRef.current = null;
            cbRef.current.onRelease();
          }
          lowSinceRef.current = null;
        } else {
          // Mid-band: reset recovery timer but keep throttle state as-is.
          highSinceRef.current = null;
        }
      }
      rafId = requestAnimationFrame(loop);
    };
    rafId = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafId);
  }, [lowFps, highFps, lowWindowMs, highWindowMs, sampleMs, maxRate]);

  return fps;
}
