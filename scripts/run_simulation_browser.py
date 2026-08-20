"""
Playwright Headed Simulation Driver — runs the 1-year temporal backtest
simulation through the browser UI on the Epson display.

This script:
1. Opens a Chromium browser on the Epson PJ display (HDMI-1-0)
2. Navigates to the /backtest page
3. Clicks "Run 1-Year Simulation" button
4. Monitors the live progress UI (progress bar, equity, regime, errors)
5. Takes periodic screenshots
6. Waits for completion and verifies results
7. Navigates through the dashboard to verify all widgets render

Usage:
    python scripts/run_simulation_browser.py [--url http://localhost:3000]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


EPSON_DISPLAY = {"x": 1339, "y": 0, "width": 1440, "height": 900}


def main():
    parser = argparse.ArgumentParser(description="Browser-driven temporal simulation")
    parser.add_argument("--url", default="http://localhost:3000", help="Frontend URL")
    parser.add_argument("--timeout", type=int, default=600, help="Max simulation time (seconds)")
    args = parser.parse_args()

    screenshots_dir = Path("docs/simulation_screenshots")
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                f"--window-position={EPSON_DISPLAY['x']},{EPSON_DISPLAY['y']}",
                f"--window-size={EPSON_DISPLAY['width']},{EPSON_DISPLAY['height']}",
                "--disable-gpu",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            viewport={"width": EPSON_DISPLAY["width"], "height": EPSON_DISPLAY["height"]},
        )
        page = context.new_page()

        # Capture console errors
        console_errors: list[str] = []
        page.on("console", lambda msg: console_errors.append(f"[{msg.type}] {msg.text}") if msg.type == "error" else None)

        print("=" * 70)
        print("  BROWSER-DRIVEN 1-YEAR TEMPORAL SIMULATION")
        print("=" * 70)
        print(f"  Target: {args.url}/backtest")
        print(f"  Display: HDMI-1-0 (Epson PJ) at {EPSON_DISPLAY['x']},{EPSON_DISPLAY['y']}")
        print(f"  Resolution: {EPSON_DISPLAY['width']}x{EPSON_DISPLAY['height']}")
        print(f"  Timeout: {args.timeout}s")
        print("=" * 70)

        # Step 1: Navigate to backtest page
        print("\n[1/6] Navigating to /backtest...")
        page.goto(f"{args.url}/backtest", wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector("main", timeout=15_000)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(screenshots_dir / "01_backtest_page_loaded.png"))
        print(f"  ✅ Backtest page loaded — URL: {page.url}")

        # Step 2: Click "Run 1-Year Simulation" button
        print("\n[2/6] Clicking 'Jalankan Simulasi 1 Tahun' button...")
        run_button = page.locator("button:has-text('Jalankan Simulasi 1 Tahun')")
        run_button.wait_for(timeout=10_000)
        run_button.click()
        print("  ✅ Simulasi dimulai via browser UI")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(screenshots_dir / "02_simulation_started.png"))

        # Step 3: Monitor progress
        print("\n[3/6] Monitoring simulation progress...")
        start_time = time.time()
        last_day = 0
        screenshot_interval = 30  # seconds between screenshots
        last_screenshot = 0

        while True:
            elapsed = time.time() - start_time
            if elapsed > args.timeout:
                print(f"\n  ❌ TIMEOUT after {elapsed:.0f}s")
                break

            # Read progress from the page
            try:
                progress_elements = page.get_by_text(re.compile(r"Hari \d+ / \d+ hari bursa")).all_inner_texts()
                if progress_elements:
                    print(f"\r  {progress_elements[0]}", end="", flush=True)
            except Exception:
                pass

            # Check if done
            done_badge = page.locator("text='Simulasi Selesai'")
            if done_badge.count() > 0:
                print("\n  ✅ Simulasi Selesai badge detected")
                break

            # Check for "Menyimulasikan..." button state
            simulating = page.locator("button:has-text('Menyimulasikan...')")
            if simulating.count() == 0:
                # Button reverted — either done or error
                done_badge = page.locator("text='Simulasi Selesai'")
                if done_badge.count() > 0:
                    print("\n  ✅ Simulasi Selesai")
                    break
                else:
                    # Check for error message
                    try:
                        msg_elements = page.get_by_text(re.compile(r"Error|error|Error:"), exact=False).all_inner_texts()
                        if msg_elements:
                            print(f"\n  ⚠️ Possible error: {msg_elements[0][:100]}")
                    except Exception:
                        pass
                    # Also check via API if simulation is still running
                    try:
                        import urllib.request as _urllib
                        with _urllib.urlopen("http://localhost:8000/api/temporal-backtest/progress", timeout=5) as resp:
                            import json as _json
                            prog = _json.loads(resp.read())
                            if prog.get("running"):
                                print(f"\n  ℹ️ Simulation still running via API (day {prog.get('current_day')}/{prog.get('total_trading_days')})")
                                # Continue monitoring
                                simulating = True
                            elif prog.get("done"):
                                print("\n  ✅ Simulation done (via API)")
                                break
                    except Exception:
                        pass
                    if not simulating:
                        break

            # Periodic screenshot
            if elapsed - last_screenshot > screenshot_interval:
                page.screenshot(path=str(screenshots_dir / f"progress_{int(elapsed)}s.png"))
                last_screenshot = elapsed

            time.sleep(3)

        elapsed = time.time() - start_time
        print(f"\n  Simulation finished in {elapsed:.0f}s")

        # Final screenshot
        page.screenshot(path=str(screenshots_dir / "03_simulation_complete.png"))

        # Step 4: Verify results are displayed
        print("\n[4/6] Verifying simulation results on page...")
        page.wait_for_timeout(3000)

        # Check for equity curve chart
        equity_chart = page.locator(".recharts-surface")
        if equity_chart.count() > 0:
            print("  ✅ Equity curve chart rendered")
        else:
            print("  ⚠️ Equity curve chart not found")

        # Check for trading days number
        body_text = page.inner_text("body")
        if "124" in body_text or "Trading Days" in body_text:
            print("  ✅ Trading days metric visible")
        else:
            print("  ⚠️ Trading days metric not found")

        # Check for look-ahead violations
        if "0 violations" in body_text or "Look-ahead" in body_text:
            print("  ✅ Look-ahead violations metric visible")
        else:
            print("  ⚠️ Look-ahead metric not found")

        page.screenshot(path=str(screenshots_dir / "04_results_verified.png"))

        # Step 5: Navigate through dashboard pages
        print("\n[5/6] Navigating dashboard pages to verify UI stability...")

        pages_to_visit = [
            ("/", "Dashboard"),
            ("/signals", "Signals"),
            ("/portfolio", "Portfolio"),
            ("/backtest", "Backtest (final)"),
            ("/settings", "Settings"),
        ]

        for path, name in pages_to_visit:
            try:
                page.goto(f"{args.url}{path}", wait_until="domcontentloaded", timeout=15_000)
                page.wait_for_selector("main", timeout=10_000)
                page.wait_for_timeout(1500)
                page.screenshot(path=str(screenshots_dir / f"05_{name.lower().replace(' ', '_').replace('(', '').replace(')', '')}.png"))
                print(f"  ✅ {name} — {page.url}")
            except PlaywrightTimeout:
                print(f"  ⚠️ {name} — timeout")

        # Step 6: Report console errors
        print("\n[6/6] Console error check...")
        if console_errors:
            print(f"  ⚠️ {len(console_errors)} console errors detected:")
            for err in console_errors[:10]:
                print(f"    {err[:120]}")
        else:
            print("  ✅ Zero console errors")

        # Summary
        print("\n" + "=" * 70)
        print("  BROWSER SIMULATION SUMMARY")
        print("=" * 70)
        print(f"  Duration:       {elapsed:.0f}s")
        print(f"  Screenshots:    {len(list(screenshots_dir.glob('*.png')))} files in docs/simulation_screenshots/")
        print(f"  Console errors: {len(console_errors)}")
        print("=" * 70)

        browser.close()


if __name__ == "__main__":
    main()
