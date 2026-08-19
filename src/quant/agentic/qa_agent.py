"""Agent QA — runs Playwright E2E on Epson display, captures errors, debugs.

The QA agent is the final agent in the autonomous dev loop. It:
  1. Runs the Playwright headed E2E suite (targeting Epson monitor)
  2. Captures console errors, network failures, page crashes
  3. If errors found, uses ML ErrorPatternLearner to classify them
  4. Generates a SelfHealingPrompt for the Coder to fix
  5. Returns QAResult with pass/fail + error details

Integrates with the existing scripts/e2e_playwright_headed.py and
scripts/monitor_detect.py for Epson display targeting.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quant.agentic.base_agent import BaseAgent, AgentContext, AgentResult

logger = logging.getLogger(__name__)

# Path to the E2E script (relative to project root)
_E2E_SCRIPT = "scripts/e2e_playwright_headed.py"
_MONITOR_SCRIPT = "scripts/monitor_detect.py"


@dataclass
class QAResult:
    """Structured QA result."""
    passed: bool
    total_scenarios: int
    passed_scenarios: int
    failed_scenarios: int
    errors: list[str] = field(default_factory=list)
    console_errors: list[dict] = field(default_factory=list)
    network_errors: list[dict] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    self_healing_prompt: str = ""
    report_path: str = ""


class AgentQA(BaseAgent):
    """Agent QA — runs E2E tests and debugs failures.

    Workflow:
      1. Verifies Epson monitor is available (via monitor_detect.py)
      2. Runs E2E Playwright suite in --auto mode
      3. Parses the JSON report for errors
      4. If errors found, uses ErrorPatternLearner to classify
      5. Generates SelfHealingPrompt for the Coder
    """

    name = "AgentQA"
    role = "qa"
    system_prompt = """You are a Senior QA Automation Engineer.
You analyze E2E test failures and produce actionable fix instructions.

Given a list of errors, output a JSON object:
{
  "root_cause": "primary cause of failures",
  "fix_instructions": "step-by-step instructions to fix",
  "files_to_fix": ["list of files that need changes"],
  "priority": "high|medium|low"
}

