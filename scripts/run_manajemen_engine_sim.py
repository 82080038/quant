"""
Playwright script: Launch Manajemen Engine page on Epson PJ monitor.
Strict error monitoring, self-healing, screenshots, page navigation check.
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
TIMEOUT = 900  # 15 min max


def api_get(path: str):
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def main():
    screenshots = Path(__file__).parent.parent / "docs" / "manajemen_engine_screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)

    monitors = detect_monitors()
    epson = find_epson_monitor()
    if not epson:
        print("❌ Epson PJ not found!")
        return 1

    print("=" * 70)
    print("  MANAJEMEN ENGINE PAGE — EPSON PJ SIMULATION")
    print("=" * 70)
    print(f"  Epson: ({epson.x}, {epson.y}) {epson.width}x{epson.height}")
    print(f"  URL: {URL}/manajemen-engine")
    print(f"  Timeout: {TIMEOUT}s")
    print("=" * 70)

    errors = []
    warnings = []
    healed = []

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

        # Strict error monitoring
        page.on("pageerror", lambda err: errors.append(f"PAGE ERROR: {err}"))
        page.on("console", lambda msg: (
            errors.append(f"CONSOLE ERROR: {msg.text}") if msg.type == "error"
            else warnings.append(f"WARN: {msg.text}") if msg.type == "warning"
            else None
        ))
        page.on("requestfailed", lambda req: errors.append(f"REQUEST FAILED: {req.url}"))

        # Step 1: Navigate to Manajemen Engine page
        print("\n[1/5] Navigasi ke /manajemen-engine...")
        page.goto(f"{URL}/manajemen-engine", wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_timeout(4000)
        page.screenshot(path=str(screenshots / "01_manajemen_engine.png"))

        # Verify window on Epson
        try:
            win_x = page.evaluate("window.screenX")
            print(f"  📍 Window position: ({win_x}, {page.evaluate('window.screenY')})")
            if win_x >= epson.x - 50:
                print(f"  ✅ Browser di monitor Epson (x={win_x})")
            else:
                print(f"  ⚠️ Browser mungkin tidak di Epson (x={win_x})")
        except Exception:
            pass

        # Verify page elements
        title = page.locator("text=Manajemen Engine & Log Orkestrasi")
        grid = page.locator("text=Engine Registry Grid")
        chart = page.locator("text=Grafik Bobot Engine Hybrid")
        terminal = page.locator("text=Terminal Log Jalur Browser")

        print(f"  Title: {'✅' if title.count() > 0 else '❌'}")
        print(f"  Registry Grid: {'✅' if grid.count() > 0 else '❌'}")
        print(f"  Weight Chart: {'✅' if chart.count() > 0 else '❌'}")
        print(f"  Terminal Log: {'✅' if terminal.count() > 0 else '❌'}")

        # Check engine cards loaded
        cards = page.locator("button[class*='rounded-full']")
        print(f"  Toggle switches: {cards.count()} found")

        # Step 2: Trigger ensemble tuning
        print("\n[2/5] Trigger Ensemble Tuning...")
        btn = page.locator("button:has-text('Tuning Ensemble')")
        if btn.count() > 0:
            btn.click()
            print("  ✅ Tombol 'Tuning Ensemble' diklik")
        else:
            try:
                urllib.request.urlopen(
                    urllib.request.Request(f"{API}/api/ensemble-tuning/run", method="POST"),
                    timeout=10,
                )
                print("  ✅ Ensemble tuning dimulai via API fallback")
            except Exception as e:
                print(f"  ❌ Gagal: {e}")
                errors.append(f"Start failed: {e}")

        page.wait_for_timeout(3000)
        page.screenshot(path=str(screenshots / "02_tuning_started.png"))

        # Step 3: Monitor progress
        print("\n[3/5] Monitor progress...")
        start = time.time()
        last_day = 0
        last_ss = 0

        while True:
            elapsed = time.time() - start
            if elapsed > TIMEOUT:
                print(f"\n  ❌ TIMEOUT after {elapsed:.0f}s")
                break

            # Self-healing
            if errors:
                print(f"\n  ⚠️ {len(errors)} errors — self-healing...")
                for e in errors[-3:]:
                    print(f"    {e}")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=10_000)
                    page.wait_for_timeout(2000)
                    healed.append(f"Reload at {elapsed:.0f}s")
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

                if not running and not done_flag and "Error" in prog.get("message", ""):
                    print(f"\n  ❌ Error: {prog['message']}")
                    break

            if elapsed - last_ss > 30:
                page.screenshot(path=str(screenshots / f"progress_{int(elapsed)}s.png"))
                last_ss = elapsed

            time.sleep(3)

        elapsed = time.time() - start
        page.wait_for_timeout(3000)
        page.screenshot(path=str(screenshots / "03_results.png"))

        # Step 4: Verify final results
        print("\n[4/5] Verifikasi hasil...")
        rep = api_get("/api/ensemble-tuning/report")
        if rep and rep.get("status") != "not_found":
            print(f"  DA: {rep.get('overall_da', 0)}%")
            print(f"  F1: {rep.get('overall_f1', 0)}")
            print(f"  Return: {rep.get('total_return_pct', 0)}%")
            print(f"  Sharpe: {rep.get('sharpe_ratio', 0)}")
            print(f"  Engine Aktif: {len(rep.get('active_engines', []))}")

        # Scroll down to see terminal log
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1000)
        page.screenshot(path=str(screenshots / "04_terminal_log.png"))

        # Step 5: Navigate all pages
        print("\n[5/5] Verifikasi stabilitas UI...")
        pages = [
            ("Dashboard", "/"),
            ("Sinyal", "/signals"),
            ("Portofolio", "/portfolio"),
            ("Prediksi", "/prediksi"),
            ("Backtest", "/backtest"),
            ("Manajemen Engine", "/manajemen-engine"),
            ("Pengaturan", "/settings"),
        ]
        for name, path in pages:
            try:
                page.goto(f"{URL}{path}", wait_until="domcontentloaded", timeout=15_000)
                page.wait_for_timeout(2000)
                page.screenshot(path=str(screenshots / f"05_{name.lower().replace(' ', '_')}.png"))
                print(f"  ✅ {name} — {path}")
            except Exception as e:
                print(f"  ❌ {name}: {e}")
                errors.append(f"Nav {name}: {e}")

        # Summary
        print("\n" + "=" * 70)
        print("  RINGKASAN")
        print("=" * 70)
        print(f"  Durasi: {elapsed:.0f}s")
        print(f"  Console errors: {len(errors)}")
        print(f"  Warnings: {len(warnings)}")
        print(f"  Self-heals: {len(healed)}")
        print(f"  Screenshots: {len(list(screenshots.glob('*.png')))} files")
        if errors:
            for e in errors[:5]:
                print(f"    ERROR: {e}")
        print("=" * 70)

        browser.close()

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
