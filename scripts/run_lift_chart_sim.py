"""
Playwright script: Launch Manajemen Engine page on Epson PJ with predictive lift chart.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from monitor_detector import find_epson_monitor, detect_monitors
from playwright.sync_api import sync_playwright

URL = "http://localhost:3000"
API = "http://localhost:8000"
TIMEOUT = 300


def api_get(path: str):
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def main():
    screenshots = Path(__file__).parent.parent / "docs" / "lift_chart_screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)

    epson = find_epson_monitor()
    if not epson:
        print("❌ Epson PJ not found!")
        return 1

    print("=" * 70)
    print("  PREDICTIVE LIFT CHART — EPSON PJ")
    print("=" * 70)
    print(f"  Epson: ({epson.x}, {epson.y}) {epson.width}x{epson.height}")
    print(f"  URL: {URL}/manajemen-engine")
    print("=" * 70)

    errors = []
    warnings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                f"--window-position={epson.x},{epson.y}",
                f"--window-size={epson.width},{epson.height}",
                "--start-maximized",
                "--no-sandbox",
                "--disable-gpu-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            viewport={"width": epson.width, "height": epson.height},
            locale="id-ID",
        )
        page = context.new_page()

        page.on("pageerror", lambda err: errors.append(f"PAGE ERROR: {err}"))
        page.on("console", lambda msg: (
            errors.append(f"CONSOLE ERROR: {msg.text}") if msg.type == "error"
            else warnings.append(f"WARN: {msg.text}") if msg.type == "warning"
            else None
        ))
        page.on("requestfailed", lambda req: errors.append(f"REQUEST FAILED: {req.url}"))

        # Navigate
        print("\n[1/4] Navigasi ke /manajemen-engine...")
        page.goto(f"{URL}/manajemen-engine", wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_timeout(5000)
        page.screenshot(path=str(screenshots / "01_page_loaded.png"))

        win_x = page.evaluate("window.screenX")
        print(f"  📍 Window: ({win_x}, {page.evaluate('window.screenY')})")
        if win_x >= epson.x - 50:
            print(f"  ✅ Browser di Epson (x={win_x})")
        else:
            print(f"  ⚠️ Browser tidak di Epson (x={win_x})")

        # Verify all 4 panels
        panels = {
            "Engine Registry Grid": page.locator("text=Engine Registry Grid"),
            "Weight Chart": page.locator("text=Grafik Bobot Engine Hybrid"),
            "Lift Chart": page.locator("text=Matriks Perbandingan Akurasi"),
            "Terminal Log": page.locator("text=Terminal Log Jalur Browser"),
        }
        for name, loc in panels.items():
            count = loc.count()
            print(f"  {'✅' if count > 0 else '❌'} {name}: {count}")

        # Scroll to lift chart
        print("\n[2/4] Scroll ke Accuracy Comparison Chart...")
        lift_section = page.locator("text=Matriks Perbandingan Akurasi")
        if lift_section.count() > 0:
            lift_section.scroll_into_view_if_needed()
            page.wait_for_timeout(3000)
            page.screenshot(path=str(screenshots / "02_lift_chart.png"))
            print("  ✅ Screenshot lift chart diambil")

        # Check lift report data
        print("\n[3/4] Verifikasi data predictive lift...")
        rep = api_get("/api/predictive-lift/report")
        if rep and rep.get("status") != "not_found":
            print(f"  DA A (Fibonacci): {rep.get('overall_a_da', 0)}%")
            print(f"  DA B (Hybrid): {rep.get('overall_b_da', 0)}%")
            print(f"  Delta: {rep.get('overall_delta', 0)}%")
            print(f"  Lift: {rep.get('overall_lift_pct', 0)}%")
            print(f"  Total Prediksi: {rep.get('summary', {}).get('total_predictions', 0)}")

            for ac in rep.get("asset_class_results", []):
                print(f"\n  ── {ac['asset_class']} ({ac['n_tickers']} ticker) ──")
                for h in ac.get("horizons", []):
                    delta_str = f"+{h['delta_da']:.1f}" if h['delta_da'] > 0 else f"{h['delta_da']:.1f}"
                    print(f"    {h['horizon']:<12} A: {h['condition_a_da']:5.1f}% → B: {h['condition_b_da']:5.1f}% | Δ: {delta_str:>6}% | F1: {h['condition_a_f1']:.3f}→{h['condition_b_f1']:.3f}")
        else:
            print("  ⚠️ Report tidak ditemukan")

        # Scroll down to see terminal
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(screenshots / "03_full_page.png"))

        # Navigate all pages for stability
        print("\n[4/4] Verifikasi stabilitas UI...")
        pages = [
            ("Dashboard", "/"),
            ("Manajemen Engine", "/manajemen-engine"),
            ("Prediksi", "/prediksi"),
            ("Settings", "/settings"),
        ]
        for name, path in pages:
            try:
                page.goto(f"{URL}{path}", wait_until="domcontentloaded", timeout=15_000)
                page.wait_for_timeout(2000)
                page.screenshot(path=str(screenshots / f"04_{name.lower().replace(' ', '_')}.png"))
                print(f"  ✅ {name}")
            except Exception as e:
                print(f"  ❌ {name}: {e}")
                errors.append(f"Nav {name}: {e}")

        print("\n" + "=" * 70)
        print("  RINGKASAN")
        print("=" * 70)
        print(f"  Console errors: {len(errors)}")
        print(f"  Warnings: {len(warnings)}")
        print(f"  Screenshots: {len(list(screenshots.glob('*.png')))} files")
        if errors:
            for e in errors[:5]:
                print(f"    ERROR: {e}")
        print("=" * 70)

        browser.close()

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
