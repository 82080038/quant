"""Pipeline state machine for incremental processing.

Tracks each ticker's position in the modular pipeline:
  INGESTED → SCREENED → ANALYZED → SIGNAL_GENERATED → PORTFOLIO_OPTIMIZED → DONE
      ↘ FAILED (at any step, with error tracking for self-healing)
"""

from quant.pipeline.state_machine import PipelineStatus, PipelineTracker, STEP_LEVELS, TRANSITIONS
from quant.pipeline.orchestrator import PipelineOrchestrator, run_daily_pipeline

__all__ = ["PipelineStatus", "PipelineTracker", "STEP_LEVELS", "TRANSITIONS", "PipelineOrchestrator", "run_daily_pipeline"]
