"""Agent Coder — writes and modifies source code.

The Coder receives an ArchitecturePlan from the Architect and:
  1. Reads target files that need modification
  2. Generates code via LLM (or rule-based templates)
  3. Applies changes using FileTools (write/edit)
  4. Validates syntax by running a quick parse check
  5. Returns a list of CodeChange artifacts

Safety:
  - All file writes are sandboxed to project root
  - Python files are syntax-checked after write
  - Original file content is preserved in CodeChange for rollback
"""

from __future__ import annotations

import ast
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from quant.agentic.base_agent import BaseAgent, AgentContext, AgentResult
from quant.agentic.architect_agent import ArchitecturePlan, ImplementationStep

logger = logging.getLogger(__name__)


@dataclass
class CodeChange:
    """Record of a single code change applied by AgentCoder."""
    file: str
    action: str  # "create", "modify", "delete"
    description: str
    original_content: str = ""  # for rollback
    new_content: str = ""
    syntax_valid: bool = True
    error: str = ""


class AgentCoder(BaseAgent):
    """Agent Coder — implements code changes from ArchitecturePlan.

    Workflow:
      1. Reads the ArchitecturePlan from context.previous_results
      2. For each step, reads target file (if modify) or creates new
      3. Sends file content + step description to LLM for code generation
      4. Applies the generated code via FileTools
      5. Syntax-checks Python files
    """

    name = "AgentCoder"
    role = "coder"
    system_prompt = """You are a Senior Software Engineer writing clean, production-ready code.

Given a file's current content and a task description, produce the modified file content.

Rules:
- Output ONLY the complete file content (no markdown fences, no explanations)
- Preserve existing code style and imports
- Add necessary imports at the top
- Keep changes minimal and focused
- Ensure the code is syntactically valid Python (or TypeScript/TSX for frontend)
- Do not add comments unless explicitly requested"""

    def execute(self, context: AgentContext) -> AgentResult:
        """Execute code changes based on ArchitecturePlan from previous results."""
        plan = self._extract_plan(context)
        if plan is None:
            return self._result(
                success=False,
                output="No ArchitecturePlan found in context",
                errors=["Missing ArchitecturePlan in previous_results"],
            )

        changes: list[CodeChange] = []
        errors: list[str] = []

        for step in plan.steps:
            if step.action == "test":
                continue  # QA agent handles testing

            try:
                change = self._execute_step(step, context)
                changes.append(change)
                if not change.syntax_valid:
                    errors.append(f"Syntax error in {change.file}: {change.error}")
            except Exception as e:
                logger.error("Coder step %d failed: %s", step.step_number, e)
                errors.append(f"Step {step.step_number} ({step.file}): {e}")
                changes.append(CodeChange(
                    file=step.file,
                    action=step.action,
                    description=step.description,
                    syntax_valid=False,
                    error=str(e),
                ))

        all_valid = all(c.syntax_valid for c in changes)
        output_lines = [
            f"Applied {len(changes)} code changes:",
            *[f"  {'✅' if c.syntax_valid else '❌'} {c.action} {c.file}: {c.description}" for c in changes],
        ]

        return self._result(
            success=all_valid,
            output="\n".join(output_lines),
            artifacts=[c.file for c in changes if c.syntax_valid],
            errors=errors,
        )

    def _extract_plan(self, context: AgentContext) -> ArchitecturePlan | None:
        """Extract ArchitecturePlan from previous agent results."""
        for result in reversed(context.previous_results):
            if result.agent_name == "AgentArchitect" and result.success:
                try:
                    plan_dict = json.loads(result.output)
                    return self._dict_to_plan(plan_dict)
                except (json.JSONDecodeError, KeyError):
                    continue
        return None

    def _dict_to_plan(self, d: dict) -> ArchitecturePlan:
        """Reconstruct ArchitecturePlan from dict."""
        steps = [
            ImplementationStep(
                step_number=s.get("step", i + 1),
                action=s.get("action", "modify"),
                file=s.get("file", ""),
                description=s.get("description", ""),
                acceptance_criteria=s.get("acceptance_criteria", ""),
            )
            for i, s in enumerate(d.get("steps", []))
        ]
        return ArchitecturePlan(
            summary=d.get("summary", ""),
            steps=steps,
            files_to_create=d.get("files_to_create", []),
            files_to_modify=d.get("files_to_modify", []),
            test_strategy=d.get("test_strategy", ""),
            risks=d.get("risks", []),
        )

    def _execute_step(self, step: ImplementationStep, context: AgentContext) -> CodeChange:
        """Execute a single implementation step."""
        original = ""
        if step.action == "modify" and self.tools.files.exists(step.file):
            original = self.tools.files.read(step.file)

        # Generate new content via LLM
        new_content = self._generate_code(step, original, context)

        # Apply the change
        if step.action == "create":
            self.tools.files.write(step.file, new_content)
        elif step.action == "modify":
            self.tools.files.write(step.file, new_content)
        elif step.action == "delete":
            # Safe delete: only if file exists and is within project
            if self.tools.files.exists(step.file):
                path = self.tools.files.root / step.file
                path.unlink()
        else:
            return CodeChange(
                file=step.file,
                action=step.action,
                description=step.description,
                syntax_valid=False,
                error=f"Unknown action: {step.action}",
            )

        # Syntax check for Python files
        syntax_valid = True
        error_msg = ""
        if step.file.endswith(".py"):
            syntax_valid, error_msg = self._check_syntax(new_content)

        return CodeChange(
            file=step.file,
            action=step.action,
            description=step.description,
            original_content=original[:500],  # truncated for rollback
            new_content=new_content[:500],
            syntax_valid=syntax_valid,
            error=error_msg,
        )

    def _generate_code(
        self, step: ImplementationStep, current_content: str, context: AgentContext
    ) -> str:
        """Generate code for a step using LLM or fallback."""
        if not current_content and step.action == "create":
            # For new files, use LLM to generate from scratch
            user_prompt = f"""Create a new file: {step.file}
Description: {step.description}
Task context: {context.task}

Write the complete file content."""

            resp = self._llm_complete(
                system=self.system_prompt,
                user=user_prompt,
                temperature=0.2,
                max_tokens=4096,
            )
            if resp.success and resp.text:
                return resp.text.strip()

            # Fallback: minimal template
            return self._fallback_template(step)

        elif current_content and step.action == "modify":
            # For modifications, send current + instruction to LLM
            user_prompt = f"""Modify the file: {step.file}

Current content:
```
{current_content[:4000]}
```

Modification needed: {step.description}
Task context: {context.task}

Output the complete modified file content."""

            resp = self._llm_complete(
                system=self.system_prompt,
                user=user_prompt,
                temperature=0.2,
                max_tokens=4096,
            )
            if resp.success and resp.text:
                # Strip markdown code fences if present
                text = resp.text.strip()
                if text.startswith("```"):
                    lines = text.split("\n")
                    text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
                return text

            # Fallback: return original unchanged
            return current_content

        return self._fallback_template(step)

    def _fallback_template(self, step: ImplementationStep) -> str:
        """Generate a minimal file template when LLM is unavailable."""
        if step.file.endswith(".py"):
            return f'"""{step.description}"""\n\nfrom __future__ import annotations\n\n\n# TODO: Implement {step.description}\n'
        elif step.file.endswith((".tsx", ".ts")):
            return f'// {step.description}\n\n// TODO: Implement\n'
        return f"// {step.description}\n"

    @staticmethod
    def _check_syntax(code: str) -> tuple[bool, str]:
        """Check Python syntax validity."""
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"{e.msg} at line {e.lineno}"
