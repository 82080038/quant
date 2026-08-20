"""Quick Playwright verification of risk metrics charts on Epson."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from monitor_detector import find_epson_monitor
from playwright.sync_api import sync_playwright

URL = "http://localhost:3000"

def main():
    screenshots = Path(__file__).parent.parent / "docs" / "risk_metrics_screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    epson = find_epson_monitor()
    if not epson:
        print("❌ Epson not found")
        return 1

    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                f"--window-position={epson.x},{epson.y}",
                f"--window-size={epson.width},{epson.height}",
                "--start-maximized",
                "--no-sandbox",
            ],
        )
        ctx = browser.new_context(viewport={"width": epson.width, "height": epson.height}, locale="id-ID")
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(f"CONSOLE: {m.text}") if m.type == "error" else None)

        print("[1] Navigate to /manajemen-engine...")
        page.goto(f"{URL}/manajemen-engine", wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_timeout(5000)
        page.screenshot(path=str(screenshots / "final_01_loaded.png"))

        win_x = page.evaluate("window.screenX")
        print(f"  Window X: {win_x} (Epson: {epson.x})")

        # Verify panels
        for name, sel in [
            ("Equity Curve", "text=Kurva Ekuitas"),
            ("Scorecard", "text=Skor Kinerja Institusional"),
            ("Sharpe", "text=Sharpe Ratio"),
            ("Profit Factor", "text=Profit Factor"),
            ("Max Drawdown", "text=Max Drawdown"),
            ("Win Rate", "text=Win Rate"),
            ("Return", "text=Return on Capital"),
        ]:
            c = page.locator(sel).count()
            print(f"  {'✅' if c > 0 else '❌'} {name}: {c}")

        # Scroll to equity curve
        page.locator("text=Kurva Ekuitas").scroll_into_view_if_needed()
        page.wait_for_timeout(3000)
        page.screenshot(path=str(screenshots / "final_02_equity_curve.png"))

        # Scroll to scorecard
        page.locator("text=Skor Kinerja Institusional").scroll_into_view_if_needed()
        page.wait_for_timeout(3000)
        page.screenshot(path=str(screenshots / "final_03_scorecard.png"))

        # Full page
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(screenshots / "final_04_full_top.png"))

        # Scroll to bottom
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(screenshots / "final_05_full_bottom.png"))

        print(f"\nErrors: {len(errors)}")
        if errors:
            for e in errors[:5]:
                print(f"  {e}")

        browser.close()

    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(main())
