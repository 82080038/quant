"""Base agent framework — tools, context, and agent lifecycle.

Provides:
  - FileTools: cross-platform file read/write/modify (safe, sandboxed to project root)
  - TerminalTools: execute shell commands with timeout and capture
  - ToolRegistry: central registry agents use to access tools
  - BaseAgent: abstract base with LLM integration via existing LLMGateway
  - AgentContext: per-cycle context (task description, working files, constraints)
  - AgentResult: structured output from each agent turn

Security: all file operations are constrained to the project root directory.
Terminal commands are validated against a blocklist (no rm -rf, no sudo).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from quant.ai.llm_gateway import LLMGateway, LLMResponse

logger = logging.getLogger(__name__)

# Project root = 3 levels up from this file (src/quant/agentic/base_agent.py)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Commands that must never be executed
_BLOCKED_COMMANDS = [
    r"\brm\s+-rf\s+/",
    r"\bsudo\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r":\(\)\s*\{",  # fork bomb
]


def _is_command_safe(cmd: str) -> bool:
    """Validate command against blocklist."""
    for pattern in _BLOCKED_COMMANDS:
        if re.search(pattern, cmd):
            return False
    return True


def _is_path_safe(path: Path, root: Path) -> bool:
    """Ensure path is within the project root (no path traversal)."""
    try:
        resolved = path.resolve()
        return str(resolved).startswith(str(root.resolve()))
    except (OSError, ValueError):
        return False


# ── File Tools ────────────────────────────────────────────────────────────

class FileTools:
    """Cross-platform file operations sandboxed to project root."""

    def __init__(self, root: Path | None = None):
        self.root = (root or _PROJECT_ROOT).resolve()

    def read(self, rel_path: str) -> str:
        """Read a file within the project."""
        path = self.root / rel_path
        if not _is_path_safe(path, self.root):
            raise ValueError(f"Path outside project root: {rel_path}")
        if not path.exists():
            raise FileNotFoundError(f"File not found: {rel_path}")
        return path.read_text(encoding="utf-8")

    def read_lines(self, rel_path: str, start: int = 1, end: int | None = None) -> str:
        """Read specific line range from a file (1-indexed)."""
        content = self.read(rel_path)
        lines = content.splitlines(keepends=True)
        start_idx = max(0, start - 1)
        end_idx = end if end else len(lines)
        return "".join(lines[start_idx:end_idx])

    def write(self, rel_path: str, content: str) -> str:
        """Write a new file (or overwrite) within the project."""
        path = self.root / rel_path
        if not _is_path_safe(path, self.root):
            raise ValueError(f"Path outside project root: {rel_path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {rel_path}"

    def edit(self, rel_path: str, old_text: str, new_text: str) -> str:
        """Replace first occurrence of old_text with new_text in a file."""
        content = self.read(rel_path)
        if old_text not in content:
            raise ValueError(f"old_text not found in {rel_path}")
        updated = content.replace(old_text, new_text, 1)
        path = self.root / rel_path
        path.write_text(updated, encoding="utf-8")
        return f"Edited {rel_path}: replaced {len(old_text)} chars"

    def list_dir(self, rel_path: str = ".") -> list[str]:
        """List directory contents within the project."""
        path = self.root / rel_path
        if not _is_path_safe(path, self.root):
            raise ValueError(f"Path outside project root: {rel_path}")
        if not path.is_dir():
            raise NotADirectoryError(f"Not a directory: {rel_path}")
        return sorted([str(p.relative_to(self.root)) for p in path.iterdir()])

    def exists(self, rel_path: str) -> bool:
        """Check if a file exists within the project."""
        return (self.root / rel_path).exists()

    def search(self, pattern: str, file_glob: str = "*.py") -> list[dict]:
        """Search for a text pattern across project files."""
        import fnmatch
        results = []
        for root, dirs, files in os.walk(self.root):
            # Skip hidden dirs, __pycache__, node_modules, .git
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules", ".git")]
            for fname in files:
                if not fnmatch.fnmatch(fname, file_glob):
                    continue
                fpath = Path(root) / fname
                try:
                    for i, line in enumerate(fpath.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                        if pattern in line:
                            results.append({
                                "file": str(fpath.relative_to(self.root)),
                                "line": i,
                                "text": line.strip()[:200],
                            })
                except (OSError, UnicodeDecodeError):
                    continue
        return results


# ── Terminal Tools ────────────────────────────────────────────────────────

class TerminalTools:
    """Cross-platform terminal command execution with safety checks."""

    def __init__(self, cwd: Path | None = None, timeout: int = 120):
        self.cwd = str(cwd or _PROJECT_ROOT)
        self.timeout = timeout

    def run(self, command: str, timeout: int | None = None) -> dict:
        """Execute a shell command and return structured output.

        Returns:
            {"success": bool, "stdout": str, "stderr": str, "returncode": int}
        """
        if not _is_command_safe(command):
            return {
                "success": False,
                "stdout": "",
                "stderr": f"BLOCKED: command failed safety check: {command}",
                "returncode": -1,
            }

        # Use venv python if available
        venv_python = str(Path(self.cwd) / ".venv" / "bin" / "python")
        env = os.environ.copy()
        if Path(venv_python).exists():
            env["PYTHON"] = venv_python

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                cwd=self.cwd,
                env=env,
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Command timed out after {timeout or self.timeout}s",
                "returncode": -1,
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
            }


# ── Tool Registry ─────────────────────────────────────────────────────────

@dataclass
class ToolRegistry:
    """Central registry for agent tools."""
    files: FileTools = field(default_factory=FileTools)
    terminal: TerminalTools = field(default_factory=TerminalTools)
    gateway: Optional[LLMGateway] = None

    @classmethod
    def create(cls, project_root: Path | None = None, gateway: LLMGateway | None = None) -> "ToolRegistry":
        root = (project_root or _PROJECT_ROOT).resolve()
        return cls(
            files=FileTools(root=root),
            terminal=TerminalTools(cwd=root),
            gateway=gateway or LLMGateway(),
        )


# ── Agent Context & Result ────────────────────────────────────────────────

@dataclass
class AgentContext:
    """Per-cycle context passed between agents."""
    task: str
    project_root: Path
    target_files: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    previous_results: list["AgentResult"] = field(default_factory=list)
    cycle_id: str = field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Structured output from an agent turn."""
    agent_name: str
    success: bool
    output: str
    artifacts: list[str] = field(default_factory=list)  # files created/modified
    errors: list[str] = field(default_factory=list)
    llm_used: bool = False
    llm_response: Optional[LLMResponse] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ── Base Agent ────────────────────────────────────────────────────────────