Focus on the root cause, not symptoms. Prioritize runtime errors over network warnings."""

    def execute(self, context: AgentContext) -> AgentResult:
        """Run E2E tests and analyze results."""
        # Step 1: Verify Epson monitor
        monitor_ok = self._verify_epson_monitor()
        if not monitor_ok:
            return self._result(
                success=False,
                output="Epson monitor not detected. QA cannot run headed browser.",
                errors=["Epson monitor not found"],
            )

        # Step 2: Run E2E suite
        e2e_result = self._run_e2e_suite()
        if not e2e_result["success"]:
            return self._result(
                success=False,
                output=f"E2E suite failed to execute: {e2e_result['stderr'][:500]}",
                errors=[e2e_result.get("stderr", "Unknown error")],
            )

        # Step 3: Parse report
        qa = self._parse_report(e2e_result.get("report_path", ""))
        if qa is None:
            return self._result(
                success=False,
                output="Failed to parse E2E report",
                errors=["Report parsing failed"],
            )

        # Step 4: If errors, generate self-healing prompt
        if not qa.passed and qa.errors:
            qa.self_healing_prompt = self._generate_healing_prompt(qa, context)

        output_lines = [
            f"QA Result: {'PASS' if qa.passed else 'FAIL'}",
            f"  Scenarios: {qa.passed_scenarios}/{qa.total_scenarios} passed",
            f"  Errors: {len(qa.errors)}",
        ]
        if qa.self_healing_prompt:
            output_lines.append(f"  Self-healing prompt generated ({len(qa.self_healing_prompt)} chars)")

        return self._result(
            success=qa.passed,
            output="\n".join(output_lines),
            artifacts=qa.screenshots,
            errors=qa.errors,
        )

    def _verify_epson_monitor(self) -> bool:
        """Check that Epson monitor is available."""
        result = self.tools.terminal.run(
            f"{self._python()} {_MONITOR_SCRIPT} --no-prompt",
            timeout=15,
        )
        if not result["success"]:
            logger.warning("Monitor detection failed: %s", result.get("stderr", ""))
            return False
        return "EPSON TARGET" in result.get("stdout", "")

    def _run_e2e_suite(self) -> dict:
        """Run the Playwright E2E suite in auto mode."""
        cmd = f"{self._python()} {_E2E_SCRIPT} --auto --no-start --url http://localhost:3000"
        result = self.tools.terminal.run(cmd, timeout=180)

        # Find report path in stdout
        report_path = ""
        for line in result.get("stdout", "").splitlines():
            if "Report saved:" in line:
                report_path = line.split("Report saved:")[-1].strip()
                break

        return {
            "success": result["success"],
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "report_path": report_path,
        }

    def _parse_report(self, report_path: str) -> QAResult | None:
        """Parse the JSON E2E report into QAResult."""
        if not report_path:
            return QAResult(
                passed=False,
                total_scenarios=0,
                passed_scenarios=0,
                failed_scenarios=0,
                errors=["No report file path found"],
            )

        try:
            # report_path may be absolute or relative to project root
            p = Path(report_path)
            if not p.is_absolute():
                p = self.tools.files.root / report_path
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return QAResult(
                passed=False,
                total_scenarios=0,
                passed_scenarios=0,
                failed_scenarios=0,
                errors=[f"Failed to read report: {e}"],
            )

        scenarios = data.get("scenarios", [])
        passed = sum(1 for s in scenarios if s["status"] == "PASS")
        failed = sum(1 for s in scenarios if s["status"] == "FAIL")
        all_errors = []
        console_errors = []
        network_errors = []

        for s in scenarios:
            if s["status"] == "FAIL":
                all_errors.extend(s.get("errors", []))
            console_errors.extend(s.get("console_errors", []))
            network_errors.extend(s.get("network_errors", []))

        return QAResult(
            passed=failed == 0 and passed > 0,
            total_scenarios=len(scenarios),
            passed_scenarios=passed,
            failed_scenarios=failed,
            errors=all_errors,
            console_errors=console_errors,
            network_errors=network_errors,
            screenshots=[s for sc in scenarios for s in sc.get("screenshots", [])],
            report_path=report_path,
        )

    def _generate_healing_prompt(self, qa: QAResult, context: AgentContext) -> str:
        """Generate a self-healing prompt for the Coder using LLM."""
        # Try ML-based prompt generation first
        try:
            from quant.agentic.ml_meta import SelfHealingPromptGenerator
            generator = SelfHealingPromptGenerator()
            prompt = generator.generate(qa.errors, qa.console_errors, qa.network_errors)
            if prompt:
                return prompt
        except Exception as e:
            logger.warning("ML prompt generation failed: %s", e)

        # Fallback: LLM-based
        error_summary = "\n".join(f"- {e}" for e in qa.errors[:10])
        user_prompt = f"""E2E Test Failures:
{error_summary}

Console errors: {json.dumps(qa.console_errors[:5], indent=2)}
Network errors: {json.dumps(qa.network_errors[:5], indent=2)}

Task context: {context.task}

Analyze the root cause and provide fix instructions."""

        resp = self._llm_complete(
            system=self.system_prompt,
            user=user_prompt,
            temperature=0.2,
            json_mode=True,
            max_tokens=2048,
        )

        if resp.success and resp.text:
            return resp.text

        # Final fallback: template
        return self._template_healing_prompt(qa)

    def _template_healing_prompt(self, qa: QAResult) -> str:
        """Template-based healing prompt when LLM is unavailable."""
        errors = qa.errors[:5]
        return json.dumps({
            "root_cause": errors[0] if errors else "Unknown",
            "fix_instructions": "Fix the errors listed above. Check stack traces for file paths and line numbers.",
            "files_to_fix": list(set(re.findall(r"[\w/]+\.py", " ".join(errors)))),
            "priority": "high",
        }, indent=2)

    def _python(self) -> str:
        """Get the venv python path."""
        venv_py = self.tools.files.root / ".venv" / "bin" / "python"
        return str(venv_py) if venv_py.exists() else sys.executable
