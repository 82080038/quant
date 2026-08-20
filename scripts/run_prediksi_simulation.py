"""
Playwright script: Run prediction simulation 1-year on Epson PJ browser.

1. Navigate to /prediksi page
2. Click "Jalankan Simulasi Prediksi 1 Tahun"
3. Monitor progress via API + page
4. Take periodic screenshots
5. Verify results when done
6. Navigate all pages for stability check
"""

import json
import re
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:3000"
API = "http://localhost:8000"
WIDTH = 1440
HEIGHT = 900
TIMEOUT = 900  # 15 minutes


def api_get(path: str):
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def main():
    screenshots = Path(__file__).parent.parent / "docs" / "prediksi_screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)

    errors = []
    warnings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--display=:1", "--no-sandbox", "--disable-gpu-sandbox"],
        )
        context = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            locale="id-ID",
        )
        page = context.new_page()

        page.on("pageerror", lambda err: errors.append(f"PAGE ERROR: {err}"))
        page.on("console", lambda msg: (
            errors.append(f"CONSOLE ERROR: {msg.text}") if msg.type == "error"
            else warnings.append(f"WARN: {msg.text}") if msg.type == "warning"
            else None
        ))

        print("=" * 70)
        print("  SIMULASI PREDIKSI 1 TAHUN — PLAYWRIGHT HEADED EPSON PJ")
        print("=" * 70)
        print(f"  URL: {URL}/prediksi")
        print(f"  Display: HDMI-1-0 ({WIDTH}x{HEIGHT})")
        print(f"  Timeout: {TIMEOUT}s")
        print("=" * 70)

        # Step 1: Navigate to /prediksi
        print("\n[1/5] Navigasi ke halaman Prediksi...")
        page.goto(f"{URL}/prediksi", wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_timeout(3000)
        page.screenshot(path=str(screenshots / "01_prediksi_page.png"))
        print("  ✅ Halaman Prediksi dimuat")

        # Step 2: Click run button
        print("\n[2/5] Klik tombol 'Jalankan Simulasi Prediksi 1 Tahun'...")
        btn = page.locator("button:has-text('Jalankan Simulasi Prediksi 1 Tahun')")
        btn.wait_for(timeout=10_000)
        btn.click()
        print("  ✅ Tombol diklik, simulasi dimulai")
        page.wait_for_timeout(3000)
        page.screenshot(path=str(screenshots / "02_sim_started.png"))

        # Step 3: Monitor progress
        print("\n[3/5] Monitor progress simulasi...")
        start = time.time()
        last_day = 0
        last_ss = 0

        while True:
            elapsed = time.time() - start
            if elapsed > TIMEOUT:
                print(f"\n  ❌ TIMEOUT after {elapsed:.0f}s")
                break

            if errors:
                print(f"\n  ❌ ERROR DETECTED — STOPPING")
                for e in errors[:5]:
                    print(f"    {e}")
                page.screenshot(path=str(screenshots / "error.png"))
                break

            prog = api_get("/api/prediction-sim/progress")
            if prog:
                day = prog.get("current_day", 0)
                total = prog.get("total_trading_days", 0)
                da = prog.get("directional_accuracy", 0)
                eq = prog.get("equity", 0)
                msg = prog.get("message", "")
                running = prog.get("running", False)
                done = prog.get("done", False)

                if day != last_day:
                    print(f"\r  Hari {day}/{total} | DA: {da:.1f}% | Ekuitas: Rp {eq/1_000_000:.2f}Jt | {msg}", end="", flush=True)
                    last_day = day

                if done and not running:
                    print(f"\n  ✅ Simulasi Selesai: {msg}")
                    break

                if not running and not done and msg and "Error" in msg:
                    print(f"\n  ❌ Simulasi error: {msg}")
                    break

            # Periodic screenshot
            if elapsed - last_ss > 30:
                page.screenshot(path=str(screenshots / f"progress_{int(elapsed)}s.png"))
                last_ss = elapsed

            time.sleep(3)

        elapsed = time.time() - start
        print(f"\n  Durasi simulasi: {elapsed:.0f}s")

        # Step 4: Verify results
        print("\n[4/5] Verifikasi hasil simulasi...")
        page.wait_for_timeout(3000)
        page.screenshot(path=str(screenshots / "03_results.png"))

        # Check for equity curve
        eq_chart = page.locator("text=Kurva Ekuitas Prediksi")
        if eq_chart.count() > 0:
            print("  ✅ Kurva ekuitas terender")
        else:
            print("  ⚠️ Kurva ekuitas tidak ditemukan")

        # Check engine scores
        eng_section = page.locator("text=Skor Engine")
        if eng_section.count() > 0:
            print("  ✅ Tabel skor engine terender")

        # Check projections
        proj_section = page.locator("text=Proyeksi Multi-Horizon")
        if proj_section.count() > 0:
            print("  ✅ Proyeksi multi-horizon terender")

        # Get final report via API
        rep = api_get("/api/prediction-sim/report")
        if rep and rep.get("status") != "not_found":
            print(f"\n  📊 Hasil Akhir:")
            print(f"     Hari Bursa: {rep.get('trading_days', 0)}")
            print(f"     Total Prediksi: {rep.get('total_predictions', 0)}")
            print(f"     DA Keseluruhan: {rep.get('overall_da', 0):.1f}%")
            print(f"     MAPE: {rep.get('overall_mape', 0):.1f}%")
            print(f"     F1 Score: {rep.get('overall_f1', 0):.3f}")
            print(f"     Imbal Hasil: {rep.get('total_return_pct', 0):.2f}%")
            print(f"     Sharpe: {rep.get('sharpe_ratio', 0):.3f}")
            print(f"     Look-ahead: {rep.get('lookahead_violations', 0)}")

        # Step 5: Navigate all pages
        print("\n[5/5] Verifikasi stabilitas UI semua halaman...")
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

        # Final error check
        print("\n" + "=" * 70)
        print("  RINGKASAN SIMULASI PREDIKSI")
        print("=" * 70)
        print(f"  Durasi: {elapsed:.0f}s")
        print(f"  Console errors: {len(errors)}")
        print(f"  Warnings: {len(warnings)}")
        print(f"  Screenshots: {len(list(screenshots.glob('*.png')))} files")
        if errors:
            print(f"\n  ERRORS:")
            for e in errors[:10]:
                print(f"    {e}")
        print("=" * 70)

        browser.close()

    return 1 if errors else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
