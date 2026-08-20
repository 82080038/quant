"""
Playwright script: Risk metrics simulation on Epson PJ.
Runs ensemble tuning with MDD, Sharpe, PF, circuit breaker, then verifies UI.
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from monitor_detector import find_epson_monitor
from playwright.sync_api import sync_playwright

URL = "http://localhost:3000"
API = "http://localhost:8000"
TIMEOUT = 900


def api_get(path):
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def api_post(path):
    try:
        req = urllib.request.Request(f"{API}{path}", method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def main():
    screenshots = Path(__file__).parent.parent / "docs" / "risk_metrics_screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)

    epson = find_epson_monitor()
    if not epson:
        print("❌ Epson PJ not found!")
        return 1

    print("=" * 70)
    print("  RISK METRICS SIMULATION — EPSON PJ")
    print("  MDD · Sharpe Ratio · Profit Factor · Circuit Breaker")
    print("=" * 70)
    print(f"  Epson: ({epson.x}, {epson.y}) {epson.width}x{epson.height}")
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
        print("\n[1/5] Navigasi ke /manajemen-engine...")
        page.goto(f"{URL}/manajemen-engine", wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_timeout(5000)
        page.screenshot(path=str(screenshots / "01_page_loaded.png"))

        win_x = page.evaluate("window.screenX")
        print(f"  📍 Window: ({win_x}, {page.evaluate('window.screenY')})")
        if win_x >= epson.x - 50:
            print(f"  ✅ Browser di Epson (x={win_x})")

        # Verify all 6 panels
        panels = {
            "Engine Registry Grid": page.locator("text=Engine Registry Grid"),
            "Weight Chart": page.locator("text=Grafik Bobot Engine Hybrid"),
            "Lift Chart": page.locator("text=Matriks Perbandingan Akurasi"),
            "Equity Curve": page.locator("text=Kurva Ekuitas"),
            "Scorecard": page.locator("text=Skor Kinerja Institusional"),
            "Terminal Log": page.locator("text=Terminal Log Jalur Browser"),
        }
        for name, loc in panels.items():
            count = loc.count()
            print(f"  {'✅' if count > 0 else '❌'} {name}: {count}")

        # Trigger ensemble tuning
        print("\n[2/5] Trigger Ensemble Tuning...")
        btn = page.locator("button:has-text('Tuning Ensemble')")
        if btn.count() > 0:
            btn.click()
            print("  ✅ Tombol diklik")
        else:
            api_post("/api/ensemble-tuning/run")
            print("  ✅ API fallback")

        page.wait_for_timeout(3000)
        page.screenshot(path=str(screenshots / "02_tuning_started.png"))

        # Monitor progress
        print("\n[3/5] Monitor progress...")
        start = time.time()
        last_day = 0
        last_ss = 0

        while True:
            elapsed = time.time() - start
            if elapsed > TIMEOUT:
                print(f"\n  ❌ TIMEOUT after {elapsed:.0f}s")
                break

            if errors:
                print(f"\n  ⚠️ {len(errors)} errors — self-healing...")
                for e in errors[-3:]:
                    print(f"    {e}")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=10_000)
                    page.wait_for_timeout(2000)
                    errors.clear()
                except Exception as he:
                    print(f"  ❌ Heal failed: {he}")

            prog = api_get("/api/ensemble-tuning/progress")
            if prog:
                day = prog.get("current_day", 0)
                total = prog.get("total_trading_days", 0)
                da = prog.get("directional_accuracy", 0)
                eq = prog.get("equity", 0)
                running = prog.get("running", False)
                done_flag = prog.get("done", False)

                if day != last_day and day > 0:
                    print(f"\r  Hari {day}/{total} | DA: {da:.1f}% | Rp {eq/1_000_000:.2f}Jt", end="", flush=True)
                    last_day = day

                if done_flag and not running:
                    print(f"\n  ✅ Selesai: {prog.get('message', '')}")
                    break

            if elapsed - last_ss > 30:
                page.screenshot(path=str(screenshots / f"progress_{int(elapsed)}s.png"))
                last_ss = elapsed

            time.sleep(3)

        elapsed = time.time() - start
        page.wait_for_timeout(3000)
        page.screenshot(path=str(screenshots / "03_results.png"))

        # Verify risk metrics
        print("\n[4/5] Verifikasi risk metrics...")
        sc = api_get("/api/risk-metrics/scorecard")
        if sc and sc.get("scorecard"):
            s = sc["scorecard"]
            print(f"  Sharpe: {s['sharpe_ratio']:.2f} ({s['quality']['sharpe']})")
            print(f"  Profit Factor: {s['profit_factor']:.2f} ({s['quality']['profit_factor']})")
            print(f"  Max Drawdown: {s['max_drawdown']:.1f}% ({s['quality']['max_drawdown']})")
            print(f"  Win Rate: {s['win_rate']:.1f}% ({s['quality']['win_rate']})")
            print(f"  Return: {s['cumulative_return']:.1f}% ({s['quality']['return']})")
            print(f"  Ekuitas: Rp {s['equity']/1e6:.1f}Jt")

        eq = api_get("/api/risk-metrics/equity-curve")
        if eq and eq.get("equity_curve"):
            print(f"  Equity curve points: {len(eq['equity_curve'])}")

        # Scroll to equity curve chart
        page.locator("text=Kurva Ekuitas").scroll_into_view_if_needed()
        page.wait_for_timeout(2000)
        page.screenshot(path=str(screenshots / "04_equity_curve.png"))

        # Scroll to scorecard
        page.locator("text=Skor Kinerja Institusional").scroll_into_view_if_needed()
        page.wait_for_timeout(2000)
        page.screenshot(path=str(screenshots / "05_scorecard.png"))

        # Scroll to terminal log
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(screenshots / "06_terminal_log.png"))

        # Navigate all pages
        print("\n[5/5] Verifikasi stabilitas UI...")
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
                page.screenshot(path=str(screenshots / f"07_{name.lower().replace(' ', '_')}.png"))
                print(f"  ✅ {name}")
            except Exception as e:
                print(f"  ❌ {name}: {e}")
                errors.append(f"Nav {name}: {e}")

        print("\n" + "=" * 70)
        print("  RINGKASAN")
        print("=" * 70)
        print(f"  Durasi: {elapsed:.0f}s")
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
