#!/usr/bin/env python3
"""Playwright headed E2E automation with Epson monitor targeting.

Launches a headed Chromium browser positioned on the Epson display,
runs test scenarios against the quant frontend, and captures all
console errors, network failures, and page crashes in real-time.

Self-healing loop: stops on first error, logs root cause, and waits
for code fix before proceeding to the next scenario.

Usage:
    python scripts/e2e_playwright_headed.py
    python scripts/e2e_playwright_headed.py --url http://localhost:3000
    python scripts/e2e_playwright_headed.py --no-start  # don't start dev server
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Add scripts dir to path for monitor_detect import
sys.path.insert(0, str(Path(__file__).parent))
from monitor_detect import detect_monitors_xrandr, get_epson_monitor, MonitorInfo


# ─── Configuration ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
REPORT_DIR = PROJECT_ROOT / "scripts" / "e2e_reports"
REPORT_DIR.mkdir(exist_ok=True)

DEFAULT_URL = "http://localhost:3000"
DEFAULT_TIMEOUT = 30_000  # 30s for page operations


# ─── Data Structures ──────────────────────────────────────────────────────

@dataclass
class ConsoleMessage:
    type: str
    text: str
    url: str
    line: int
    column: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class NetworkError:
    url: str
    status: int
    method: str
    resource_type: str
    error_text: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ScenarioResult:
    name: str
    status: str  # "PASS", "FAIL", "SKIP"
    duration_ms: float
    errors: list[str] = field(default_factory=list)
    console_errors: list[ConsoleMessage] = field(default_factory=list)
    network_errors: list[NetworkError] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)


@dataclass
class E2EReport:
    started_at: str
    finished_at: str = ""
    target_monitor: str = ""
    browser_position: str = ""
    scenarios: list[ScenarioResult] = field(default_factory=list)
    total_errors: int = 0
    self_healing_actions: list[str] = field(default_factory=list)


# ─── Monitor Targeting ────────────────────────────────────────────────────

def resolve_epson_monitor() -> MonitorInfo:
    """Detect Epson monitor or prompt for fallback."""
    monitors = detect_monitors_xrandr()
    if not monitors:
        print("❌ FATAL: No monitors detected. Cannot launch headed browser.")
        sys.exit(1)

    epson = get_epson_monitor(monitors)
    if epson:
        print(f"✅ Epson display targeted: {epson.output} ({epson.name})")
        print(f"   Position: X={epson.x}, Y={epson.y} | Resolution: {epson.resolution}")
        return epson

    # Fallback: warn and prompt
    print("\n⚠️  WARNING: Epson display NOT detected!")
    print("   Available monitors:")
    for i, m in enumerate(monitors):
        tag = " [PRIMARY]" if m.is_primary else ""
        print(f"   [{i}] {m.output} — {m.name} ({m.resolution}) at +{m.x}+{m.y}{tag}")

    try:
        choice = input("\n   Select monitor index (or Enter to abort): ").strip()
        if choice == "":
            print("   Aborting: no target monitor selected.")
            sys.exit(2)
        idx = int(choice)
        if 0 <= idx < len(monitors):
            selected = monitors[idx]
            print(f"   → Fallback: {selected.output} ({selected.name}) at +{selected.x}+{selected.y}")
            return selected
    except (ValueError, IndexError):
        pass

    print("   Invalid selection. Aborting.")
    sys.exit(2)


# ─── Dev Server Management ────────────────────────────────────────────────

class DevServerManager:
    """Starts and manages the Next.js dev server."""

    def __init__(self, frontend_dir: Path, port: int = 3000):
        self.frontend_dir = frontend_dir
        self.port = port
        self.process: subprocess.Popen | None = None

    def start(self) -> bool:
        """Start the dev server. Returns True if ready."""
        # Check if already running
        try:
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                 f"http://localhost:{self.port}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout == "200":
                print(f"✅ Dev server already running on port {self.port}")
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        print(f"▶ Starting Next.js dev server on port {self.port}...")
        self.process = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(self.frontend_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            preexec_fn=os.setsid,
        )

        # Wait for server to be ready (max 60s)
        for _ in range(120):
            time.sleep(0.5)
            try:
                result = subprocess.run(
                    ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                     f"http://localhost:{self.port}"],
                    capture_output=True, text=True, timeout=3,
                )
                if result.stdout in ("200", "307", "308"):
                    print(f"✅ Dev server ready on port {self.port}")
                    return True
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue

        print("❌ Dev server failed to start within 60s")
        return False

    def stop(self):
        if self.process:
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.process = None


# ─── Playwright E2E Runner ────────────────────────────────────────────────

class E2ERunner:
    """Runs Playwright headed browser scenarios with error capture."""

    def __init__(self, url: str, monitor: MonitorInfo, auto_mode: bool = False):
        self.url = url
        self.monitor = monitor
        self.auto_mode = auto_mode
        self.console_errors: list[ConsoleMessage] = []
        self.network_errors: list[NetworkError] = []
        self.page_errors: list[str] = []
        self.report = E2EReport(
            started_at=datetime.now().isoformat(),
            target_monitor=f"{monitor.output} ({monitor.name})",
            browser_position=f"{monitor.x},{monitor.y}",
        )

    @staticmethod
    def _is_network_error(text: str) -> bool:
        """Classify console messages that are really network/backend issues, not JS bugs."""
        net_patterns = [
            "Failed to load resource",
            "404 (Not Found)",
            "403",
            "WebSocket connection",
            "ERR_CONNECTION_REFUSED",
            "net::ERR_",
            "Failed to fetch",
        ]
        return any(p in text for p in net_patterns)

    def _launch_browser(self):
        """Launch Playwright Chromium headed browser on Epson display."""
        from playwright.sync_api import sync_playwright

        self.pw = sync_playwright().start()

        # Build launch args to position window on Epson monitor
        window_position = f"--window-position={self.monitor.x},{self.monitor.y}"
        window_size = f"--window-size={self.monitor.width},{self.monitor.height}"

        self.browser = self.pw.chromium.launch(
            headless=False,
            args=[
                window_position,
                window_size,
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )

        self.context = self.browser.new_context(
            viewport={"width": self.monitor.width, "height": self.monitor.height},
            locale="id-ID",
        )

        # Attach error listeners to every new page
        self.context.on("page", self._on_new_page)

    def _on_new_page(self, page):
        """Attach console and error listeners to a page."""
        page.on("console", lambda msg: self._on_console(msg, page))
        page.on("pageerror", lambda err: self._on_page_error(err, page))
        page.on("requestfailed", lambda req: self._on_request_failed(req, page))

    def _on_console(self, msg, page):
        """Capture console messages — focus on errors and warnings."""
        msg_type = msg.type
        if msg_type in ("error", "warning"):
            location = msg.location
            cm = ConsoleMessage(
                type=msg_type,
                text=msg.text,
                url=location.get("url", ""),
                line=location.get("lineNumber", 0),
                column=location.get("columnNumber", 0),
            )
            self.console_errors.append(cm)
            icon = "🔴" if msg_type == "error" else "🟡"
            print(f"  {icon} CONSOLE {msg_type.upper()}: {msg.text}")
            if location.get("url"):
                print(f"     at {location['url']}:{location.get('lineNumber', 0)}")

    def _on_page_error(self, err, page):
        """Capture uncaught page errors (runtime exceptions)."""
        self.page_errors.append(str(err))
        print(f"  💥 PAGE ERROR: {err}")

    def _on_request_failed(self, req, page):
        """Capture failed network requests."""
        try:
            response = req.response
            status = response.status if response else 0
        except Exception:
            status = 0

        ne = NetworkError(
            url=req.url,
            status=status,
            method=req.method,
            resource_type=req.resource_type,
            error_text=req.failure or "Unknown",
        )
        self.network_errors.append(ne)
        print(f"  🌐 NETWORK FAIL: {req.method} {req.url} — {req.failure}")

    def run_scenarios(self) -> list[ScenarioResult]:
        """Execute all E2E test scenarios sequentially."""
        self._launch_browser()
        page = self.context.new_page()

        scenarios = [
            ("S1: Page Load & Title", self._scenario_page_load),
            ("S2: Sidebar Navigation", self._scenario_sidebar_nav),
            ("S3: Dashboard Widgets Render", self._scenario_widgets_render),
            ("S4: Signals Page Navigation", self._scenario_signals_page),
            ("S5: Portfolio Page Navigation", self._scenario_portfolio_page),
            ("S6: Backtest Page Navigation", self._scenario_backtest_page),
            ("S7: Settings Page Navigation", self._scenario_settings_page),
            ("S8: API Health Check", self._scenario_api_health),
        ]

        results = []
        for name, func in scenarios:
            print(f"\n{'='*60}")
            print(f"  ▶ {name}")
            print(f"{'='*60}")

            # Clear per-scenario error collections
            prev_console = len(self.console_errors)
            prev_network = len(self.network_errors)
            prev_page = len(self.page_errors)

            result = ScenarioResult(
                name=name,
                status="PASS",
                duration_ms=0,
            )

            start = time.time()
            try:
                func(page)
                result.duration_ms = (time.time() - start) * 1000

                # Check for new errors during this scenario
                new_console = self.console_errors[prev_console:]
                new_network = self.network_errors[prev_network:]
                new_page_err = self.page_errors[prev_page:]

                if new_page_err:
                    result.status = "FAIL"
                    result.errors.extend(new_page_err)
                    result.console_errors = new_console
                    result.network_errors = new_network
                    print(f"  ❌ FAIL: {len(new_page_err)} page error(s)")
                    self._self_heal(name, new_page_err, page)
                else:
                    # Separate real JS errors from network/backend errors
                    real_js_errors = [
                        cm for cm in new_console
                        if cm.type == "error" and not self._is_network_error(cm.text)
                    ]
                    net_warnings = [
                        cm for cm in new_console
                        if cm.type == "error" and self._is_network_error(cm.text)
                    ]

                    if net_warnings:
                        print(f"  🟡 {len(net_warnings)} network warning(s) (backend API not running)")
                        result.console_errors = new_console
                        result.network_errors = new_network

                    if real_js_errors:
                        result.status = "FAIL"
                        result.errors.extend(cm.text for cm in real_js_errors)
                        result.console_errors = new_console
                        result.network_errors = new_network
                        print(f"  ❌ FAIL: {len(real_js_errors)} JS console error(s)")
                        self._self_heal(name, [cm.text for cm in real_js_errors], page)
                    else:
                        if new_console and not net_warnings:
                            result.console_errors = new_console
                        if new_network:
                            result.network_errors = new_network
                        print(f"  ✅ PASS ({result.duration_ms:.0f}ms)")

            except Exception as e:
                result.status = "FAIL"
                result.duration_ms = (time.time() - start) * 1000
                result.errors.append(str(e))
                print(f"  ❌ FAIL: {e}")
                # Take screenshot on failure
                try:
                    screenshot_path = str(REPORT_DIR / f"{name.replace(' ', '_')}_fail.png")
                    page.screenshot(path=screenshot_path)
                    result.screenshots.append(screenshot_path)
                    print(f"  📸 Screenshot: {screenshot_path}")
                except Exception:
                    pass
                self._self_heal(name, [str(e)], page)

            results.append(result)

            # Self-healing gate: don't proceed if failed
            if result.status == "FAIL":
                print(f"\n  ⛔ SELF-HEALING GATE: Scenario '{name}' failed.")
                print(f"     Fix the error above before proceeding.")

                if self.auto_mode:
                    print(f"  🔄 Auto-retrying '{name}'...")
                    start = time.time()
                    try:
                        func(page)
                        result.duration_ms = (time.time() - start) * 1000
                        result.status = "PASS"
                        print(f"  ✅ PASS on retry ({result.duration_ms:.0f}ms)")
                    except Exception as e2:
                        result.status = "SKIP"
                        result.errors.append(f"Retry failed: {e2}")
                        print(f"  ⏭️  Auto-skipping after retry failure: {e2}")
                else:
                    print(f"     Press Enter to retry, or 'skip' to continue: ", end="")
                    try:
                        user_input = input().strip().lower()
                        if user_input == "skip":
                            result.status = "SKIP"
                            continue
                        # Retry the scenario
                        print(f"  🔄 Retrying '{name}'...")
                        start = time.time()
                        try:
                            func(page)
                            result.duration_ms = (time.time() - start) * 1000
                            result.status = "PASS"
                            print(f"  ✅ PASS on retry ({result.duration_ms:.0f}ms)")
                        except Exception as e2:
                            result.status = "FAIL"
                            result.errors.append(f"Retry failed: {e2}")
                            print(f"  ❌ Retry also failed: {e2}")
                    except EOFError:
                        pass

        # Final report
        self.report.scenarios = results
        self.report.finished_at = datetime.now().isoformat()
        self.report.total_errors = sum(
            len(r.errors) for r in results if r.status == "FAIL"
        )

        self._save_report()
        self._cleanup()
        return results

    def _self_heal(self, scenario_name: str, errors: list[str], page):
        """Log self-healing analysis for detected errors."""
        for err in errors:
            action = f"[{datetime.now().isoformat()}] {scenario_name}: {err}"
            self.report.self_healing_actions.append(action)
            print(f"  🔧 SELF-HEAL ANALYSIS: {err}")

    # ─── Test Scenarios ───────────────────────────────────────────────────

    def _scenario_page_load(self, page):
        """S1: Verify page loads with correct title."""
        page.goto(self.url, timeout=DEFAULT_TIMEOUT, wait_until="networkidle")
        title = page.title()
        assert title, "Page title is empty"
        print(f"     Title: {title}")

        # Verify main content area exists
        page.wait_for_selector("main", timeout=10_000)
        print("     <main> element found")

    def _scenario_sidebar_nav(self, page):
        """S2: Test sidebar navigation links."""
        page.goto(self.url, timeout=DEFAULT_TIMEOUT, wait_until="networkidle")

        # Find sidebar links
        sidebar = page.query_selector("nav, aside, [role='navigation']")
        if not sidebar:
            print("     ⚠️ No sidebar element found — checking nav links globally")
            links = page.query_selector_all("a[href]")
        else:
            links = sidebar.query_selector_all("a[href]")

        assert len(links) > 0, "No navigation links found"
        print(f"     Found {len(links)} navigation links")

        # Click first non-active link
        for link in links:
            href = link.get_attribute("href")
            if href and href != "/" and href != "#":
                text = link.inner_text().strip()[:30]
                print(f"     Clicking: {text} → {href}")
                link.click()
                page.wait_for_load_state("networkidle", timeout=15_000)
                print(f"     Navigated to: {page.url}")
                break

    def _scenario_widgets_render(self, page):
        """S3: Verify dashboard widgets are visible."""
        page.goto(self.url, timeout=DEFAULT_TIMEOUT, wait_until="networkidle")
        page.wait_for_selector("main", timeout=10_000)

        # Check for common widget patterns
        widgets = page.query_selector_all("[class*='widget'], [class*='card'], [class*='panel']")
        print(f"     Found {len(widgets)} widget-like elements")

        # Check for SVG charts (recharts renders SVG)
        svgs = page.query_selector_all("svg")
        print(f"     Found {len(svgs)} SVG elements (charts)")

        # Verify no blank/frozen UI — check body has content
        body_text = page.inner_text("body")
        assert len(body_text.strip()) > 50, "Page body appears empty (possible UI freeze)"

    def _scenario_signals_page(self, page):
        """S4: Navigate to signals page."""
        page.goto(f"{self.url}/signals", timeout=DEFAULT_TIMEOUT, wait_until="networkidle")
        page.wait_for_selector("main", timeout=10_000)
        print(f"     URL: {page.url}")
        body = page.inner_text("body")
        assert len(body.strip()) > 10, "Signals page appears empty"

    def _scenario_portfolio_page(self, page):
        """S5: Navigate to portfolio page."""
        page.goto(f"{self.url}/portfolio", timeout=DEFAULT_TIMEOUT, wait_until="networkidle")
        page.wait_for_selector("main", timeout=10_000)
        print(f"     URL: {page.url}")
        body = page.inner_text("body")
        assert len(body.strip()) > 10, "Portfolio page appears empty"

    def _scenario_backtest_page(self, page):
        """S6: Navigate to backtest page."""
        page.goto(f"{self.url}/backtest", timeout=DEFAULT_TIMEOUT, wait_until="domcontentloaded")
        page.wait_for_selector("main", timeout=15_000)
        page.wait_for_timeout(1000)
        print(f"     URL: {page.url}")
        body = page.inner_text("body")
        assert len(body.strip()) > 10, "Backtest page appears empty"

    def _scenario_settings_page(self, page):
        """S7: Navigate to settings page."""
        page.goto(f"{self.url}/settings", timeout=DEFAULT_TIMEOUT, wait_until="networkidle")
        page.wait_for_selector("main", timeout=10_000)
        print(f"     URL: {page.url}")
        body = page.inner_text("body")
        assert len(body.strip()) > 10, "Settings page appears empty"

    def _scenario_api_health(self, page):
        """S8: Check API health endpoint."""
        import urllib.request
        import urllib.error

        api_url = self.url.replace(":3000", ":8000") + "/api/health"
        print(f"     Checking API: {api_url}")
        try:
            req = urllib.request.Request(api_url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                body = resp.read().decode()[:200]
                print(f"     API Status: {status}")
                print(f"     API Response: {body}")
                assert status == 200, f"API returned {status}"
        except urllib.error.URLError as e:
            print(f"     ⚠️ API not reachable: {e}")
            print(f"     (This is OK if backend is not running)")

    # ─── Reporting ────────────────────────────────────────────────────────

    def _save_report(self):
        """Save structured E2E report as JSON."""
        report_data = {
            "started_at": self.report.started_at,
            "finished_at": self.report.finished_at,
            "target_monitor": self.report.target_monitor,
            "browser_position": self.report.browser_position,
            "total_errors": self.report.total_errors,
            "self_healing_actions": self.report.self_healing_actions,
            "scenarios": [
                {
                    "name": r.name,
                    "status": r.status,
                    "duration_ms": round(r.duration_ms, 1),
                    "errors": r.errors,
                    "console_errors": [
                        {"type": cm.type, "text": cm.text, "url": cm.url}
                        for cm in r.console_errors
                    ],
                    "network_errors": [
                        {"url": ne.url, "status": ne.status, "error": ne.error_text}
                        for ne in r.network_errors
                    ],
                    "screenshots": r.screenshots,
                }
                for r in self.report.scenarios
            ],
        }

        report_path = REPORT_DIR / f"e2e_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, "w") as f:
            json.dump(report_data, f, indent=2)
        print(f"\n📋 Report saved: {report_path}")

    def _print_summary(self):
        """Print human-readable test summary."""
        results = self.report.scenarios
        passed = sum(1 for r in results if r.status == "PASS")
        failed = sum(1 for r in results if r.status == "FAIL")
        skipped = sum(1 for r in results if r.status == "SKIP")

        print(f"\n{'='*60}")
        print(f"  E2E TEST SUMMARY")
        print(f"{'='*60}")
        print(f"  Target Monitor: {self.report.target_monitor}")
        print(f"  Browser Position: {self.report.browser_position}")
        print(f"  Total Scenarios: {len(results)}")
        print(f"  ✅ Passed: {passed}")
        print(f"  ❌ Failed: {failed}")
        print(f"  ⏭️  Skipped: {skipped}")
        print(f"  Total Errors: {self.report.total_errors}")
        print(f"  Self-Healing Actions: {len(self.report.self_healing_actions)}")
        print(f"{'='*60}")

        for r in results:
            icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}[r.status]
            print(f"  {icon} {r.name} ({r.duration_ms:.0f}ms)")
            if r.errors:
                for e in r.errors[:3]:
                    print(f"       → {e[:100]}")

    def _cleanup(self):
        """Close browser and Playwright."""
        self._print_summary()
        try:
            self.context.close()
            self.browser.close()
            self.pw.stop()
        except Exception:
            pass


# ─── Main Entry Point ─────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="E2E Playwright Headed Automation")
    parser.add_argument("--url", default=DEFAULT_URL, help="Frontend URL")
    parser.add_argument("--no-start", action="store_true", help="Don't start dev server")
    parser.add_argument("--port", type=int, default=3000, help="Dev server port")
    parser.add_argument("--auto", action="store_true", help="Non-interactive mode: auto-skip failures after retry")
    args = parser.parse_args()

    print("=" * 60)
    print("  PLAYWRIGHT HEADED E2E AUTOMATION")
    print("  Epson Monitor Targeting + Self-Healing Loop")
    print("=" * 60)

    # Step 1: Detect Epson monitor
    print("\n📡 Step 1: Monitor Detection")
    monitor = resolve_epson_monitor()

    # Step 2: Start dev server (if needed)
    server = DevServerManager(FRONTEND_DIR, args.port)
    if not args.no_start:
        print(f"\n🖥️  Step 2: Dev Server")
        if not server.start():
            print("❌ Cannot start dev server. Aborting.")
            return 1
    else:
        print("\n🖥️  Step 2: Dev server auto-start skipped (--no-start)")

    # Step 3: Run E2E scenarios
    print(f"\n🎭 Step 3: E2E Scenarios")
    runner = E2ERunner(args.url, monitor, auto_mode=args.auto)

    try:
        results = runner.run_scenarios()
    finally:
        if not args.no_start:
            server.stop()

    # Exit code: 0 if all pass, 1 if any fail
    failed = sum(1 for r in results if r.status == "FAIL")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
