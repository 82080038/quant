"""Agent Architect — designs logic, plans features, breaks down tasks.

The Architect is the first agent in the autonomous dev loop. It:
  1. Analyzes the task description and existing codebase structure
  2. Produces an ArchitecturePlan with step-by-step implementation plan
  3. Identifies which files need to be created/modified
  4. Defines acceptance criteria for QA

Uses LLM (via LLMGateway) for reasoning, with rule-based fallback.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from quant.agentic.base_agent import BaseAgent, AgentContext, AgentResult

logger = logging.getLogger(__name__)


@dataclass
class ImplementationStep:
    """A single step in the architecture plan."""
    step_number: int
    action: str  # "create", "modify", "delete", "test"
    file: str
    description: str
    acceptance_criteria: str


@dataclass
class ArchitecturePlan:
    """Output of AgentArchitect — a structured implementation plan."""
    summary: str
    steps: list[ImplementationStep] = field(default_factory=list)
    files_to_create: list[str] = field(default_factory=list)
    files_to_modify: list[str] = field(default_factory=list)
    test_strategy: str = ""
    risks: list[str] = field(default_factory=list)
    llm_rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "steps": [
                {
                    "step": s.step_number,
                    "action": s.action,
                    "file": s.file,
                    "description": s.description,
                    "acceptance_criteria": s.acceptance_criteria,
                }
                for s in self.steps
            ],
            "files_to_create": self.files_to_create,
            "files_to_modify": self.files_to_modify,
            "test_strategy": self.test_strategy,
            "risks": self.risks,
            "llm_rationale": self.llm_rationale,
        }


class AgentArchitect(BaseAgent):
    """Agent Architect — designs logic and plans implementation.

    Workflow:
      1. Scans existing project structure via FileTools
      2. Sends task + codebase context to LLM for planning
      3. Parses LLM response into structured ArchitecturePlan
      4. Falls back to rule-based planning if LLM unavailable
    """

    name = "AgentArchitect"
    role = "architect"
    system_prompt = """You are a Principal Software Architect.
You analyze tasks and produce structured implementation plans in JSON format.

Your output must be valid JSON with this schema:
{
  "summary": "Brief description of the approach",
  "steps": [
    {"step": 1, "action": "create|modify|delete|test", "file": "path/to/file", "description": "what to do", "acceptance_criteria": "how to verify"}
  ],
  "files_to_create": ["path/to/new/file"],
  "files_to_modify": ["path/to/existing/file"],
  "test_strategy": "How to verify the implementation",
  "risks": ["potential issues"]
}

Focus on minimal, clean changes. Prefer modifying existing files over creating new ones.
Always include a test step as the final step."""

    def execute(self, context: AgentContext) -> AgentResult:
        """Analyze task and produce ArchitecturePlan."""
        # Gather codebase context
        project_structure = self._scan_project()
        existing_files = self._identify_relevant_files(context.task, project_structure)

        # Build LLM prompt
        user_prompt = self._build_prompt(context, existing_files)

        llm_resp = self._llm_complete(
            system=self.system_prompt,
            user=user_prompt,
            temperature=0.2,
            json_mode=True,
            max_tokens=4096,
        )

        if llm_resp.success and llm_resp.parsed:
            plan = self._parse_llm_plan(llm_resp.parsed)
        else:
            # Fallback: rule-based plan
            plan = self._fallback_plan(context, existing_files, llm_resp.error or "")

        return self._result(
            success=True,
            output=json.dumps(plan.to_dict(), indent=2),
            artifacts=[],
            llm_response=llm_resp,
        )

    def _scan_project(self) -> dict:
        """Scan project structure for context."""
        try:
            entries = self.tools.files.list_dir(".")
            return {"root_entries": entries}
        except Exception as e:
            logger.warning("Project scan failed: %s", e)
            return {"root_entries": [], "error": str(e)}

    def _identify_relevant_files(self, task: str, structure: dict) -> list[str]:
        """Identify files relevant to the task using keyword matching."""
        keywords = [w.lower() for w in task.split() if len(w) > 3]
        relevant = []

        # Search for files matching task keywords
        for kw in keywords[:5]:  # limit to 5 keywords
            try:
                hits = self.tools.files.search(kw, file_glob="*.py")
                for h in hits[:3]:
                    if h["file"] not in relevant:
                        relevant.append(h["file"])
            except Exception:
                continue

        return relevant[:10]  # cap at 10 files

    def _build_prompt(self, context: AgentContext, relevant_files: list[str]) -> str:
        """Build the LLM prompt with task and codebase context."""
        file_contents = {}
        for f in relevant_files[:5]:
            try:
                content = self.tools.files.read(f)
                file_contents[f] = content[:2000]  # truncate to 2k chars
            except Exception:
                continue

        prompt = f"""Task: {context.task}

Project structure (root): {json.dumps(self._scan_project(), indent=2)}

Relevant existing files:
{json.dumps(file_contents, indent=2)}

Constraints:
{chr(10).join(f'- {c}' for c in context.constraints)}

Produce a detailed implementation plan as JSON."""
        return prompt

    def _parse_llm_plan(self, parsed: dict) -> ArchitecturePlan:
        """Parse LLM JSON response into ArchitecturePlan."""
        steps = []
        for s in parsed.get("steps", []):
            steps.append(ImplementationStep(
                step_number=s.get("step", len(steps) + 1),
                action=s.get("action", "modify"),
                file=s.get("file", ""),
                description=s.get("description", ""),
                acceptance_criteria=s.get("acceptance_criteria", ""),
            ))

        return ArchitecturePlan(
            summary=parsed.get("summary", ""),
            steps=steps,
            files_to_create=parsed.get("files_to_create", []),
            files_to_modify=parsed.get("files_to_modify", []),
            test_strategy=parsed.get("test_strategy", ""),
            risks=parsed.get("risks", []),
            llm_rationale=parsed.get("summary", ""),
        )

    def _fallback_plan(
        self, context: AgentContext, relevant_files: list[str], error: str
    ) -> ArchitecturePlan:
        """Rule-based fallback plan when LLM is unavailable."""
        steps = [
            ImplementationStep(
                step_number=1,
                action="modify",
                file=relevant_files[0] if relevant_files else "src/quant/main.py",
                description=f"Implement: {context.task}",
                acceptance_criteria="Code runs without errors",
            ),
            ImplementationStep(
                step_number=2,
                action="test",
                file="tests/",
                description="Run existing test suite to verify no regressions",
                acceptance_criteria="All tests pass",
            ),
        ]
        return ArchitecturePlan(
            summary=f"Fallback plan for: {context.task} (LLM unavailable: {error})",
            steps=steps,
            files_to_modify=relevant_files[:3],
            test_strategy="Run pytest suite",
            risks=["LLM not available — plan is heuristic only"],
            llm_rationale="",
        )
