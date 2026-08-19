"""Analysis modules — causality, profiling, and instrument analysis."""

from quant.analysis.causality import (
    CausalityAnalyzer,
    CausalityResult,
    MatrixResult,
    compute_ccf_lag,
    granger_causality_test,
    fit_var_model,
)

__all__ = [
    "CausalityAnalyzer",
    "CausalityResult",
    "MatrixResult",
    "compute_ccf_lag",
    "granger_causality_test",
    "fit_var_model",
]
