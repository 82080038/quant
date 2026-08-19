#!/usr/bin/env python3
"""Detect all connected monitors and identify the Epson display.

Uses xrandr --verbose to parse EDID data for monitor names, plus
screeninfo as a cross-platform fallback. Outputs JSON with monitor
metadata including position coordinates for Playwright window targeting.

Usage:
    python scripts/monitor_detect.py
    python scripts/monitor_detect.py --json   # machine-readable output
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict


@dataclass
class MonitorInfo:
    name: str
    output: str
    resolution: str
    x: int
    y: int
    width: int
    height: int
    is_primary: bool
    is_epson: bool


def _parse_edid_name(edid_hex: str) -> str:
    """Extract the monitor name from EDID hex data.

    EDID descriptor blocks at offsets 0x36 and 0x48 contain text
    descriptors. The descriptor type 0xFC holds the monitor name.
    """
    try:
        clean_hex = re.sub(r"\s", "", edid_hex)[:512]
        raw = bytes.fromhex(clean_hex)
    except ValueError:
        return "Unknown"

    # EDID 1.4 descriptor blocks (18 bytes each) at offsets 54, 72, 90, 108:
    #   Byte 0-2: 0x00, 0x00, 0x00 (flag for descriptor; non-zero = detailed timing)
    #   Byte 3:   Tag (0xFC=monitor name, 0xFD=range limits, 0xFE=ASCII text, 0xFF=serial)
    #   Byte 4:   0x00
    #   Bytes 5-17: Text data (13 bytes, padded with 0x20, terminated with 0x0A)
    for offset in (54, 72, 90, 108):
        if offset + 18 > len(raw):
            continue
        if raw[offset] == 0x00 and raw[offset + 1] == 0x00 and raw[offset + 3] == 0xFC:
            name_bytes = raw[offset + 5 : offset + 18]
            name = name_bytes.split(b"\n")[0].rstrip(b"\x00 ").decode("ascii", errors="replace")
            return name.strip() if name.strip() else "Unknown"
    return "Unknown"


def detect_monitors_xrandr() -> list[MonitorInfo]:
    """Detect monitors using xrandr --verbose (Linux/X11)."""
    try:
        result = subprocess.run(
            ["xrandr", "--verbose"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    output = result.stdout
    monitors: list[MonitorInfo] = []

    # Split by output sections (HDMI-0, DVI-D-1-0, etc.)
    # Pattern: output_name connected [primary] WxH+X+Y
    output_pattern = re.compile(
        r"^(\S+)\s+connected\s+(primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)",
        re.MULTILINE,
    )

    # Find all EDID blocks and their associated outputs
    # Split the output into sections per display
    sections = re.split(r"^(\S+)\s+connected", output, flags=re.MULTILINE)

    # sections[0] is preamble, then alternating: output_name, section_body
    for i in range(1, len(sections), 2):
        output_name = sections[i]
        body = sections[i + 1] if i + 1 < len(sections) else ""

        # Parse geometry from the connected line (first line of body)
        geom_match = re.match(
            r"\s+(primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)", body
        )
        if not geom_match:
            continue

        is_primary = bool(geom_match.group(1))
        width = int(geom_match.group(2))
        height = int(geom_match.group(3))
        x = int(geom_match.group(4))
        y = int(geom_match.group(5))

        # Extract EDID hex block
        edid_match = re.search(r"EDID:\s*\n((?:\s+[0-9a-fA-F]+\n?)+)", body)
        monitor_name = "Unknown"
        if edid_match:
            edid_hex = edid_match.group(1)
            monitor_name = _parse_edid_name(edid_hex)

        is_epson = "EPSON" in monitor_name.upper()

        monitors.append(
            MonitorInfo(
                name=monitor_name,
                output=output_name,
                resolution=f"{width}x{height}",
                x=x,
                y=y,
                width=width,
                height=height,
                is_primary=is_primary,
                is_epson=is_epson,
            )
        )

    return monitors


def detect_monitors_screeninfo() -> list[MonitorInfo]:
    """Fallback detection using screeninfo library (cross-platform)."""
    try:
        from screeninfo import get_monitors
    except ImportError:
        return []

    monitors: list[MonitorInfo] = []
    for i, m in enumerate(get_monitors()):
        monitors.append(
            MonitorInfo(
                name=f"Monitor-{i}",
                output=f"screeninfo-{i}",
                resolution=f"{m.width}x{m.height}",
                x=m.x,
                y=m.y,
                width=m.width,
                height=m.height,
                is_primary=(i == 0),
                is_epson=False,
            )
        )
    return monitors


def get_epson_monitor(monitors: list[MonitorInfo]) -> MonitorInfo | None:
    """Find the Epson monitor from the list, or None if not found."""
    for m in monitors:
        if m.is_epson:
            return m
    return None


def prompt_fallback(monitors: list[MonitorInfo]) -> MonitorInfo | None:
    """Interactive fallback: ask user to pick a monitor if Epson not found."""
    print("\n⚠️  WARNING: Epson display not detected!\n")
    print("Available monitors:")
    for i, m in enumerate(monitors):
        primary_tag = " [PRIMARY]" if m.is_primary else ""
        print(f"  [{i}] {m.output} — {m.name} ({m.resolution}) at +{m.x}+{m.y}{primary_tag}")

    if not monitors:
        print("  (no monitors detected)")
        return None

    try:
        choice = input("\nSelect monitor index to use (or press Enter to cancel): ").strip()
        if choice == "":
            return None
        idx = int(choice)
        if 0 <= idx < len(monitors):
            return monitors[idx]
    except (ValueError, IndexError):
        pass

    print("Invalid selection. Aborting.")
    return None


def main() -> int:
    use_json = "--json" in sys.argv

    # Try xrandr first (gives us EDID names), then screeninfo fallback
    monitors = detect_monitors_xrandr()
    if not monitors:
        monitors = detect_monitors_screeninfo()

    if not monitors:
        print("ERROR: No monitors detected.", file=sys.stderr)
        return 1

    epson = get_epson_monitor(monitors)

    if use_json:
        print(json.dumps({
            "monitors": [asdict(m) for m in monitors],
            "epson": asdict(epson) if epson else None,
        }, indent=2))
        return 0

    # Human-readable output
    print("=" * 60)
    print("  MONITOR DETECTION REPORT")
    print("=" * 60)
    print(f"  Total monitors detected: {len(monitors)}\n")

    for m in monitors:
        tags = []
        if m.is_primary:
            tags.append("PRIMARY")
        if m.is_epson:
            tags.append("★ EPSON TARGET")
        tag_str = f"  [{' '.join(tags)}]" if tags else ""

        print(f"  Output:     {m.output}")
        print(f"  Name:       {m.name}")
        print(f"  Resolution: {m.resolution}")
        print(f"  Position:   X={m.x}, Y={m.y}{tag_str}")
        print(f"  Size:       {m.width}x{m.height}")
        print("-" * 60)

    if epson:
        print(f"\n  ✅ Epson display FOUND: {epson.output} ({epson.name})")
        print(f"     Coordinates: X={epson.x}, Y={epson.y}")
        print(f"     Resolution:  {epson.resolution}")
        print(f"     Window-position arg: --window-position={epson.x},{epson.y}")
    else:
        print("\n  ❌ Epson display NOT found.")
        if "--no-prompt" not in sys.argv:
            epson = prompt_fallback(monitors)
            if epson:
                print(f"\n  → Fallback selected: {epson.output} ({epson.name})")
                print(f"     Coordinates: X={epson.x}, Y={epson.y}")
            else:
                print("  → No fallback selected. Exiting.")
                return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
