/**
 * Lightweight astronomical background for the dashboard.
 *
 * Three purely-decorative CSS layers (see globals.css):
 *   1. `.celestial-bg`    — radial gradients (deep space + nebula tints)
 *   2. `.celestial-stars` — static SVG starfield (cached compositor layer)
 *   3. `.celestial-orbit` — three faint orbit rings with `orbit-pulse`
 *
 * Total idle cost: <1% CPU, 0 GPU. No WebGL, no per-frame canvas.
 * Respects `prefers-reduced-motion` (pulse disabled via CSS).
 */
export function CelestialBg() {
  return (
    <>
      <div className="celestial-bg" aria-hidden="true" />
      <div className="celestial-stars" aria-hidden="true" />
      <div className="celestial-orbit o1" aria-hidden="true" />
      <div className="celestial-orbit o2" aria-hidden="true" />
      <div className="celestial-orbit o3" aria-hidden="true" />
    </>
  );
}
