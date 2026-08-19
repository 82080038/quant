"""Agentic Orchestrator — coordinates the autonomous development loop.

The orchestrator runs the full cycle:
  Architect → Coder → QA → (if fail) ML analysis → Coder retry → QA retry

It manages the loop budget (max retries, max cycles) and produces
a DevCycleResult with the full trace of agent interactions.

Usage:
    from quant.agentic.orchestrator import AgenticOrchestrator
    from quant.agentic.base_agent import ToolRegistry, AgentContext

    tools = ToolRegistry.create()
    orch = AgenticOrchestrator(tools=tools)

    result = orch.run(
        task="Add /api/portfolio endpoint to backend",
        target_files=["src/quant/api/app.py"],
    )
    if result.success:
        print("Feature implemented successfully!")
    else:
        print(f"Failed: {result.errors}")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from quant.agentic.base_agent import (
    BaseAgent, ToolRegistry, AgentContext, AgentResult,
)
from quant.agentic.architect_agent import AgentArchitect
from quant.agentic.coder_agent import AgentCoder
from quant.agentic.qa_agent import AgentQA

logger = logging.getLogger(__name__)


@dataclass
class DevCycleResult:
    """Final result of a complete autonomous development cycle."""
    task: str
    success: bool
    cycles: int
    architect_result: AgentResult | None = None
    coder_results: list[AgentResult] = field(default_factory=list)
    qa_results: list[AgentResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    total_duration_s: float = 0.0

    def summary(self) -> str:
        lines = [
            f"Dev Cycle: {'SUCCESS' if self.success else 'FAILURE'}",
            f"  Task: {self.task}",
            f"  Cycles: {self.cycles}",
            f"  Duration: {self.total_duration_s:.1f}s",
            f"  Coder turns: {len(self.coder_results)}",
            f"  QA turns: {len(self.qa_results)}",
        ]
        if self.errors:
            lines.append(f"  Errors: {len(self.errors)}")
            for e in self.errors[:3]:
                lines.append(f"    - {e[:100]}")
        return "\n".join(lines)


class AgenticOrchestrator:
    """Coordinates the Architect → Coder → QA autonomous dev loop.

    Args:
        tools: ToolRegistry with file/terminal/LLM access
        max_retries: Max QA→Coder retry loops per cycle (default: 3)
        max_cycles: Max independent dev cycles (default: 1)

    Workflow per cycle:
      1. Architect analyzes task → produces ArchitecturePlan
      2. Coder implements plan → produces CodeChanges
      3. QA runs E2E tests → produces QAResult
      4. If QA fails and retries remain:
         - QA generates self-healing prompt
         - Coder receives prompt as new context → re-implements
         - QA re-runs
      5. If QA passes → success. If retries exhausted → failure.
    """

    def __init__(
        self,
        tools: ToolRegistry,
        max_retries: int = 3,
        max_cycles: int = 1,
    ):
        self.tools = tools
        self.max_retries = max_retries
        self.max_cycles = max_cycles

        self.architect = AgentArchitect(tools=tools)
        self.coder = AgentCoder(tools=tools)
        self.qa = AgentQA(tools=tools)

    def run(
        self,
        task: str,
        target_files: list[str] | None = None,
        constraints: list[str] | None = None,
    ) -> DevCycleResult:
        """Run the full autonomous development cycle.

        Args:
            task: Natural language task description
            target_files: Files that should be modified
            constraints: Additional constraints for the agents

        Returns:
            DevCycleResult with full trace
        """
        import time
        start = time.time()
        started_at = datetime.now().isoformat()

        all_errors: list[str] = []
        coder_results: list[AgentResult] = []
        qa_results: list[AgentResult] = []
        architect_result: AgentResult | None = None
        success = False

        for cycle in range(1, self.max_cycles + 1):
            logger.info("Starting dev cycle %d/%d: %s", cycle, self.max_cycles, task)

            # Build context
            context = AgentContext(
                task=task,
                project_root=self.tools.files.root,
                target_files=target_files or [],
                constraints=constraints or [],
                previous_results=[],
                cycle_id=f"cycle_{cycle}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            )

            # Step 1: Architect
            logger.info("  ▶ Architect analyzing task...")
            architect_result = self.architect.execute(context)
            context.previous_results.append(architect_result)

            if not architect_result.success:
                all_errors.append(f"Architect failed: {architect_result.errors}")
                continue

            # Step 2: Coder (initial implementation)
            logger.info("  ▶ Coder implementing plan...")
            coder_result = self.coder.execute(context)
            coder_results.append(coder_result)
            context.previous_results.append(coder_result)

            if not coder_result.success:
                all_errors.extend(coder_result.errors)

            # Step 3: QA + retry loop
            for retry in range(1, self.max_retries + 1):
                logger.info("  ▶ QA run %d/%d...", retry, self.max_retries)
                qa_result = self.qa.execute(context)
                qa_results.append(qa_result)
                context.previous_results.append(qa_result)

                if qa_result.success:
                    success = True
                    logger.info("  ✅ QA passed on attempt %d", retry)
                    break

                logger.warning("  ❌ QA failed on attempt %d: %s", retry, qa_result.errors[:3])

                if retry < self.max_retries:
                    # Coder retries with self-healing context
                    logger.info("  ▶ Coder retrying with self-healing context...")
                    retry_result = self.coder.execute(context)
                    coder_results.append(retry_result)
                    context.previous_results.append(retry_result)
                else:
                    all_errors.append(f"QA failed after {self.max_retries} retries")
                    all_errors.extend(qa_result.errors)

            if success:
                break

        duration = time.time() - start
        return DevCycleResult(
            task=task,
            success=success,
            cycles=cycle,
            architect_result=architect_result,
            coder_results=coder_results,
            qa_results=qa_results,
            errors=all_errors,
            started_at=started_at,
            finished_at=datetime.now().isoformat(),
            total_duration_s=duration,
        )
