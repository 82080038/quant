"""Agentic AI — autonomous development ecosystem.

Multi-agent system for autonomous software development:
  - AgentArchitect: designs logic, plans features, breaks down tasks
  - AgentCoder: reads/writes/modifies source files
  - AgentQA: runs Playwright E2E on Epson display, captures errors, debugs
  - AgenticOrchestrator: coordinates the full autonomous dev loop

ML Meta-Learning:
  - ErrorPatternLearner: clusters error logs, learns recurring patterns
  - SelfHealingPromptGenerator: generates LLM repair prompts from patterns

All agents use the existing LLMGateway (Ollama/OpenAI) for reasoning
and share a ToolRegistry for safe file I/O and terminal execution.
"""

from quant.agentic.base_agent import (
    BaseAgent,
    ToolRegistry,
    AgentContext,
    AgentResult,
    FileTools,
    TerminalTools,
)
from quant.agentic.architect_agent import AgentArchitect, ArchitecturePlan
from quant.agentic.coder_agent import AgentCoder, CodeChange
from quant.agentic.qa_agent import AgentQA, QAResult
from quant.agentic.orchestrator import AgenticOrchestrator, DevCycleResult
from quant.agentic.ml_meta import ErrorPatternLearner, SelfHealingPromptGenerator

__all__ = [
    "BaseAgent", "ToolRegistry", "AgentContext", "AgentResult",
    "FileTools", "TerminalTools",
    "AgentArchitect", "ArchitecturePlan",
    "AgentCoder", "CodeChange",
    "AgentQA", "QAResult",
    "AgenticOrchestrator", "DevCycleResult",
    "ErrorPatternLearner", "SelfHealingPromptGenerator",
]
