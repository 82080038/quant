"""
Multi-monitor detection utility — find Epson PJ coordinates.

Linux: uses xrandr to detect monitors and their positions.
Cross-platform fallback: uses screeninfo library if available.
"""

import subprocess
import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MonitorInfo:
    name: str
    x: int
    y: int
    width: int
    height: int
    is_primary: bool
    is_epson: bool


def detect_monitors() -> list[MonitorInfo]:
    """Detect all connected monitors using xrandr (Linux)."""
    monitors = []

    try:
        result = subprocess.run(
            ["xrandr", "--listmonitors"],
            capture_output=True, text=True, timeout=5,
        )
        output = result.stdout

        # Parse: " 0: +*HDMI-0 1920/476x1080/268+0+900  HDMI-0"
        pattern = re.compile(
            r"^\s*(\d+):\s+(\+?)(\*?)(\S+)\s+(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)\s+(\S+)",
            re.MULTILINE,
        )

        for match in pattern.finditer(output):
            is_primary = match.group(3) == "*"
            mon_name = match.group(9)
            width = int(match.group(5))
            height = int(match.group(6))
            x = int(match.group(7))
            y = int(match.group(8))

            # Detect Epson: HDMI-1-0 is the Epson PJ (no EDID name, but it's the projector)
            # Also check for "EPSON" in monitor name
            is_epson = "EPSON" in mon_name.upper() or mon_name == "HDMI-1-0"

            monitors.append(MonitorInfo(
                name=mon_name,
                x=x, y=y,
                width=width, height=height,
                is_primary=is_primary,
                is_epson=is_epson,
            ))

    except Exception as e:
        logger.warning("xrandr detection failed: %s", e)

    return monitors


def find_epson_monitor() -> MonitorInfo | None:
    """Find the Epson PJ monitor specifically."""
    monitors = detect_monitors()
    for m in monitors:
        if m.is_epson:
            logger.info("Epson PJ detected: %s at (%d, %d) %dx%d", m.name, m.x, m.y, m.width, m.height)
            return m
    logger.warning("Epson PJ monitor not found among %d monitors", len(monitors))
    return None


def get_epson_window_position() -> tuple[int, int]:
    """Get the X,Y coordinates for positioning a window on the Epson monitor."""
    epson = find_epson_monitor()
    if epson:
        return (epson.x, epson.y)
    # Fallback: assume Epson is at 1339, 0 (from previous detection)
    return (1339, 0)


def get_epson_resolution() -> tuple[int, int]:
    """Get the Epson monitor resolution."""
    epson = find_epson_monitor()
    if epson:
        return (epson.width, epson.height)
    return (1440, 900)


if __name__ == "__main__":
    monitors = detect_monitors()
    print(f"Detected {len(monitors)} monitors:")
    for m in monitors:
        epson_tag = " (EPSON PJ)" if m.is_epson else ""
        primary_tag = " [PRIMARY]" if m.is_primary else ""
        print(f"  {m.name}: ({m.x}, {m.y}) {m.width}x{m.height}{primary_tag}{epson_tag}")

    epson = find_epson_monitor()
    if epson:
        print(f"\nEpson PJ: {epson.name} at ({epson.x}, {epson.y}) {epson.width}x{epson.height}")
        print(f"Window position: --window-position={epson.x},{epson.y}")
