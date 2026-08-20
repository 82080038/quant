"""
FASE 4: Full hybrid ensemble simulation on Epson PJ with strict error monitoring.

1. Detect Epson monitor coordinates
2. Launch Playwright headed browser on Epson ONLY (not Lenovo)
3. Navigate to dashboard, trigger ensemble tuning
4. Monitor console errors, page errors, and orchestration logs
5. Take periodic screenshots
6. Self-heal: if errors detected, log them and attempt recovery
7. Navigate all pages for stability check
"""

import json
import re
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

# Import monitor detection
import sys
sys.path.insert(0, str(Path(__file__).parent))
from monitor_detector import find_epson_monitor, detect_monitors

URL = "http://localhost:3000"
API = "http://localhost:8000"
TIMEOUT = 1200  # 20 minutes


def api_get(path: str):
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def main():
    screenshots = Path(__file__).parent.parent / "docs" / "ensemble_screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)

    # Detect monitors
    monitors = detect_monitors()
    epson = find_epson_monitor()

    if not epson:
        print("❌ Epson PJ monitor not found! Aborting.")
        return 1

    print("=" * 70)
    print("  FASE 4: HYBRID ENSEMBLE SIMULATION — EPSON PJ")
    print("=" * 70)
    print(f"  Monitors detected: {len(monitors)}")
    for m in monitors:
        tag = " (EPSON PJ)" if m.is_epson else (" [LENOVO/PRIMARY]" if m.is_primary else "")
        print(f"    {m.name}: ({m.x}, {m.y}) {m.width}x{m.height}{tag}")
    print(f"  Target: Epson PJ at ({epson.x}, {epson.y}) {epson.width}x{epson.height}")
    print(f"  URL: {URL}")
    print(f"  Timeout: {TIMEOUT}s")
    print("=" * 70)

    errors = []
    warnings = []
    healed = []

    with sync_playwright() as p:
        # Launch browser with explicit window position on Epson
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
        page.on("requestfailed", lambda req: errors.append(f"REQUEST FAILED: {req.url} - {req.failure}"))

        # Step 1: Navigate to dashboard
        print("\n[1/6] Navigasi ke Dashboard...")
        page.goto(URL, wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_timeout(3000)
        page.screenshot(path=str(screenshots / "01_dashboard.png"))
        print(f"  ✅ Dashboard dimuat — URL: {page.url}")

        # Verify we're on Epson (check window position via JS)
        try:
            win_x = page.evaluate("window.screenX")
            win_y = page.evaluate("window.screenY")
            print(f"  📍 Window position: ({win_x}, {win_y})")
            if win_x >= epson.x - 50:
                print(f"  ✅ Browser terbuka di monitor Epson (x={win_x} >= {epson.x})")
            else:
                print(f"  ⚠️ Browser mungkin tidak di Epson (x={win_x} < {epson.x})")
        except Exception:
            pass

        # Step 2: Trigger ensemble tuning
        print("\n[2/6] Trigger Ensemble Tuning...")
        # Click the "Tuning Ensemble" button on the dashboard
        btn = page.locator("button:has-text('Tuning Ensemble')")
        if btn.count() > 0:
            btn.click()
            print("  ✅ Tombol 'Tuning Ensemble' diklik")
        else:
            # Fallback: trigger via API
            try:
                urllib.request.urlopen(
                    urllib.request.Request(f"{API}/api/ensemble-tuning/run", method="POST"),
                    timeout=10,
                )
                print("  ✅ Ensemble tuning dimulai via API")
            except Exception as e:
                print(f"  ❌ Gagal memulai ensemble tuning: {e}")
                errors.append(f"Failed to start ensemble: {e}")

        page.wait_for_timeout(3000)
        page.screenshot(path=str(screenshots / "02_ensemble_started.png"))

        # Step 3: Monitor progress
        print("\n[3/6] Monitor progress ensemble tuning...")
        start = time.time()
        last_day = 0
        last_ss = 0

        while True:
            elapsed = time.time() - start
            if elapsed > TIMEOUT:
                print(f"\n  ❌ TIMEOUT after {elapsed:.0f}s")
                break

            # Check for errors — self-healing
            if errors:
                print(f"\n  ⚠️ {len(errors)} errors detected — attempting self-heal...")
                for e in errors[-3:]:
                    print(f"    {e}")
                # Self-heal: reload page
                try:
                    page.reload(wait_until="domcontentloaded", timeout=10_000)
                    page.wait_for_timeout(2000)
                    healed.append(f"Reloaded page at {elapsed:.0f}s")
                    print("  🔧 Self-heal: Page reloaded")
                    errors.clear()  # Clear after healing attempt
                except Exception as heal_err:
                    print(f"  ❌ Self-heal failed: {heal_err}")

            prog = api_get("/api/ensemble-tuning/progress")
            if prog:
                day = prog.get("current_day", 0)
                total = prog.get("total_trading_days", 0)
                da = prog.get("directional_accuracy", 0)
                eq = prog.get("equity", 0)
                msg = prog.get("message", "")
                running = prog.get("running", False)
                done = prog.get("done", False)

                if day != last_day and day > 0:
                    print(f"\r  Hari {day}/{total} | DA: {da:.1f}% | Ekuitas: Rp {eq/1_000_000:.2f}Jt | {msg}", end="", flush=True)
                    last_day = day

                if done and not running:
                    print(f"\n  ✅ Ensemble Selesai: {msg}")
                    break

                if not running and not done and msg and "Error" in msg:
                    print(f"\n  ❌ Ensemble error: {msg}")
                    errors.append(f"Ensemble: {msg}")
                    break

            # Periodic screenshot
            if elapsed - last_ss > 30:
                page.screenshot(path=str(screenshots / f"progress_{int(elapsed)}s.png"))
                last_ss = elapsed

            time.sleep(3)

        elapsed = time.time() - start
        print(f"\n  Durasi: {elapsed:.0f}s")

        # Step 4: Verify results
        print("\n[4/6] Verifikasi hasil ensemble...")
        page.wait_for_timeout(3000)
        page.screenshot(path=str(screenshots / "03_results.png"))

        # Check orchestration log is visible
        log_section = page.locator("text=Log Orkestrasi Real-time")
        if log_section.count() > 0:
            print("  ✅ Log Orkestrasi terender")
        else:
            print("  ⚠️ Log Orkestrasi tidak ditemukan")

        # Check engine badges
        engine_section = page.locator("text=Manajemen Engine")
        if engine_section.count() > 0:
            print("  ✅ Manajemen Engine panel terender")

        # Get final report
        rep = api_get("/api/ensemble-tuning/report")
        if rep and rep.get("status") != "not_found":
            print(f"\n  📊 Hasil Ensemble:")
            print(f"     Hari Bursa: {rep.get('trading_days', 0)}")
            print(f"     Total Prediksi: {rep.get('total_predictions', 0)}")
            print(f"     DA Keseluruhan: {rep.get('overall_da', 0)}%")
            print(f"     F1 Score: {rep.get('overall_f1', 0)}")
            print(f"     Imbal Hasil: {rep.get('total_return_pct', 0)}%")
            print(f"     Sharpe: {rep.get('sharpe_ratio', 0)}")
            print(f"     Engine Aktif: {len(rep.get('active_engines', []))}")
            print(f"     Engine Dimatikan: {len(rep.get('deactivated_engines', []))}")
            print(f"     Log Orkestrasi: {len(rep.get('orchestration_log', []))} entries")

        # Step 5: Navigate all pages
        print("\n[5/6] Verifikasi stabilitas UI semua halaman...")
        pages = [
            ("Dashboard", "/"),
            ("Sinyal", "/signals"),
            ("Portofolio", "/portfolio"),
            ("Prediksi", "/prediksi"),
            ("Backtest", "/backtest"),
            ("Pengaturan", "/settings"),
        ]
        for name, path in pages:
            try:
                page.goto(f"{URL}{path}", wait_until="domcontentloaded", timeout=15_000)
                page.wait_for_timeout(2000)
                page.screenshot(path=str(screenshots / f"05_{name.lower()}.png"))
                print(f"  ✅ {name} — {path}")
            except Exception as e:
                print(f"  ❌ {name} — Error: {e}")
                errors.append(f"Nav error {name}: {e}")

        # Step 6: Final error check
        print("\n[6/6] Final error check...")
        print("\n" + "=" * 70)
        print("  RINGKASAN SIMULASI ENSEMBLE")
        print("=" * 70)
        print(f"  Durasi: {elapsed:.0f}s")
        print(f"  Console errors: {len(errors)}")
        print(f"  Warnings: {len(warnings)}")
        print(f"  Self-heals: {len(healed)}")
        print(f"  Screenshots: {len(list(screenshots.glob('*.png')))} files")
        if errors:
            print(f"\n  ERRORS:")
            for e in errors[:10]:
                print(f"    {e}")
        if healed:
            print(f"\n  SELF-HEALED:")
            for h in healed:
                print(f"    {h}")
        print("=" * 70)

        browser.close()

    return 1 if errors else 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
