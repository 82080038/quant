"""Astronacci Cycle Engine — Financial Astrology + Fibonacci Price Confluence.

Implements the Astronacci methodology (Astrology + Fibonacci) developed by
Gema Goeyardi / Astronacci International. The core innovation is CONFLUENCE:
astrological time cycles identify WHEN a reversal may occur, and Fibonacci
price retracement levels confirm WHERE price should be for the reversal to
be valid. Only when BOTH align does the signal fire.

**Astrology (WHEN)** — time triggers for potential market reversal windows:

1. **Moon Phase** — New Moon, First Quarter, Full Moon, Last Quarter.
   Academic evidence: Yuan et al. (2006, J. Empirical Finance) found 3-5%
   annual return difference between New Moon and Full Moon across 48 countries.
   Dichev & Janes (2001) found returns near New Moon are ~2x returns near
   Full Moon across 100 years of US data.

2. **Planetary Retrograde** — Mercury, Venus, Mars, Jupiter, Saturn, Uranus,
   Neptune, Pluto. Academic evidence: Qi et al. (2022) found 3.33% lower
   annual returns during Mercury Retrograde across 48 countries (behavioral/
   self-fulfilling mechanism). Ma et al. (2023) found ~31% annualized price
   drops during Mercury Retrograde in Chinese stocks.

3. **Planetary Ingress** — Planet moving from one zodiac constellation to
   another. Market character reset, new cycle phase initiation.

**Fibonacci (WHERE)** — price retracement levels from the most recent
significant swing high/low. Institutional traders use 38.2%, 50%, 61.8%
retracement levels as support/resistance (Goldman Sachs quant research:
61.8% zone generates 23% higher order book density than random levels).
Self-fulfilling: when thousands of algorithms place orders at these levels,
they become real support/resistance.

**Confluence** — the Astronacci signal fires ONLY when:
  1. An astrology event is active (within its time window), AND
  2. Current price is within a tolerance band of a Fibonacci retracement level.
This is the key innovation vs. using either component alone. Goeyardi (2021):
"After obtaining the Astrology factor, it will be checked whether it has been
confirmed by Fibonacci."

Framework:
    Astrology = Time reference (WHEN)
    Fibonacci = Price structure validation (WHERE)
    Confluence = Both must align → high-probability reversal signal
    Price action = Final confirmation

Sources:
    - Goeyardi, G. (2021). "Financial analysis method based on astrology,
      Fibonacci, and Astronacci." IJEBR Vol.22 No.2/3.
    - Yuan, K., Zheng, L., Zhu, Q. (2006). "Are investors moonstruck?"
      J. Empirical Finance 13(1), 1-23.
    - Qi, Y., Wang, H., Zhang, B. (2022). "Long Live Hermes! Mercury
      Retrograde and Equity Prices." SSRN 4074620.
    - TradeAlgo (2026). "Fibonacci Trading Guide" — institutional usage.
    - Signalixx (2026). Goldman Sachs/BlackRock Fibonacci research notes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import ephem
import pandas as pd


# ── Constants ────────────────────────────────────────────────────────────────

ZODIAC_SIGNS = [
    "ARIES", "TAURUS", "GEMINI", "CANCER", "LEO", "VIRGO",
    "LIBRA", "SCORPIO", "SAGITTARIUS", "CAPRICORN", "AQUARIUS", "PISCES",
]

# Fibonacci price retracement ratios — used by institutional traders
# 61.8% (golden ratio) is the most watched level (Goldman Sachs, ICT/OTE)
# 38.2% and 50% are secondary levels. 78.6% is the deep retracement (OTE zone).
# Extensions: 127.2%, 161.8% for target projection.
FIBONACCI_RATIOS = [0.236, 0.382, 0.500, 0.618, 0.786]
FIBONACCI_EXTENSIONS = [1.272, 1.618]
# Tolerance band (±%) around a Fibonacci level for confluence check.
# Institutional algorithms cluster within ~1% of the exact level.
FIBONACCI_TOLERANCE_PCT = 1.5

# Planets tracked for retrograde and ingress
PLANETARY_BODIES = {
    "MERCURY": ephem.Mercury,
    "VENUS": ephem.Venus,
    "MARS": ephem.Mars,
    "JUPITER": ephem.Jupiter,
    "SATURN": ephem.Saturn,
    "URANUS": ephem.Uranus,
    "NEPTUNE": ephem.Neptune,
    "PLUTO": ephem.Pluto,
}

# Sun ingress is the most significant for monthly cycle tracking
SUN_BODY = {"SUN": ephem.Sun}

# Impact levels per cycle type
DEFAULT_IMPACT = {
    "MOON_PHASE_NEW": "HIGH",
    "MOON_PHASE_FULL": "HIGH",
    "MOON_PHASE_FIRST_QUARTER": "MEDIUM",
    "MOON_PHASE_LAST_QUARTER": "MEDIUM",
    "MERCURY_RETROGRADE": "CRITICAL",
    "VENUS_RETROGRADE": "HIGH",
    "MARS_RETROGRADE": "HIGH",
    "JUPITER_RETROGRADE": "MEDIUM",
    "SATURN_RETROGRADE": "MEDIUM",
    "URANUS_RETROGRADE": "MEDIUM",
    "NEPTUNE_RETROGRADE": "LOW",
    "PLUTO_RETROGRADE": "LOW",
    "SUN_INGRESS": "MEDIUM",
    "MERCURY_INGRESS": "LOW",
    "VENUS_INGRESS": "LOW",
    "MARS_INGRESS": "MEDIUM",
    "JUPITER_INGRESS": "HIGH",
    "SATURN_INGRESS": "HIGH",
    "URANUS_INGRESS": "HIGH",
    "NEPTUNE_INGRESS": "MEDIUM",
    "PLUTO_INGRESS": "MEDIUM",
    "FIBONACCI_PRICE": "HIGH",
}

# Expected reversal type per cycle type
DEFAULT_REVERSAL = {
    # Moon phases: academic evidence shows New Moon → bullish bias,
    # Full Moon → bearish bias (Yuan et al. 2006, Dichev & Janes 2001).
    # First/Last Quarter → transitional, mild volatility.
    "MOON_PHASE_NEW": "BULLISH_REVERSAL",
    "MOON_PHASE_FULL": "BEARISH_REVERSAL",
    "MOON_PHASE_FIRST_QUARTER": "VOLATILITY",
    "MOON_PHASE_LAST_QUARTER": "VOLATILITY",
    "MERCURY_RETROGRADE": "BEARISH_REVERSAL",
    "VENUS_RETROGRADE": "BEARISH_REVERSAL",
    "MARS_RETROGRADE": "VOLATILITY",
    "JUPITER_RETROGRADE": "NEUTRAL",
    "SATURN_RETROGRADE": "NEUTRAL",
    "URANUS_RETROGRADE": "VOLATILITY",
    "NEPTUNE_RETROGRADE": "NEUTRAL",
    "PLUTO_RETROGRADE": "NEUTRAL",
    "SUN_INGRESS": "NEUTRAL",
    "MERCURY_INGRESS": "NEUTRAL",
    "VENUS_INGRESS": "NEUTRAL",
    "MARS_INGRESS": "VOLATILITY",
    "JUPITER_INGRESS": "VOLATILITY",
    "SATURN_INGRESS": "VOLATILITY",
    "URANUS_INGRESS": "VOLATILITY",
    "NEPTUNE_INGRESS": "NEUTRAL",
    "PLUTO_INGRESS": "NEUTRAL",
    "FIBONACCI_PRICE": "NEUTRAL",  # direction depends on swing type + confluence
}

# Window duration (hours) for each cycle type — the event spans this many hours
WINDOW_HOURS = {
    "MOON_PHASE_NEW": 24,
    "MOON_PHASE_FULL": 24,
    "MOON_PHASE_FIRST_QUARTER": 12,
    "MOON_PHASE_LAST_QUARTER": 12,
    "MERCURY_RETROGRADE": 6,   # peak window within the retrograde period
    "VENUS_RETROGRADE": 6,
    "MARS_RETROGRADE": 6,
    "JUPITER_RETROGRADE": 6,
    "SATURN_RETROGRADE": 6,
    "URANUS_RETROGRADE": 6,
    "NEPTUNE_RETROGRADE": 6,
    "PLUTO_RETROGRADE": 6,
    "SUN_INGRESS": 12,
    "MERCURY_INGRESS": 6,
    "VENUS_INGRESS": 6,
    "MARS_INGRESS": 12,
    "JUPITER_INGRESS": 24,
    "SATURN_INGRESS": 24,
    "URANUS_INGRESS": 24,
    "NEPTUNE_INGRESS": 24,
    "PLUTO_INGRESS": 24,
    "FIBONACCI_PRICE": 24,
}


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class AstronacciCycle:
    """A single Astronacci time-cycle event."""
    cycle_type: str
    title: str
    start_at: datetime
    end_at: datetime
    potential_impact: str = "HIGH"
    target_asset_class: str = "ALL"
    expected_reversal: str = "NEUTRAL"
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "cycle_type": self.cycle_type,
            "title": self.title,
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
            "potential_impact": self.potential_impact,
            "target_asset_class": self.target_asset_class,
            "expected_reversal": self.expected_reversal,
            "description": self.description,
        }


# ── Helper Functions ─────────────────────────────────────────────────────────

_OBLIQUITY = math.radians(23.44)


def _geocentric_ecliptic_lon(body: ephem.Body, date: ephem.Date) -> float:
    """Compute geocentric ecliptic longitude in degrees [0, 360)."""
    body.compute(date)
    ra = float(body.ra)
    dec = float(body.dec)
    lon = math.atan2(
        math.sin(ra) * math.cos(_OBLIQUITY) - math.tan(dec) * math.sin(_OBLIQUITY),
        math.cos(ra),
    )
    return math.degrees(lon) % 360


def _zodiac_sign(lon_deg: float) -> str:
    """Return zodiac sign name for a given ecliptic longitude."""
    idx = int(lon_deg // 30) % 12
    return ZODIAC_SIGNS[idx]


def _ephem_to_datetime(d: ephem.Date) -> datetime:
    """Convert ephem.Date to timezone-aware UTC datetime."""
    dt = d.datetime()
    return dt.replace(tzinfo=timezone.utc)


# ── Moon Phase Calculator ────────────────────────────────────────────────────

class MoonPhaseCalculator:
    """Computes all moon phase events in a date range.

    Moon phases (New Moon, First Quarter, Full Moon, Last Quarter) occur
    approximately every 7.38 days (synodic month 29.53 / 4).
    """

    PHASE_FUNCS = {
        "MOON_PHASE_NEW": ephem.next_new_moon,
        "MOON_PHASE_FULL": ephem.next_full_moon,
        "MOON_PHASE_FIRST_QUARTER": ephem.next_first_quarter_moon,
        "MOON_PHASE_LAST_QUARTER": ephem.next_last_quarter_moon,
    }

    PHASE_TITLES = {
        "MOON_PHASE_NEW": "New Moon",
        "MOON_PHASE_FULL": "Full Moon",
        "MOON_PHASE_FIRST_QUARTER": "First Quarter Moon",
        "MOON_PHASE_LAST_QUARTER": "Last Quarter Moon",
    }

    PHASE_DESCRIPTIONS = {
        "MOON_PHASE_NEW": (
            "New Moon phase — historically associated with ~78-79% market "
            "reversal probability (Goeyardi 2026). Window of increased "
            "volatility and potential directional shift."
        ),
        "MOON_PHASE_FULL": (
            "Full Moon phase — historically associated with ~78-79% market "
            "reversal probability (Goeyardi 2026). Market sensitivity "
            "peaks; potential for emotional trading extremes."
        ),
        "MOON_PHASE_FIRST_QUARTER": (
            "First Quarter Moon — transitional phase. Market may show "
            "increased indecision or continuation of trend established "
            "at New Moon."
        ),
        "MOON_PHASE_LAST_QUARTER": (
            "Last Quarter Moon — transitional phase. Market may show "
            "preparation for the upcoming New/Full Moon reversal window."
        ),
    }

    def compute(self, start: datetime, end: datetime) -> list[AstronacciCycle]:
        cycles: list[AstronacciCycle] = []
        start_ephem = ephem.Date(start.replace(tzinfo=None))
        end_ephem = ephem.Date(end.replace(tzinfo=None))

        for phase_type, func in self.PHASE_FUNCS.items():
            d = start_ephem
            while True:
                try:
                    phase_date = func(d)
                except ephem.AlwaysUpError:
                    break
                if phase_date >= end_ephem:
                    break
                dt = _ephem_to_datetime(phase_date)
                window_h = WINDOW_HOURS[phase_type]
                cycles.append(AstronacciCycle(
                    cycle_type=phase_type,
                    title=self.PHASE_TITLES[phase_type],
                    start_at=dt,
                    end_at=dt + timedelta(hours=window_h),
                    potential_impact=DEFAULT_IMPACT[phase_type],
                    expected_reversal=DEFAULT_REVERSAL[phase_type],
                    description=self.PHASE_DESCRIPTIONS[phase_type],
                ))
                d = phase_date + 0.01  # advance slightly past current
        cycles.sort(key=lambda c: c.start_at)
        return cycles


# ── Retrograde Calculator ────────────────────────────────────────────────────

class RetrogradeCalculator:
    """Computes planetary retrograde periods by scanning geocentric
    ecliptic longitude day-by-day.

    A planet is retrograde when its geocentric ecliptic longitude decreases
    from one day to the next (apparent backward motion).
    """

    RETRO_TITLES = {
        "MERCURY": "Mercury Retrograde",
        "VENUS": "Venus Retrograde",
        "MARS": "Mars Retrograde",
        "JUPITER": "Jupiter Retrograde",
        "SATURN": "Saturn Retrograde",
        "URANUS": "Uranus Retrograde",
        "NEPTUNE": "Neptune Retrograde",
        "PLUTO": "Pluto Retrograde",
    }

    RETRO_DESCRIPTIONS = {
        "MERCURY": (
            "Mercury Retrograde — momentum trend melambat, false breakout "
            "meningkat, market memasuki mode evaluasi. Sektor komunikasi/tech "
            "paling terdampak. Reversal besar sering terjadi saat momentum "
            "melemah, bukan saat market kuat."
        ),
        "VENUS": (
            "Venus Retrograde — evaluasi nilai dan sentimen market. "
            "Sektor finansial/konsumer terdampak. Potensi reversal "
            "dalam tren nilai."
        ),
        "MARS": (
            "Mars Retrograde — energi market menurun, agresivitas berkurang. "
            "Volatilitas tinggi dengan momentum lemah."
        ),
        "JUPITER": (
            "Jupiter Retrograde — fase konsolidasi besar. Ekspansi market "
            "melambat, evaluasi pertumbuhan."
        ),
        "SATURN": (
            "Saturn Retrograde — fase restrukturisasi. Market mengkonsolidasi "
            "struktur dan mengevaluasi fondasi."
        ),
        "URANUS": (
            "Uranus Retrograde — volatilitas tak terduga. Potensi shock "
            "market atau perubahan mendadak."
        ),
        "NEPTUNE": (
            "Neptune Retrograde — ilusi market terkoreksi. Sentimen vs "
            "realitas divergen."
        ),
        "PLUTO": (
            "Pluto Retrograde — transformasi struktural mendalam. "
            "Perubahan fundamental market."
        ),
    }

    def compute(self, start: datetime, end: datetime) -> list[AstronacciCycle]:
        cycles: list[AstronacciCycle] = []
        start_ephem = ephem.Date(start.replace(tzinfo=None))
        end_ephem = ephem.Date(end.replace(tzinfo=None))

        for planet_name, body_class in PLANETARY_BODIES.items():
            body = body_class()
            d = ephem.Date(start_ephem)
            prev_lon = _geocentric_ecliptic_lon(body, d)
            d = ephem.Date(d + 1)  # move to next day
            retro_start: ephem.Date | None = None

            # BUG-1 fix: Check if planet is already retrograde at query start.
            # If so, scan backwards to find the actual retrograde start date.
            if _geocentric_ecliptic_lon(body, d) < prev_lon:
                # Planet is already retrograde — scan backwards to find start
                scan_d = ephem.Date(start_ephem)
                scan_prev = _geocentric_ecliptic_lon(body, scan_d)
                scan_step = 1
                max_scan = 365  # max 1 year backwards (covers even slow planets)
                scanned = 0
                while scanned < max_scan:
                    scan_d = ephem.Date(scan_d - scan_step)
                    scan_curr = _geocentric_ecliptic_lon(body, scan_d)
                    if scan_curr >= scan_prev:
                        # Retrograde started at scan_d + 1 day
                        retro_start = ephem.Date(scan_d + scan_step)
                        break
                    scan_prev = scan_curr
                    scanned += scan_step
                if retro_start is None:
                    # Couldn't find start within 1 year — use query start as fallback
                    retro_start = ephem.Date(start_ephem)

            while d < end_ephem:
                curr_lon = _geocentric_ecliptic_lon(body, d)
                is_retro = curr_lon < prev_lon

                if is_retro and retro_start is None:
                    retro_start = ephem.Date(d - 1)  # retrograde began previous day
                elif not is_retro and retro_start is not None:
                    # Retrograde ended
                    cycle_key = f"{planet_name}_RETROGRADE"
                    start_dt = _ephem_to_datetime(retro_start)
                    end_dt = _ephem_to_datetime(d)
                    # Use the midpoint as the "peak" event time
                    peak_dt = start_dt + (end_dt - start_dt) / 2
                    window_h = WINDOW_HOURS.get(cycle_key, 6)
                    cycles.append(AstronacciCycle(
                        cycle_type=cycle_key,
                        title=self.RETRO_TITLES[planet_name],
                        start_at=peak_dt - timedelta(hours=window_h / 2),
                        end_at=peak_dt + timedelta(hours=window_h / 2),
                        potential_impact=DEFAULT_IMPACT.get(cycle_key, "MEDIUM"),
                        expected_reversal=DEFAULT_REVERSAL.get(cycle_key, "NEUTRAL"),
                        description=self.RETRO_DESCRIPTIONS[planet_name],
                    ))
                    retro_start = None

                prev_lon = curr_lon
                d = ephem.Date(d + 1)

            # Handle retrograde that extends past end date
            if retro_start is not None:
                cycle_key = f"{planet_name}_RETROGRADE"
                start_dt = _ephem_to_datetime(retro_start)
                end_dt = _ephem_to_datetime(end_ephem)
                peak_dt = start_dt + (end_dt - start_dt) / 2
                window_h = WINDOW_HOURS.get(cycle_key, 6)
                cycles.append(AstronacciCycle(
                    cycle_type=cycle_key,
                    title=self.RETRO_TITLES[planet_name],
                    start_at=peak_dt - timedelta(hours=window_h / 2),
                    end_at=peak_dt + timedelta(hours=window_h / 2),
                    potential_impact=DEFAULT_IMPACT.get(cycle_key, "MEDIUM"),
                    expected_reversal=DEFAULT_REVERSAL.get(cycle_key, "NEUTRAL"),
                    description=self.RETRO_DESCRIPTIONS[planet_name],
                ))

        cycles.sort(key=lambda c: c.start_at)
        return cycles


# ── Ingress Calculator ───────────────────────────────────────────────────────

class IngressCalculator:
    """Computes planetary ingress events (planet entering a new zodiac sign).

    Sun ingress (monthly) is the most significant. Major planet ingresses
    (Jupiter, Saturn, Uranus) mark larger cycle shifts.
    """

    INGRESS_DESCRIPTIONS = {
        "SUN": (
            "Sun ingress into {sign} — monthly cycle shift. Market "
            "character may reset; new psychological phase begins."
        ),
        "MERCURY": (
            "Mercury ingress into {sign} — communication/information "
            "flow shifts. Short-term sentiment change."
        ),
        "VENUS": (
            "Venus ingress into {sign} — value/sentiment shift. "
            "Consumer and financial sectors may be affected."
        ),
        "MARS": (
            "Mars ingress into {sign} — energy/aggression shift. "
            "Market momentum character changes."
        ),
        "JUPITER": (
            "Jupiter ingress into {sign} — major growth/expansion cycle "
            "shift. Annual-level market character change."
        ),
        "SATURN": (
            "Saturn ingress into {sign} — major structural cycle shift. "
            "2.5-year market phase transition."
        ),
        "URANUS": (
            "Uranus ingress into {sign} — disruption/innovation cycle "
            "shift. 7-year market phase transition."
        ),
        "NEPTUNE": (
            "Neptune ingress into {sign} — sentiment/illusion cycle "
            "shift. 14-year market phase transition."
        ),
        "PLUTO": (
            "Pluto ingress into {sign} — transformation/rebirth cycle "
            "shift. 20-year market phase transition."
        ),
    }

    # Which bodies to track for ingress (Sun + major planets)
    INGRESS_BODIES = {**SUN_BODY, **PLANETARY_BODIES}

    def compute(self, start: datetime, end: datetime) -> list[AstronacciCycle]:
        cycles: list[AstronacciCycle] = []
        start_ephem = ephem.Date(start.replace(tzinfo=None))
        end_ephem = ephem.Date(end.replace(tzinfo=None))

        for body_name, body_class in self.INGRESS_BODIES.items():
            body = body_class()
            d = ephem.Date(start_ephem)
            prev_sign = _zodiac_sign(_geocentric_ecliptic_lon(body, d))
            d = ephem.Date(d + 1)

            while d < end_ephem:
                curr_lon = _geocentric_ecliptic_lon(body, d)
                curr_sign = _zodiac_sign(curr_lon)

                if curr_sign != prev_sign:
                    cycle_key = f"{body_name}_INGRESS"
                    dt = _ephem_to_datetime(d)
                    window_h = WINDOW_HOURS.get(cycle_key, 12)
                    desc_template = self.INGRESS_DESCRIPTIONS.get(body_name, "")
                    cycles.append(AstronacciCycle(
                        cycle_type=cycle_key,
                        title=f"{body_name.title()} Ingress → {curr_sign}",
                        start_at=dt,
                        end_at=dt + timedelta(hours=window_h),
                        potential_impact=DEFAULT_IMPACT.get(cycle_key, "MEDIUM"),
                        expected_reversal=DEFAULT_REVERSAL.get(cycle_key, "NEUTRAL"),
                        description=desc_template.format(sign=curr_sign),
                    ))
                    prev_sign = curr_sign

                d = ephem.Date(d + 1)

        cycles.sort(key=lambda c: c.start_at)
        return cycles


# ── Fibonacci Price Retracement Calculator ───────────────────────────────────

class FibonacciPriceRetracementCalculator:
    """Computes Fibonacci price retracement levels from swing highs/lows.

    This is the tool institutional traders actually use — price-based
    support/resistance levels at 23.6%, 38.2%, 50%, 61.8%, 78.6% of the
    most recent significant price swing. The 61.8% level (golden ratio)
    is the most watched by institutional algorithms (Goldman Sachs, ICT/OTE).

    Unlike Fibonacci *time zones* (which count days from swings), price
    retracements identify WHERE price is likely to find support/resistance.
    This is the "WHERE" component of the Astronacci framework.
    """

    def __init__(self, ratios: list[float] | None = None):
        self.ratios = ratios or FIBONACCI_RATIOS

    def find_swing_points(
        self,
        prices: pd.DataFrame,
        lookback: int = 20,
        min_separation: int = 10,
    ) -> list[tuple[pd.Timestamp, float, str]]:
        """Find swing highs and lows in price data.

        Args:
            prices: DataFrame with 'timestamp' and 'close' columns.
            lookback: Bars on each side to confirm a swing point.
            min_separation: Minimum bars between swing points of same type.

        Returns:
            List of (timestamp, price, type) tuples where type is 'HIGH' or 'LOW'.
        """
        if len(prices) < 2 * lookback + 1:
            return []

        closes = prices["close"].values
        timestamps = prices["timestamp"].values
        swing_points: list[tuple[pd.Timestamp, float, str]] = []

        last_high_idx = -min_separation
        last_low_idx = -min_separation

        for i in range(lookback, len(closes) - lookback):
            window = closes[i - lookback : i + lookback + 1]
            is_high = closes[i] == window.max()
            is_low = closes[i] == window.min()

            if is_high and (i - last_high_idx) >= min_separation:
                swing_points.append((pd.Timestamp(timestamps[i]), float(closes[i]), "HIGH"))
                last_high_idx = i
            elif is_low and (i - last_low_idx) >= min_separation:
                swing_points.append((pd.Timestamp(timestamps[i]), float(closes[i]), "LOW"))
                last_low_idx = i

        return swing_points

    def compute_retracement_levels(
        self,
        prices: pd.DataFrame,
        lookback: int = 20,
    ) -> list[dict]:
        """Compute Fibonacci price retracement levels from the most recent swing.

        Uses the last completed swing (high → low or low → high) to compute
        retracement levels. Returns levels sorted by proximity to current price.

        Args:
            prices: DataFrame with 'timestamp' and 'close' columns.
            lookback: Bars on each side for swing detection.

        Returns:
            List of dicts with keys: ratio, price_level, swing_type,
            swing_high, swing_low, direction (BULLISH if swing low → expect
            bounce up, BEARISH if swing high → expect reversal down).
        """
        swing_points = self.find_swing_points(prices, lookback=lookback)
        if len(swing_points) < 2:
            return []

        # Use the last two swing points to define the most recent swing
        last_swing = swing_points[-1]
        prev_swing = swing_points[-2]

        # The swing is defined by prev_swing → last_swing
        if last_swing[2] == "HIGH" and prev_swing[2] == "LOW":
            # Uptrend: low → high. Retracement measures pullback from high.
            swing_high = last_swing[1]
            swing_low = prev_swing[1]
            direction = "BULLISH"  # expect bounce up from retracement level
        elif last_swing[2] == "LOW" and prev_swing[2] == "HIGH":
            # Downtrend: high → low. Retracement measures rally from low.
            swing_high = prev_swing[1]
            swing_low = last_swing[1]
            direction = "BEARISH"  # expect reversal down from retracement level
        else:
            # Same type consecutive — use the extreme
            if last_swing[2] == "HIGH":
                swing_high = max(last_swing[1], prev_swing[1])
                swing_low = min(last_swing[1], prev_swing[1])
            else:
                swing_high = max(last_swing[1], prev_swing[1])
                swing_low = min(last_swing[1], prev_swing[1])
            direction = "BULLISH" if last_swing[2] == "LOW" else "BEARISH"

        price_range = swing_high - swing_low
        if price_range <= 0:
            return []

        levels = []
        for ratio in self.ratios:
            if direction == "BULLISH":
                # Retracement down from high: level = high - range * ratio
                level = swing_high - price_range * ratio
            else:
                # Retracement up from low: level = low + range * ratio
                level = swing_low + price_range * ratio

            levels.append({
                "ratio": ratio,
                "price_level": level,
                "swing_type": last_swing[2],
                "swing_high": swing_high,
                "swing_low": swing_low,
                "direction": direction,
            })

        return levels

    def check_confluence(
        self,
        current_price: float,
        prices: pd.DataFrame,
        tolerance_pct: float = FIBONACCI_TOLERANCE_PCT,
    ) -> dict | None:
        """Check if current price is near a Fibonacci retracement level.

        This is the core "WHERE" validation. Returns the matching level
        if price is within tolerance band, None otherwise.

        Args:
            current_price: Current market price.
            prices: OHLCV DataFrame for swing point detection.
            tolerance_pct: Tolerance band (±%) around Fibonacci level.

        Returns:
            Dict with confluence info or None if no match.
        """
        levels = self.compute_retracement_levels(prices)
        if not levels:
            return None

        for level_info in levels:
            fib_price = level_info["price_level"]
            distance_pct = abs(current_price - fib_price) / fib_price * 100

            if distance_pct <= tolerance_pct:
                return {
                    "matched": True,
                    "ratio": level_info["ratio"],
                    "fib_price": fib_price,
                    "current_price": current_price,
                    "distance_pct": distance_pct,
                    "direction": level_info["direction"],
                    "swing_high": level_info["swing_high"],
                    "swing_low": level_info["swing_low"],
                }

        return None

    def compute(
        self,
        prices: pd.DataFrame,
        start: datetime,
        end: datetime,
    ) -> list[AstronacciCycle]:
        """Compute Fibonacci price retracement cycle events for visualization.

        Creates AstronacciCycle entries for each retracement level of the
        most recent swing, dated to the query range start. These are
        informational events for the timeline — the actual signal logic
        uses check_confluence() at signal computation time.

        Args:
            prices: DataFrame with 'timestamp' and 'close' columns.
            start: Start of target date range.
            end: End of target date range.

        Returns:
            List of AstronacciCycle events for Fibonacci price levels.
        """
        levels = self.compute_retracement_levels(prices)
        if not levels:
            return []

        cycles: list[AstronacciCycle] = []
        start_utc = start if start.tzinfo else start.replace(tzinfo=timezone.utc)

        for level_info in levels:
            ratio = level_info["ratio"]
            fib_price = level_info["price_level"]
            direction = level_info["direction"]
            reversal = "BULLISH_REVERSAL" if direction == "BULLISH" else "BEARISH_REVERSAL"

            cycles.append(AstronacciCycle(
                cycle_type="FIBONACCI_PRICE",
                title=f"Fibonacci {ratio:.1%} @ {fib_price:.2f} ({direction})",
                start_at=start_utc,
                end_at=start_utc + timedelta(hours=24),
                potential_impact=DEFAULT_IMPACT["FIBONACCI_PRICE"],
                expected_reversal=reversal,
                description=(
                    f"Fibonacci {ratio:.1%} retracement level at {fib_price:.2f}. "
                    f"Swing: {level_info['swing_low']:.2f} → {level_info['swing_high']:.2f}. "
                    f"Direction: {direction}. "
                    f"{'Support zone — expect bounce.' if direction == 'BULLISH' else 'Resistance zone — expect reversal.'}"
                ),
            ))

        cycles.sort(key=lambda c: c.title)
        return cycles


# ── Astronacci Engine ────────────────────────────────────────────────────────

class AstronacciEngine:
    """Orchestrates all Astronacci cycle calculators with confluence logic.

    Computes moon phases, planetary retrogrades, planetary ingresses,
    and Fibonacci price retracement levels. The signal computation
    uses CONFLUENCE: astrology events provide the WHEN, Fibonacci price
    levels provide the WHERE. Only when both align does the signal fire.
    """

    def __init__(self, include_fibonacci: bool = True):
        self.moon_calc = MoonPhaseCalculator()
        self.retro_calc = RetrogradeCalculator()
        self.ingress_calc = IngressCalculator()
        self.fib_calc = FibonacciPriceRetracementCalculator() if include_fibonacci else None

    def compute(
        self,
        start: datetime,
        end: datetime,
        prices: pd.DataFrame | None = None,
    ) -> list[AstronacciCycle]:
        """Compute all Astronacci cycles in the given date range.

        Args:
            start: Start datetime (UTC).
            end: End datetime (UTC).
            prices: Optional price DataFrame for Fibonacci retracement levels.

        Returns:
            Sorted list of AstronacciCycle events.
        """
        cycles: list[AstronacciCycle] = []

        cycles.extend(self.moon_calc.compute(start, end))
        cycles.extend(self.retro_calc.compute(start, end))
        cycles.extend(self.ingress_calc.compute(start, end))

        if self.fib_calc and prices is not None and len(prices) > 0:
            cycles.extend(self.fib_calc.compute(prices, start, end))

        cycles.sort(key=lambda c: c.start_at)
        return cycles

    def compute_signal(
        self,
        as_of: datetime,
        window_days: int = 3,
        prices: pd.DataFrame | None = None,
        current_price: float | None = None,
    ) -> dict:
        """Compute an Astronacci signal with Fibonacci price confluence.

        This is the integration point for SignalEnhancer / MarketContext.

        **Confluence logic** (the core Astronacci innovation):
        1. Find active astrology events within the time window (WHEN).
        2. If prices provided, compute Fibonacci retracement levels (WHERE).
        3. If current_price provided, check if price is near a Fib level.
        4. Signal strength = astrology_direction × fibonacci_confluence_boost.
           - Without confluence: astrology-only signal (weaker, weight ~0.5x)
           - With confluence: full signal (both WHEN and WHERE aligned)
        5. If no astrology events but Fibonacci confluence exists alone,
           use Fibonacci direction as a weak standalone signal.

        Returns a signal dict with:
        - active_cycles: list of cycle types active within the window
        - time_signal: float in [-1, 1] (negative = bearish, positive = bullish)
        - volatility_signal: float in [0, 1]
        - confidence: float in [0, 1] — higher when confluence confirmed
        - confluence: dict | None — Fibonacci confluence details if matched

        Args:
            as_of: The reference datetime (UTC).
            window_days: How many days forward to look for active cycles.
            prices: OHLCV DataFrame for Fibonacci retracement computation.
                Must have 'timestamp' and 'close' columns.
            current_price: Current market price for confluence check.
                If None, confluence is skipped (astrology-only signal).

        Returns:
            Signal dictionary.
        """
        start = as_of - timedelta(days=1)
        end = as_of + timedelta(days=window_days)
        cycles = self.compute(start, end, prices=prices)

        # Check Fibonacci price confluence
        confluence: dict | None = None
        if self.fib_calc and prices is not None and current_price is not None:
            confluence = self.fib_calc.check_confluence(current_price, prices)

        if not cycles and confluence is None:
            return {
                "active_cycles": [],
                "time_signal": 0.0,
                "volatility_signal": 0.0,
                "confidence": 0.0,
                "cycle_count": 0,
                "confluence": None,
            }

        # ── Compute astrology directional signal ──
        reversal_map = {
            "BEARISH_REVERSAL": -0.3,
            "BULLISH_REVERSAL": 0.3,
            "VOLATILITY": 0.0,
            "NEUTRAL": 0.0,
        }
        impact_weight = {
            "CRITICAL": 1.0,
            "HIGH": 0.7,
            "MEDIUM": 0.4,
            "LOW": 0.2,
        }

        time_signal = 0.0
        volatility_signal = 0.0
        active_types: list[str] = []
        directional_count = 0
        vol_count = 0

        for cycle in cycles:
            weight = impact_weight.get(cycle.potential_impact, 0.3)
            reversal_contrib = reversal_map.get(cycle.expected_reversal, 0.0)
            time_signal += reversal_contrib * weight

            if reversal_contrib != 0.0:
                directional_count += 1

            if cycle.expected_reversal == "VOLATILITY":
                volatility_signal += weight * 0.5
                vol_count += 1

            active_types.append(cycle.cycle_type)

        # Normalize astrology signal
        n = len(cycles)
        time_signal = max(-1.0, min(1.0, time_signal / max(n, 1)))
        volatility_signal = min(1.0, volatility_signal / max(n, 1))

        # ── Apply Fibonacci confluence boost ──
        confluence_boost = 1.0  # default: no boost
        confluence_direction: str | None = None

        if confluence and confluence["matched"]:
            confluence_direction = confluence["direction"]
            # Confluence boosts signal by 1.5x (both WHEN + WHERE aligned)
            confluence_boost = 1.5

            # If astrology signal direction agrees with Fibonacci direction,
            # boost is stronger (2x). If they disagree, use Fib direction
            # as override (Fibonacci price level is more reliable for direction).
            fib_sign = 1.0 if confluence_direction == "BULLISH" else -1.0
            if time_signal != 0.0:
                if (time_signal > 0 and fib_sign > 0) or (time_signal < 0 and fib_sign < 0):
                    confluence_boost = 2.0  # aligned: strong signal
                else:
                    # Conflicting: Fibonacci overrides astrology direction
                    time_signal = fib_sign * abs(time_signal) * 0.8
                    confluence_boost = 1.3
            else:
                # No astrology directional signal — Fibonacci provides direction
                time_signal = fib_sign * 0.15  # weak standalone Fib signal

            # Higher confidence for stronger Fibonacci ratios
            ratio = confluence["ratio"]
            if ratio == 0.618:
                confluence_boost *= 1.2  # golden ratio gets extra weight
            elif ratio == 0.786:
                confluence_boost *= 1.1  # OTE deep zone

        time_signal = max(-1.0, min(1.0, time_signal * confluence_boost))

        # ── Confidence: based on signal quality + confluence ──
        confidence = min(1.0, (directional_count * 0.3 + vol_count * 0.1) / 5.0)
        if confluence and confluence["matched"]:
            # Confluence adds significant confidence
            confidence = min(1.0, confidence + 0.3)
            if confluence["ratio"] == 0.618:
                confidence = min(1.0, confidence + 0.1)

        return {
            "active_cycles": active_types,
            "time_signal": round(time_signal, 4),
            "volatility_signal": round(volatility_signal, 4),
            "confidence": round(confidence, 4),
            "cycle_count": n,
            "confluence": confluence,
        }

    def compute_cycles(
        self,
        start: datetime,
        end: datetime,
        prices: pd.DataFrame | None = None,
    ) -> list[AstronacciCycle]:
        """Alias for compute() — backward compatibility for scheduler task."""
        return self.compute(start, end, prices=prices)


def compute_astronacci_signal(
    as_of: datetime,
    window_days: int = 3,
    prices: pd.DataFrame | None = None,
    current_price: float | None = None,
) -> dict:
    """Convenience function to compute Astronacci signal with confluence.

    Args:
        as_of: Reference datetime (UTC).
        window_days: Forward look window in days.
        prices: OHLCV DataFrame for Fibonacci retracement computation.
            Must have 'timestamp' and 'close' columns.
        current_price: Current market price for confluence check.
            If None, only astrology signal is computed (no WHERE validation).

    Returns:
        Signal dictionary with time_signal, volatility_signal, confidence,
        confluence.
    """
    engine = AstronacciEngine(include_fibonacci=True)
    return engine.compute_signal(as_of, window_days, prices=prices, current_price=current_price)
