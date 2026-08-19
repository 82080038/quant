"""Stress-test E2E — Playwright headed run with FPS + content verification.

Runs on the Epson display, navigates through all pages repeatedly,
monitors FPS via requestAnimationFrame, captures console/network errors,
reads and verifies page content against simulation API data,
and uses the ML ErrorPatternLearner to classify any errors found.

Auto-stops when:
  - Duration limit reached
  - Simulation engine reports running=false (all ticks consumed)
  - Critical page error detected (in non-auto mode)

Usage:
    python scripts/stress_test_e2e.py --duration 300 --url http://localhost:3000
    python scripts/stress_test_e2e.py --duration 300 --auto  # non-interactive
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Add project root + scripts to path
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

from monitor_detect import detect_monitors_xrandr, get_epson_monitor, MonitorInfo, prompt_fallback
from quant.agentic.ml_meta import ErrorPatternLearner, SelfHealingPromptGenerator

REPORT_DIR = _PROJECT_ROOT / "scripts" / "e2e_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# Pages to cycle through during stress test
STRESS_PAGES = [
    ("Dashboard", "/"),
    ("Cosmos", "/cosmos"),
    ("Signals", "/signals"),
    ("Portfolio", "/portfolio"),
    ("Backtest", "/backtest"),
    ("Scheduler", "/scheduler"),
    ("Data", "/data"),
    ("Reports", "/reports"),
    ("Screener", "/screener"),
    ("Settings", "/settings"),
]

# FPS monitoring JS injected into page
_FPS_SCRIPT = """
() => {
    return new Promise((resolve) => {
        let frames = 0;
        let start = performance.now();
        let minFps = Infinity;
        let maxFps = 0;
        let samples = [];

        function tick(now) {
            frames++;
            const elapsed = now - start;
            if (elapsed >= 1000) {
                const fps = (frames / elapsed) * 1000;
                samples.push(fps);
                if (fps < minFps) minFps = fps;
                if (fps > maxFps) maxFps = fps;
                frames = 0;
                start = now;
            }
            if (elapsed < 5000) {
                requestAnimationFrame(tick);
            } else {
                const avgFps = samples.reduce((a,b) => a+b, 0) / samples.length;
                resolve({ avgFps, minFps, maxFps, samples });
            }
        }
        requestAnimationFrame(tick);
    });
}
"""


@dataclass
class ContentCheck:
    """Result of verifying page content against expected data."""
    selector: str
    expected: str
    actual: str
    passed: bool


@dataclass
class StressTestResult:
    """Result of a single page stress test cycle."""
    page_name: str
    url: str
    fps_avg: float = 0
    fps_min: float = 0
    fps_max: float = 0
    console_errors: list[dict] = field(default_factory=list)
    network_errors: list[dict] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    content_checks: list[ContentCheck] = field(default_factory=list)
    page_text_snippet: str = ""  # first 500 chars of visible text
    load_time_ms: float = 0
    passed: bool = True
    error: str = ""
    sim_running: bool = True  # was simulation still running?


@dataclass
class StressTestReport:
    """Full stress test report."""
    started_at: str = ""
    finished_at: str = ""
    duration_s: int = 0
    target_monitor: str = ""
    browser_position: str = ""
    total_cycles: int = 0
    results: list[StressTestResult] = field(default_factory=list)
    fps_history: list[dict] = field(default_factory=list)
    all_errors: list[str] = field(default_factory=list)
    content_failures: list[dict] = field(default_factory=list)
    ml_patterns: list[dict] = field(default_factory=list)
    self_healing_prompt: str = ""
    overall_pass: bool = True
    avg_fps: float = 0
    min_fps: float = 0
    stop_reason: str = ""  # why the test stopped
    sim_status: dict = field(default_factory=dict)


def _api_get(base_url: str, path: str) -> dict | list | None:
    """Fetch JSON from API endpoint (urllib, no deps)."""
    try:
        url = f"{base_url}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _extract_numbers(text: str) -> list[str]:
    """Extract all number-like strings from text (for comparison)."""
    return re.findall(r'[\d,]+\.?\d*', text)


def _verify_page_content(page, page_name: str, api_url: str) -> list[ContentCheck]:
    """Read page DOM content and verify against simulation API data.

    Returns list of ContentCheck results (passed/failed).
    """
    checks: list[ContentCheck] = []

    try:
        body_text = page.inner_text("body") or ""
    except Exception:
        body_text = ""

    if page_name == "Dashboard":
        # Verify IHSG price appears on page
        ihsg_data = _api_get(api_url, "/api/prices/ihsg")
        if ihsg_data and isinstance(ihsg_data, dict):
            price = ihsg_data.get("price")
            if price:
                price_str = f"{price:,.2f}"
                # Check if price appears (may be formatted differently)
                price_digits = str(int(price))
                passed = price_digits in body_text or str(int(price)) in body_text
                checks.append(ContentCheck(
                    selector="body", expected=f"IHSG ~{price_str}",
                    actual=body_text[:200], passed=passed,
                ))
                if not passed:
                    print(f"  ⚠️  IHSG price {price_str} not found in page text")

        # Verify movers tickers appear
        movers = _api_get(api_url, "/api/prices/movers?limit=5")
        if movers and isinstance(movers, dict):
            for g in movers.get("gainers", [])[:3]:
                ticker = g.get("ticker", "")
                if ticker and ticker not in body_text:
                    # Try without .JK suffix
                    short = ticker.replace(".JK", "")
                    if short not in body_text:
                        checks.append(ContentCheck(
                            selector="body", expected=f"ticker {ticker}",
                            actual="(not found)", passed=False,
                        ))
                        print(f"  ⚠️  Ticker {ticker} not found in dashboard")

        # Verify portfolio NAV appears
        portfolio = _api_get(api_url, "/api/portfolio")
        if portfolio and isinstance(portfolio, dict):
            nav = portfolio.get("total_nav", 0)
            nav_str = f"{int(nav):,}"
            # NAV formatted with Indonesian locale uses . as thousand separator
            nav_idr = f"{int(nav):,}".replace(",", ".")
            if nav_str not in body_text and nav_idr not in body_text:
                checks.append(ContentCheck(
                    selector="body", expected=f"NAV ~{nav_str}",
                    actual="(not found)", passed=False,
                ))
                print(f"  ⚠️  Portfolio NAV {nav_str} not found in dashboard")

    elif page_name == "Portfolio":
        portfolio = _api_get(api_url, "/api/portfolio")
        if portfolio and isinstance(portfolio, dict):
            nav = portfolio.get("total_nav", 0)
            nav_str = f"{int(nav):,}".replace(",", ".")
            if nav_str not in body_text and str(int(nav)) in body_text:
                checks.append(ContentCheck(
                    selector="body", expected=f"NAV {nav_str}",
                    actual=body_text[:200], passed=True,
                ))
            elif nav_str in body_text:
                checks.append(ContentCheck(
                    selector="body", expected=f"NAV {nav_str}",
                    actual=body_text[:200], passed=True,
                ))
            else:
                # Check if any position ticker appears
                positions = portfolio.get("positions", {})
                found_any = any(ticker in body_text for ticker in positions)
                checks.append(ContentCheck(
                    selector="body", expected=f"NAV or positions",
                    actual=body_text[:200], passed=found_any,
                ))
                if not found_any and positions:
                    print(f"  ⚠️  No portfolio positions found in page text")

    elif page_name == "Signals":
        signals = _api_get(api_url, "/api/signals/attribution")
        if signals and isinstance(signals, list) and len(signals) > 0:
            for sig in signals[:3]:
                ticker = sig.get("ticker", "")
                if ticker and ticker not in body_text:
                    short = ticker.replace(".JK", "")
                    if short not in body_text:
                        checks.append(ContentCheck(
                            selector="body", expected=f"signal {ticker}",
                            actual="(not found)", passed=False,
                        ))
                        print(f"  ⚠️  Signal ticker {ticker} not found in signals page")

    elif page_name == "Cosmos":
        # Cosmos page should show exchanges or satellite data
        exchanges = _api_get(api_url, "/api/cosmos/exchanges")
        if exchanges and isinstance(exchanges, dict):
            ex_list = exchanges.get("exchanges", [])
            if ex_list and len(ex_list) > 0:
                # Check if any exchange name appears
                found = any(ex.get("name", "") in body_text for ex in ex_list[:5])
                checks.append(ContentCheck(
                    selector="body", expected="exchange names",
                    actual=body_text[:200], passed=found,
                ))
                if not found:
                    print(f"  ⚠️  No exchange names found in cosmos page")

    elif page_name == "Data":
        # Data page should show sources or watermarks
        sources = _api_get(api_url, "/api/data/sources")
        if sources and isinstance(sources, dict):
            # Even if sources empty, page should render
            checks.append(ContentCheck(
                selector="body", expected="data management UI",
                actual=body_text[:200], passed=len(body_text) > 50,
            ))

    elif page_name == "Reports":
        # Reports page should show trade log or dividends
        checks.append(ContentCheck(
            selector="body", expected="reports UI",
            actual=body_text[:200], passed=len(body_text) > 50,
        ))

    elif page_name == "Screener":
        # Screener page should have controls
        checks.append(ContentCheck(
            selector="body", expected="screener UI",
            actual=body_text[:200], passed=len(body_text) > 50,
        ))

    elif page_name == "Settings":
        # Settings page should show config fields
        checks.append(ContentCheck(
            selector="body", expected="settings UI",
            actual=body_text[:200], passed=len(body_text) > 50,
        ))

    elif page_name == "Scheduler":
        # Scheduler page should show status
        checks.append(ContentCheck(
            selector="body", expected="scheduler UI",
            actual=body_text[:200], passed=len(body_text) > 50,
        ))

    elif page_name == "Backtest":
        # Backtest page should show status
        checks.append(ContentCheck(
            selector="body", expected="backtest UI",
            actual=body_text[:200], passed=len(body_text) > 50,
        ))

    elif page_name == "Stock":
        checks.append(ContentCheck(
            selector="body", expected="stock detail UI",
            actual=body_text[:200], passed=len(body_text) > 50,
        ))

    return checks


def run_stress_test(
    url: str,
    monitor: MonitorInfo,
    duration_s: int = 300,
    auto_mode: bool = False,
    api_url: str = "http://localhost:8000",
) -> StressTestReport:
    """Run stress test for the given duration.

    Args:
        url: Frontend URL
        monitor: Target monitor info
        duration_s: Test duration in seconds (default 300 = 5 min)
        auto_mode: Non-interactive mode
        api_url: Backend API URL for data verification

    Returns:
        StressTestReport with all results
    """
    from playwright.sync_api import sync_playwright

    report = StressTestReport(
        started_at=datetime.now().isoformat(),
        duration_s=duration_s,
        target_monitor=f"{monitor.output} ({monitor.name})",
        browser_position=f"{monitor.x},{monitor.y}",
    )

    print("=" * 60)
    print("  STRESS TEST E2E — FPS + Content Verification + ML Engine")
    print(f"  Duration: {duration_s}s | Target: {monitor.name}")
    print(f"  Frontend: {url} | API: {api_url}")
    print("=" * 60)

    # ML Engine
    learner = ErrorPatternLearner()
    prompt_gen = SelfHealingPromptGenerator()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=[
                f"--window-position={monitor.x},{monitor.y}",
                f"--window-size={monitor.width},{monitor.height}",
                "--start-maximized",
                "--disable-gpu-shader-disk-cache",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            viewport={"width": monitor.width, "height": monitor.height},
        )
        page = context.new_page()

        # Error capture
        console_errors: list[dict] = []
        network_errors: list[dict] = []
        page_errors: list[str] = []

        def on_console(msg):
            if msg.type == "error":
                console_errors.append({
                    "type": "error",
                    "text": msg.text,
                    "url": msg.location.get("url", ""),
                })
                print(f"  🔴 CONSOLE: {msg.text[:120]}")

        def on_pageerror(err):
            page_errors.append(str(err))
            print(f"  💥 PAGE ERROR: {str(err)[:120]}")

        def on_requestfailed(req):
            network_errors.append({
                "url": req.url,
                "method": req.method,
                "failure": req.failure,
            })

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("requestfailed", on_requestfailed)

        # Run cycles
        cycle = 0
        start_time = time.time()
        all_fps_samples: list[float] = []
        stop_reason = ""

        while time.time() - start_time < duration_s:
            # ── Check simulation status — auto-stop if finished ──
            sim_status = _api_get(api_url, "/api/simulation/status")
            if sim_status and isinstance(sim_status, dict):
                sim_running = sim_status.get("running", False)
                sim_tick = sim_status.get("current_tick", 0)
                sim_total = sim_status.get("total_ticks", 0)
                report.sim_status = sim_status

                if not sim_running:
                    stop_reason = f"Simulation finished (tick {sim_tick}/{sim_total})"
                    print(f"\n  ⏹️  {stop_reason} — auto-stopping stress test")
                    break
                else:
                    print(f"  📊 Sim: tick {sim_tick}/{sim_total} | regime={sim_status.get('regime', '?')} | time={sim_status.get('sim_time', '?')}")
            else:
                # Simulation API not responding — check if it was ever started
                if cycle > 0:
                    print(f"  ⚠️  Simulation API not responding — continuing without sim data")

            cycle += 1
            page_name, page_path = STRESS_PAGES[(cycle - 1) % len(STRESS_PAGES)]
            page_url = f"{url}{page_path}"

            print(f"\n── Cycle {cycle} ▶ {page_name} ({page_path}) ──")
            result = StressTestResult(page_name=page_name, url=page_url)

            cycle_start = time.time()

            # Snapshot errors before navigation
            prev_console = len(console_errors)
            prev_network = len(network_errors)
            prev_page = len(page_errors)

            try:
                page.goto(page_url, wait_until="domcontentloaded", timeout=15000)
                result.load_time_ms = (time.time() - cycle_start) * 1000

                # Wait for page to settle + fetch data
                time.sleep(3)

                # ── Read and verify page content ──
                try:
                    body_text = page.inner_text("body") or ""
                    result.page_text_snippet = body_text[:500]
                    print(f"  📄 Page text: {len(body_text)} chars, first 80: {body_text[:80].strip()}")
                except Exception:
                    result.page_text_snippet = ""

                content_checks = _verify_page_content(page, page_name, api_url)
                result.content_checks = content_checks

                failed_checks = [c for c in content_checks if not c.passed]
                if failed_checks:
                    print(f"  ⚠️  {len(failed_checks)} content check(s) failed")
                    for fc in failed_checks:
                        print(f"       expected: {fc.expected}")
                        report.content_failures.append({
                            "cycle": cycle,
                            "page": page_name,
                            "expected": fc.expected,
                            "actual": fc.actual[:200],
                        })
                else:
                    print(f"  ✅ Content checks passed ({len(content_checks)} checks)")

                # Measure FPS for 5 seconds
                try:
                    fps_data = page.evaluate(_FPS_SCRIPT)
                    result.fps_avg = round(fps_data.get("avgFps", 0), 1)
                    result.fps_min = round(fps_data.get("minFps", 0), 1)
                    result.fps_max = round(fps_data.get("maxFps", 0), 1)

                    all_fps_samples.append(result.fps_avg)
                    report.fps_history.append({
                        "cycle": cycle,
                        "page": page_name,
                        "fps_avg": result.fps_avg,
                        "fps_min": result.fps_min,
                        "fps_max": result.fps_max,
                    })

                    fps_status = "✅" if result.fps_avg >= 55 else "🟡" if result.fps_avg >= 30 else "🔴"
                    print(f"  {fps_status} FPS: avg={result.fps_avg} min={result.fps_min} max={result.fps_max} | Load: {result.load_time_ms:.0f}ms")

                    if result.fps_avg < 55:
                        print(f"  ⚠️  FPS below 55 threshold — potential UI freeze risk")

                except Exception as e:
                    print(f"  ⚠️  FPS measurement failed: {e}")
                    result.fps_avg = 0

                # Check for new errors
                new_console = console_errors[prev_console:]
                new_network = network_errors[prev_network:]
                new_page = page_errors[prev_page:]

                result.console_errors = new_console
                result.network_errors = new_network
                result.page_errors = new_page

                if new_page:
                    result.passed = False
                    result.error = f"{len(new_page)} page error(s)"
                    print(f"  ❌ {len(new_page)} page error(s)")
                elif new_console:
                    # Check if real JS errors (not network)
                    real_js = [
                        c for c in new_console
                        if not any(p in c["text"] for p in [
                            "Failed to load resource", "404", "403",
                            "WebSocket connection", "ERR_CONNECTION",
                            "net::ERR_", "Failed to fetch",
                        ])
                    ]
                    if real_js:
                        result.passed = False
                        result.error = f"{len(real_js)} JS error(s)"
                        print(f"  ❌ {len(real_js)} JS console error(s)")
                    else:
                        net_count = len(new_console) - len(real_js)
                        if net_count:
                            print(f"  🟡 {net_count} network warning(s)")

                # Content check failures don't fail the test but are logged
                if failed_checks and result.passed:
                    print(f"  ℹ️  Content mismatches logged but not failing test")

            except Exception as e:
                result.passed = False
                result.error = str(e)
                result.load_time_ms = (time.time() - cycle_start) * 1000
                print(f"  ❌ Navigation failed: {str(e)[:120]}")

            report.results.append(result)
            report.all_errors.extend(result.page_errors)
            if not result.passed:
                report.overall_pass = False

            # ML Engine: learn from errors in real-time
            if result.page_errors or result.console_errors:
                error_texts = result.page_errors + [c["text"] for c in result.console_errors]
                learner.learn(error_texts)

            # Check if we should pause for self-healing
            if not result.passed and not auto_mode:
                print(f"\n  ⛔ SELF-HEALING GATE: {page_name} failed")
                print(f"     Press Enter to continue, 'skip' to abort: ", end="")
                try:
                    user_input = input().strip().lower()
                    if user_input == "skip":
                        stop_reason = "User aborted"
                        break
                except EOFError:
                    pass
            elif not result.passed and auto_mode:
                print(f"  ⏭️  Auto-continuing past failure")

        # Cleanup
        report.total_cycles = cycle
        report.finished_at = datetime.now().isoformat()
        report.stop_reason = stop_reason or "Duration limit reached"

        # Calculate aggregate FPS
        if all_fps_samples:
            report.avg_fps = round(sum(all_fps_samples) / len(all_fps_samples), 1)
            report.min_fps = round(min(all_fps_samples), 1)

        # ML Engine: generate self-healing prompt if errors found
        if report.all_errors:
            report.self_healing_prompt = prompt_gen.generate(
                errors=report.all_errors,
                console_errors=console_errors,
                network_errors=network_errors,
            )
            patterns = learner.get_patterns()
            report.ml_patterns = [
                {
                    "pattern_id": p.pattern_id,
                    "category": p.category,
                    "frequency": p.frequency,
                    "centroid_text": p.centroid_text,
                }
                for p in patterns
            ]

        # Stop simulation if still running
        sim = _api_get(api_url, "/api/simulation/status")
        if sim and isinstance(sim, dict) and sim.get("running"):
            try:
                req = urllib.request.Request(
                    f"{api_url}/api/simulation/stop",
                    method="POST",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=5)
                print("  🛑 Simulation stopped")
            except Exception:
                pass

        browser.close()

    # Save report
    report_path = REPORT_DIR / f"stress_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_data = {
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "duration_s": report.duration_s,
        "target_monitor": report.target_monitor,
        "browser_position": report.browser_position,
        "total_cycles": report.total_cycles,
        "overall_pass": report.overall_pass,
        "avg_fps": report.avg_fps,
        "min_fps": report.min_fps,
        "stop_reason": report.stop_reason,
        "sim_status": report.sim_status,
        "fps_history": report.fps_history,
        "results": [
            {
                "page_name": r.page_name,
                "url": r.url,
                "fps_avg": r.fps_avg,
                "fps_min": r.fps_min,
                "fps_max": r.fps_max,
                "load_time_ms": r.load_time_ms,
                "passed": r.passed,
                "error": r.error,
                "page_text_snippet": r.page_text_snippet,
                "content_checks": [
                    {"selector": c.selector, "expected": c.expected, "passed": c.passed}
                    for c in r.content_checks
                ],
                "console_errors": r.console_errors,
                "network_errors": r.network_errors,
                "page_errors": r.page_errors,
            }
            for r in report.results
        ],
        "all_errors": report.all_errors,
        "content_failures": report.content_failures,
        "ml_patterns": report.ml_patterns,
        "self_healing_prompt": report.self_healing_prompt,
    }
    report_path.write_text(json.dumps(report_data, indent=2))

    # Print summary
    print("\n" + "=" * 60)
    print("  STRESS TEST SUMMARY")
    print("=" * 60)
    print(f"  Target Monitor: {report.target_monitor}")
    print(f"  Duration: {report.duration_s}s | Cycles: {report.total_cycles}")
    print(f"  Overall: {'✅ PASS' if report.overall_pass else '❌ FAIL'}")
    print(f"  Avg FPS: {report.avg_fps} | Min FPS: {report.min_fps}")
    print(f"  Total Errors: {len(report.all_errors)}")
    print(f"  Content Failures: {len(report.content_failures)}")
    print(f"  ML Patterns Learned: {len(report.ml_patterns)}")
    print(f"  Stop Reason: {report.stop_reason}")
    if report.sim_status:
        print(f"  Sim Status: tick {report.sim_status.get('current_tick', '?')}/{report.sim_status.get('total_ticks', '?')} | regime={report.sim_status.get('regime', '?')}")
    if report.ml_patterns:
        for p in report.ml_patterns:
            print(f"    [{p['category']}] {p['frequency']}x: {p['centroid_text'][:80]}")
    print(f"\n  Report: {report_path}")
    print("=" * 60)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress Test E2E with FPS + Content Verification")
    parser.add_argument("--url", default="http://localhost:3000", help="Frontend URL")
    parser.add_argument("--api-url", default="http://localhost:8000", help="Backend API URL")
    parser.add_argument("--duration", type=int, default=300, help="Duration in seconds (default 300)")
    parser.add_argument("--auto", action="store_true", help="Non-interactive mode")
    parser.add_argument("--start-sim", action="store_true", default=True, help="Auto-start simulation if not running")
    args = parser.parse_args()

    # Detect Epson monitor
    monitors = detect_monitors_xrandr()
    if not monitors:
        print("❌ No monitors detected. Aborting.")
        return 1

    monitor = get_epson_monitor(monitors)
    if not monitor:
        if args.auto:
            # In auto mode, use first monitor as fallback
            monitor = monitors[0]
            print(f"⚠️  Epson not found, using fallback: {monitor.name}")
        else:
            monitor = prompt_fallback(monitors)
            if not monitor:
                print("❌ No monitor selected. Aborting.")
                return 1

    # Auto-start simulation if requested
    if args.start_sim:
        sim_status = _api_get(args.api_url, "/api/simulation/status")
        if not sim_status or (isinstance(sim_status, dict) and not sim_status.get("running")):
            print("  🚀 Starting simulation engine...")
            try:
                req = urllib.request.Request(
                    f"{args.api_url}/api/simulation/start",
                    method="POST",
                    data=json.dumps({"n_ticks": 5000, "speed": 10.0, "seed": 42}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    print(f"  ✅ Simulation started: {data.get('total_ticks')} ticks, speed={data.get('speed')}x")
            except Exception as e:
                print(f"  ⚠️  Could not start simulation: {e}")
        else:
            print(f"  ℹ️  Simulation already running: tick {sim_status.get('current_tick')}/{sim_status.get('total_ticks')}")

    report = run_stress_test(
        url=args.url,
        monitor=monitor,
        duration_s=args.duration,
        auto_mode=args.auto,
        api_url=args.api_url,
    )

    return 0 if report.overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
