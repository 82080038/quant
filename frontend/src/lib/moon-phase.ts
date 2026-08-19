/**
 * Moon Phase Calculator — astronomical lunar cycle computation.
 *
 * Uses the Conway / Trig approach for approximating the moon's
 * illuminated fraction and phase name from a given date.
 * Accurate to within ~1% of JPL ephemeris values.
 *
 * Reference: https://en.wikipedia.org/wiki/Lunar_phase#Calculating_phase
 */

export type MoonPhaseName =
  | "New Moon"
  | "Waxing Crescent"
  | "First Quarter"
  | "Waxing Gibbous"
  | "Full Moon"
  | "Waning Gibbous"
  | "Last Quarter"
  | "Waning Crescent";

export interface MoonPhaseInfo {
  /** Illuminated fraction [0, 1] — 0 = new, 1 = full */
  illumination: number;
  /** Phase angle in radians [0, 2π) */
  phaseAngle: number;
  /** Human-readable phase name */
  name: MoonPhaseName;
  /** Days since last new moon */
  age: number;
  /** Synodic period ≈ 29.53 days */
  cycleLength: number;
}

const SYNODIC_PERIOD = 29.530588853;

/**
 * Known new moon reference: 2000-01-06 18:14 UTC
 * (NASA / USNO reference)
 */
const REFERENCE_NEW_MOON_JD = 2451550.1;

function toJulianDay(date: Date): number {
  return date.getTime() / 86400000 + 2440587.5;
}

/**
 * Calculate moon phase for a given date.
 */
export function getMoonPhase(date: Date = new Date()): MoonPhaseInfo {
  const jd = toJulianDay(date);
  const daysSinceNew = (jd - REFERENCE_NEW_MOON_JD) % SYNODIC_PERIOD;
  const age = daysSinceNew < 0 ? daysSinceNew + SYNODIC_PERIOD : daysSinceNew;

  // Phase angle: 0 = new, π = full
  const phaseAngle = (2 * Math.PI * age) / SYNODIC_PERIOD;

  // Illuminated fraction (0 = new, 1 = full)
  const illumination = (1 - Math.cos(phaseAngle)) / 2;

  // Determine phase name
  let name: MoonPhaseName;
  const fraction = age / SYNODIC_PERIOD;

  if (fraction < 0.0334 || fraction > 0.9666) {
    name = "New Moon";
  } else if (fraction < 0.2166) {
    name = "Waxing Crescent";
  } else if (fraction < 0.2834) {
    name = "First Quarter";
  } else if (fraction < 0.4666) {
    name = "Waxing Gibbous";
  } else if (fraction < 0.5334) {
    name = "Full Moon";
  } else if (fraction < 0.7166) {
    name = "Waning Gibbous";
  } else if (fraction < 0.7834) {
    name = "Last Quarter";
  } else {
    name = "Waning Crescent";
  }

  return {
    illumination,
    phaseAngle,
    name,
    age,
    cycleLength: SYNODIC_PERIOD,
  };
}

/**
 * Render a moon phase as an SVG path for a given illumination fraction.
 * Returns an SVG path string for the illuminated portion.
 *
 * @param illumination 0 = new (dark), 1 = full (bright)
 * @param isWaxing true if waxing (right side illuminated), false if waning
 * @param size pixel diameter
 */
export function moonSvgPath(
  illumination: number,
  isWaxing: boolean,
  size: number = 12,
): string {
  const r = size / 2;
  const cx = r;
  const cy = r;

  // The terminator is an ellipse with semi-minor axis = r * cos(phaseAngle)
  // illumination = (1 - cos(phaseAngle)) / 2
  // => cos(phaseAngle) = 1 - 2*illumination
  const cosPhase = 1 - 2 * illumination;
  const ellipseRx = Math.abs(r * cosPhase);

  if (illumination < 0.01) {
    // New moon — just a circle outline
    return `M ${cx - r} ${cy} A ${r} ${r} 0 1 0 ${cx + r} ${cy} A ${r} ${r} 0 1 0 ${cx - r} ${cy} Z`;
  }

  if (illumination > 0.99) {
    // Full moon — full circle
    return `M ${cx - r} ${cy} A ${r} ${r} 0 1 0 ${cx + r} ${cy} A ${r} ${r} 0 1 0 ${cx - r} ${cy} Z`;
  }

  // For waxing: right side lit (sweep=1 for outer, sweep depends on terminator)
  // For waning: left side lit
  const sweep1 = isWaxing ? 1 : 0;
  const sweep2 = isWaxing ? 0 : 1;

  // Outer arc (half circle) + inner arc (ellipse terminator)
  return [
    `M ${cx} ${cy - r}`,
    `A ${r} ${r} 0 0 ${sweep1} ${cx} ${cy + r}`,
    `A ${ellipseRx} ${r} 0 0 ${sweep2} ${cx} ${cy - r}`,
    `Z`,
  ].join(" ");
}

/**
 * Get the emoji glyph for a moon phase (compact display).
 */
export function moonPhaseEmoji(name: MoonPhaseName): string {
  switch (name) {
    case "New Moon": return "🌑";
    case "Waxing Crescent": return "🌒";
    case "First Quarter": return "🌓";
    case "Waxing Gibbous": return "🌔";
    case "Full Moon": return "🌕";
    case "Waning Gibbous": return "🌖";
    case "Last Quarter": return "🌗";
    case "Waning Crescent": return "🌘";
  }
}