class BaseAgent:
    """Abstract base for autonomous agents.

    Each agent has:
      - A name and role description
      - Access to ToolRegistry (files, terminal, LLM)
      - A system prompt that defines its persona
      - An `execute()` method that processes context and returns AgentResult
    """

    name: str = "BaseAgent"
    role: str = "base"
    system_prompt: str = "You are a helpful AI assistant."

    def __init__(self, tools: ToolRegistry):
        self.tools = tools

    def _llm_complete(self, system: str, user: str, **kwargs) -> LLMResponse:
        """Call LLM via gateway with fallback."""
        if self.tools.gateway is None:
            return LLMResponse(
                text="", model="none", latency_ms=0,
                success=False, error="No LLM gateway configured",
            )
        return self.tools.gateway.complete(system=system, user=user, **kwargs)

    def execute(self, context: AgentContext) -> AgentResult:
        """Process context and produce result. Override in subclasses."""
        raise NotImplementedError(f"{self.name}.execute() not implemented")

    def _result(
        self,
        success: bool,
        output: str,
        artifacts: list[str] | None = None,
        errors: list[str] | None = None,
        llm_response: LLMResponse | None = None,
    ) -> AgentResult:
        return AgentResult(
            agent_name=self.name,
            success=success,
            output=output,
            artifacts=artifacts or [],
            errors=errors or [],
            llm_used=llm_response is not None and llm_response.success,
            llm_response=llm_response,
        )
