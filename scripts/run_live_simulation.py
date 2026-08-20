"""
Live Multi-Horizon Simulation — Playwright Headed on Epson display.

Script ini:
1. Buka dashboard di browser pada Epson PJ (HDMI-1-0, 1440x900)
2. Monitor console errors dan page errors secara ketat
3. Klik "Evaluasi Ulang" untuk menjalankan evaluasi engine
4. Monitor progress hingga selesai
5. Verifikasi proyeksi multi-horizon ditampilkan
6. Navigasi semua halaman untuk verifikasi UI stability
"""

import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DISPLAY = "HDMI-1-0"
WIDTH = 1440
HEIGHT = 900
URL = "http://localhost:3000"
TIMEOUT = 120  # seconds


def main():
    screenshots_dir = Path(__file__).parent.parent / "docs" / "simulation_screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    warnings: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                f"--display=:1",
                "--no-sandbox",
                "--disable-gpu-sandbox",
            ],
        )
        context = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            locale="id-ID",
        )
        page = context.new_page()

        # Strict error monitoring
        page.on("pageerror", lambda err: errors.append(f"PAGE ERROR: {err}"))
        page.on("console", lambda msg: (
            errors.append(f"CONSOLE ERROR: {msg.text}") if msg.type == "error"
            else warnings.append(f"CONSOLE WARN: {msg.text}") if msg.type == "warning"
            else None
        ))

        print("=" * 70)
        print("  SIMULASI LIVE MULTI-HORIZON — PLAYWRIGHT HEADED")
        print("=" * 70)
        print(f"  Target: {URL}")
        print(f"  Display: {DISPLAY} ({WIDTH}x{HEIGHT})")
        print(f"  Timeout: {TIMEOUT}s")
        print("=" * 70)

        # Step 1: Navigate to dashboard
        print("\n[1/6] Navigasi ke Dashboard...")
        page.goto(URL, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)
        page.screenshot(path=str(screenshots_dir / "live_01_dashboard.png"))
        print("  ✅ Dashboard dimuat")

        # Step 2: Check for Multi-Horizon Projection widget
        print("\n[2/6] Verifikasi widget Proyeksi Multi-Horizon...")
        proj_widget = page.get_by_text("Proyeksi Multi-Horizon")
        if proj_widget.count() > 0:
            print("  ✅ Widget Proyeksi Multi-Horizon ditemukan")
        else:
            print("  ⚠️ Widget Proyeksi Multi-Horizon tidak ditemukan")

        # Step 3: Click "Evaluasi Ulang" button
        print("\n[3/6] Klik tombol 'Evaluasi Ulang'...")
        eval_button = page.get_by_text("Evaluasi Ulang")
        if eval_button.count() > 0:
            eval_button.first.click()
            print("  ✅ Tombol Evaluasi Ulang diklik")
            page.wait_for_timeout(5000)
            page.screenshot(path=str(screenshots_dir / "live_02_eval_running.png"))
        else:
            print("  ⚠️ Tombol Evaluasi Ulang tidak ditemukan, lanjutkan...")

        # Step 4: Wait for evaluation to progress and check projections
        print("\n[4/6] Monitor progress evaluasi...")
        start_time = time.time()
        while time.time() - start_time < 60:
            page.wait_for_timeout(5000)
            elapsed = int(time.time() - start_time)

            # Check for error stop
            if errors:
                print(f"  ❌ ERROR DETECTED at {elapsed}s — STOPPING")
                for e in errors[:5]:
                    print(f"    {e}")
                page.screenshot(path=str(screenshots_dir / "live_error.png"))
                break

            # Check if projections loaded
            proj_rows = page.get_by_text(re.compile(r"\+1Hari|\+1Minggu|\+1Bulan|\+1Tahun"))
            if proj_rows.count() > 0:
                print(f"  ✅ Proyeksi multi-horizon terdeteksi ({proj_rows.count()} elemen) at {elapsed}s")
                page.screenshot(path=str(screenshots_dir / "live_03_projections_loaded.png"))
                break

            print(f"  ⏳ Menunggu proyeksi... ({elapsed}s)")

        # Step 5: Navigate all pages to verify UI stability
        print("\n[5/6] Verifikasi stabilitas UI semua halaman...")
        pages_to_check = [
            ("Dashboard", "/"),
            ("Sinyal", "/signals"),
            ("Portofolio", "/portfolio"),
            ("Backtest", "/backtest"),
            ("Pengaturan", "/settings"),
        ]

        all_ok = True
        for name, path in pages_to_check:
            try:
                page.goto(f"{URL}{path}", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)
                page.screenshot(path=str(screenshots_dir / f"live_05_{name.lower()}.png"))
                print(f"  ✅ {name} — {path}")
            except Exception as e:
                print(f"  ❌ {name} — Error: {e}")
                all_ok = False
                errors.append(f"Navigation error on {name}: {e}")

        # Step 6: Final error check
        print("\n[6/6] Pemeriksaan error console...")
        if not errors:
            print("  ✅ Zero console errors")
        else:
            print(f"  ❌ {len(errors)} console errors ditemukan:")
            for e in errors[:10]:
                print(f"    {e}")

        if warnings:
            print(f"  ⚠️ {len(warnings)} warnings:")
            for w in warnings[:5]:
                print(f"    {w}")

        # Summary
        print("\n" + "=" * 70)
        print("  RINGKASAN SIMULASI LIVE MULTI-HORIZON")
        print("=" * 70)
        print(f"  Durasi: {int(time.time() - start_time)}s")
        print(f"  Console errors: {len(errors)}")
        print(f"  Warnings: {len(warnings)}")
        print(f"  Screenshots: {len(list(screenshots_dir.glob('live_*.png')))} files")
        print("=" * 70)

        browser.close()

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
