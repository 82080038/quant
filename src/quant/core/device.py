"""Dynamic compute device dispatcher: CPU vs ``cuda:1``.

Hardware target: 2x NVIDIA GeForce GTX 1050 Ti (4 GB VRAM each, Pascal GP107,
compute capability 6.1). GPU 0 is used by the display, so heavy compute
**must** prefer ``cuda:1`` per AGENTS.md §2 ("GPU/CUDA") and §4.

The problem this module solves: for small data the CPU is faster than the GPU
because of host<->device transfer overhead; for large data the GPU wins.
Additionally, blindly calling ``.to("cuda:1")`` without a VRAM check risks
out-of-memory errors on a 4 GB card. This module profiles/benchmarks the
workload and chooses the optimal device based on workload type, data size, and
available VRAM.

References:
    - AGENTS.md §2 (GPU/CUDA) and §4 (Context & Memory).
    - pustaka/34-performance-engineering-optimization.md (Profiling &
      Benchmarking, Memory Management).

Usage::

    from quant.compute.device import DeviceContext, select_device

    device = select_device("lstm_training", data_size=50_000)
    with DeviceContext("lstm_training", data_size=50_000) as ctx:
        x = ctx.to(my_tensor)
        ...
"""

from __future__ import annotations

import logging
import statistics
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass, field
from typing import Any, TypeVar

__all__ = [
    "BenchmarkResult",
    "DeviceContext",
    "WorkloadProfile",
    "auto_select_device",
    "benchmark_workload",
    "estimate_vram",
    "select_device",
    "vram_available",
    "vram_available_for",
]

logger = logging.getLogger(__name__)

# ── torch import (optional) ──────────────────────────────────────────────
# torch may not be installed in every environment (CI, docs build). Import
# lazily so the module can still be imported and the CPU-only paths still
# work. Functions that genuinely need torch check for ``None`` and degrade
# gracefully.
try:  # pragma: no cover - import side effect
    import torch

    _TORCH_AVAILABLE = True
except Exception:  # pragma: no cover - torch genuinely missing
    torch = None  # type: ignore[assignment]
    _TORCH_AVAILABLE = False

# Preferred GPU per AGENTS.md §2: GPU 0 drives the display, use cuda:1.
PREFERRED_GPU = "cuda:1"
PREFERRED_GPU_INDEX = 1

# Safety margin applied when checking whether a workload fits in free VRAM.
# 20% headroom to absorb fragmentation and intermediate buffers.
VRAM_SAFETY_MARGIN = 0.20

# Bytes per element for common torch dtypes. Falls back to float32 size when
# the dtype is unknown (e.g. a non-torch dtype passed in for estimation).
_DTYPE_BYTES: dict[Any, int] = {}
if _TORCH_AVAILABLE:
    _DTYPE_BYTES.update(
        {
            torch.float16: 2,
            torch.bfloat16: 2,
            torch.float32: 4,
            torch.float64: 8,
            torch.int8: 1,
            torch.int16: 2,
            torch.int32: 4,
            torch.int64: 8,
            torch.bool: 1,
        }
    )

# Default bytes-per-element when dtype is not recognised.
_DEFAULT_DTYPE_BYTES = 4

# Workload classification.
# CPU-native workloads are always run on the CPU regardless of data size.
_CPU_NATIVE_WORKLOADS: frozenset[str] = frozenset(
    {
        "pandas_groupby",
        "lightgbm",
    }
)

# GPU-friendly workloads that benefit from cuda:1 once data is large enough.
_GPU_FRIENDLY_WORKLOADS: frozenset[str] = frozenset(
    {
        "lstm_training",
        "lstm_inference",
        "correlation_matrix",
        "monte_carlo",
        "var_simulation",
        "matrix_multiply",
        "walk_forward",
        "nlp_sentiment",
        "relationship_matrix",
        "technical_indicators",
        "ml_labels",
        "market_regimes",
    }
)

# Minimum data size (rows / elements) below which GPU transfer overhead is not
# worth it. Tuned for GTX 1050 Ti (Pascal, PCIe gen3) — small payloads spend
# more time on the bus than on compute.
_MIN_GPU_THRESHOLD: dict[str, int] = {
    "lstm_training": 10_000,
    "lstm_inference": 1_000,
    "correlation_matrix": 2_000,
    "monte_carlo": 50_000,
    "var_simulation": 50_000,
    "matrix_multiply": 2_000,
    "walk_forward": 10_000,
    "nlp_sentiment": 1_000,
    "relationship_matrix": 5_000,
    "technical_indicators": 10_000,
    "ml_labels": 50_000,
    "market_regimes": 5_000,
}
_DEFAULT_MIN_GPU_THRESHOLD = 1_000

# Rough VRAM cost multiplier per workload type relative to the raw tensor size.
# E.g. LSTM training keeps gradients + optimizer state (~4x the params).
_VRAM_MULTIPLIER: dict[str, float] = {
    "lstm_training": 4.0,
    "lstm_inference": 1.5,
    "correlation_matrix": 2.0,  # NxN output
    "monte_carlo": 1.5,
    "var_simulation": 1.5,
    "matrix_multiply": 2.0,  # inputs + output
    "walk_forward": 2.0,
    "nlp_sentiment": 3.0,  # model activations
    "relationship_matrix": 2.0,  # NxN correlation
    "technical_indicators": 1.5,  # per-ticker rolling windows
    "ml_labels": 1.5,  # per-ticker barrier computation
    "market_regimes": 2.0,  # regime classification matrix
}


T = TypeVar("T")
ShapeLike = tuple[int, ...] | int


# ── Dataclasses ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class WorkloadProfile:
    """Static profile describing how a workload type maps to devices."""

    workload_type: str
    cpu_native: bool
    gpu_friendly: bool
    min_gpu_threshold: int
    vram_multiplier: float


@dataclass
class BenchmarkResult:
    """Result of benchmarking a callable on a device."""

    device: str
    times: list[float] = field(default_factory=list)

    @property
    def median(self) -> float:
        """Median wall-clock time in seconds across runs."""
        return statistics.median(self.times) if self.times else float("inf")

    @property
    def mean(self) -> float:
        """Mean wall-clock time in seconds across runs."""
        return statistics.fmean(self.times) if self.times else float("inf")


# ── Workload profile registry ────────────────────────────────────────────
def _workload_profile(workload_type: str) -> WorkloadProfile:
    """Return the static profile for a workload type.

    Unknown workload types default to a conservative GPU-friendly profile so
    callers can still use the dispatcher without registering every type.
    """
    return WorkloadProfile(
        workload_type=workload_type,
        cpu_native=workload_type in _CPU_NATIVE_WORKLOADS,
        gpu_friendly=workload_type in _GPU_FRIENDLY_WORKLOADS,
        min_gpu_threshold=_MIN_GPU_THRESHOLD.get(
            workload_type, _DEFAULT_MIN_GPU_THRESHOLD
        ),
        vram_multiplier=_VRAM_MULTIPLIER.get(workload_type, 2.0),
    )


# ── VRAM helpers ─────────────────────────────────────────────────────────
def _device_index(device: str) -> int:
    """Parse a ``cuda:N`` device string into an integer index."""
    try:
        return int(device.split(":")[1])
    except (IndexError, ValueError):
        return 0


def vram_available(device: str = PREFERRED_GPU) -> tuple[float, float]:
    """Return ``(free_mb, total_mb)`` for the given CUDA device.

    Uses ``torch.cuda.mem_get_info`` which reports free/total VRAM in bytes.

    Args:
        device: Device string such as ``"cuda:1"``.

    Returns:
        ``(free_mb, total_mb)``. Returns ``(0.0, 0.0)`` when CUDA is not
        available or the device index is out of range, so callers can treat
        the GPU as "unusable" without raising.
    """
    if not _TORCH_AVAILABLE or not torch.cuda.is_available():
        logger.debug("CUDA unavailable; reporting 0 VRAM for %s", device)
        return (0.0, 0.0)
    idx = _device_index(device)
    if idx < 0 or idx >= torch.cuda.device_count():
        logger.warning("CUDA device %s out of range (count=%d)", device, torch.cuda.device_count())
        return (0.0, 0.0)
    try:
        free_bytes, total_bytes = torch.cuda.mem_get_info(idx)
    except RuntimeError as exc:  # pragma: no cover - hardware specific
        logger.warning("mem_get_info failed for %s: %s", device, exc)
        return (0.0, 0.0)
    return (free_bytes / (1024 * 1024), total_bytes / (1024 * 1024))


def vram_available_for(needed_mb: float, device: str = PREFERRED_GPU) -> bool:
    """Check whether ``needed_mb`` fits in free VRAM with a safety margin.

    The safety margin (``VRAM_SAFETY_MARGIN``, 20%) is subtracted from the
    free VRAM before the comparison to absorb fragmentation and intermediate
    buffers — important on a 4 GB card where headroom is tight.

    Args:
        needed_mb: VRAM required for the workload, in megabytes.
        device: Device string such as ``"cuda:1"``.

    Returns:
        ``True`` if the workload fits, ``False`` otherwise (including when
        CUDA is unavailable).
    """
    free_mb, _total_mb = vram_available(device)
    usable = free_mb * (1.0 - VRAM_SAFETY_MARGIN)
    fits = needed_mb <= usable
    logger.debug(
        "vram_available_for: needed=%.1fMB free=%.1fMB usable=%.1fMB fits=%s",
        needed_mb,
        free_mb,
        usable,
        fits,
    )
    return fits


def estimate_vram(
    shape: ShapeLike,
    dtype: Any = None,
) -> float:
    """Estimate the VRAM (in MB) needed for a tensor of ``shape`` and ``dtype``.

    Args:
        shape: Either a tuple of ints (tensor shape) or a single int
            interpreted as the total number of elements.
        dtype: A torch dtype (e.g. ``torch.float32``) or ``None`` to default
            to float32 (4 bytes/element).

    Returns:
        Estimated memory in megabytes.

    References:
        - pustaka/34-performance-engineering-optimization.md §6 (Memory
          Management).
    """
    if isinstance(shape, int):
        n_elements = shape
    else:
        n_elements = 1
        for dim in shape:
            n_elements *= int(dim)
    bytes_per = _DTYPE_BYTES.get(dtype, _DEFAULT_DTYPE_BYTES) if dtype else _DEFAULT_DTYPE_BYTES
    total_bytes = n_elements * bytes_per
    return total_bytes / (1024 * 1024)


# ── Device selection ─────────────────────────────────────────────────────
def select_device(
    workload_type: str,
    data_size: int,
    estimated_vram_mb: float | None = None,
) -> str:
    """Choose the optimal device (``"cpu"`` or ``"cuda:1"``) for a workload.

    Decision order:

    1. **CPU-native workloads** (``pandas_groupby``, ``lightgbm``) always run
       on the CPU.
    2. **Small data**: if ``data_size`` is below the workload's minimum GPU
       threshold, return ``"cpu"`` — transfer overhead dominates.
    3. **No CUDA**: if torch/CUDA is unavailable or ``cuda:1`` is missing,
       return ``"cpu"``.
    4. **VRAM check**: if ``estimated_vram_mb`` is provided and does not fit
       in free VRAM (with safety margin), return ``"cpu"`` to avoid OOM.
    5. Otherwise return ``"cuda:1"``.

    Args:
        workload_type: One of the known workload types (see module docstring).
            Unknown types are treated as GPU-friendly with conservative
            defaults.
        data_size: Number of rows / elements in the workload.
        estimated_vram_mb: Optional pre-computed VRAM estimate in MB. When
            ``None`` the VRAM check is skipped (caller takes responsibility).

    Returns:
        ``"cpu"`` or ``"cuda:1"``.

    References:
        - AGENTS.md §2 (GPU/CUDA) — prefer ``cuda:1``.
        - pustaka/34-performance-engineering-optimization.md §9 (Profiling &
          Benchmarking) and §6 (Memory Management).
    """
    profile = _workload_profile(workload_type)

    # 1. CPU-native workloads never go to the GPU.
    if profile.cpu_native:
        logger.debug("select_device: %s is CPU-native -> cpu", workload_type)
        return "cpu"

    # 2. Small data: transfer overhead not worth it.
    if data_size < profile.min_gpu_threshold:
        logger.debug(
            "select_device: %s data_size=%d < threshold=%d -> cpu",
            workload_type,
            data_size,
            profile.min_gpu_threshold,
        )
        return "cpu"

    # 3. CUDA availability.
    if not _TORCH_AVAILABLE or not torch.cuda.is_available():
        logger.debug("select_device: CUDA unavailable -> cpu")
        return "cpu"
    idx = _device_index(PREFERRED_GPU)
    if idx >= torch.cuda.device_count():
        logger.debug(
            "select_device: %s missing (count=%d) -> cpu",
            PREFERRED_GPU,
            torch.cuda.device_count(),
        )
        return "cpu"

    # 4. VRAM check (only when caller supplied an estimate).
    if estimated_vram_mb is not None:
        # Apply the workload multiplier to account for intermediates.
        needed = estimated_vram_mb * profile.vram_multiplier
        if not vram_available_for(needed, PREFERRED_GPU):
            logger.debug(
                "select_device: %s needs %.1fMB (x%.1f) but VRAM insufficient -> cpu",
                workload_type,
                estimated_vram_mb,
                profile.vram_multiplier,
            )
            return "cpu"

    logger.info(
        "select_device: %s data_size=%d -> %s",
        workload_type,
        data_size,
        PREFERRED_GPU,
    )
    return PREFERRED_GPU


# ── LightGBM device helper ───────────────────────────────────────────────


_LGBM_DEVICE_CACHE: str | None = None


def lgbm_device() -> str:
    """Return the device parameter for LightGBM models ('gpu' or 'cpu').

    Detects whether the installed LightGBM build was compiled with GPU support
    by attempting a tiny GPU fit. Caches the result for subsequent calls.

    Usage:
        from quant.compute.device import lgbm_device
        model = lgb.LGBMClassifier(..., device=lgbm_device())
    """
    global _LGBM_DEVICE_CACHE
    if _LGBM_DEVICE_CACHE is not None:
        return _LGBM_DEVICE_CACHE

    try:
        import lightgbm as lgb  # type: ignore[import-not-found]

        try:
            _test = lgb.LGBMClassifier(n_estimators=1, device="gpu", verbose=-1)
            _test.fit([[0], [1]], [0, 1])
            _LGBM_DEVICE_CACHE = "gpu"
            logger.info("LightGBM GPU support detected")
            return "gpu"
        except Exception:
            _LGBM_DEVICE_CACHE = "cpu"
            logger.info("LightGBM GPU tidak tersedia — fallback ke CPU")
            return "cpu"
    except ImportError:
        _LGBM_DEVICE_CACHE = "cpu"
        return "cpu"


# ── Benchmarking ─────────────────────────────────────────────────────────
def benchmark_workload(
    fn: Callable[..., T],
    *args: Any,
    device: str = "cpu",
    n_runs: int = 3,
    **kwargs: Any,
) -> BenchmarkResult:
    """Run ``fn`` ``n_runs`` times on ``device`` and return timing stats.

    The callable receives ``device`` as a keyword argument (``fn(..., device=device)``)
    when it accepts a ``device`` parameter; otherwise it is called without it.
    This lets the same function be benchmarked on both CPU and GPU.

    Args:
        fn: Callable to benchmark.
        *args: Positional arguments forwarded to ``fn``.
        device: Device string passed to ``fn`` (if accepted).
        n_runs: Number of timed runs. The median is reported.
        **kwargs: Keyword arguments forwarded to ``fn``.

    Returns:
        :class:`BenchmarkResult` with per-run wall-clock times.

    References:
        - pustaka/34-performance-engineering-optimization.md §9 (Profiling &
          Benchmarking).
    """
    result = BenchmarkResult(device=device)
    # Detect whether fn accepts a `device` kwarg by inspecting kwargs already
    # provided vs the callable signature. We try with device first and fall
    # back to calling without it.
    call_kwargs = dict(kwargs)
    try:
        call_kwargs.setdefault("device", device)
        for _ in range(n_runs):
            start = time.perf_counter()
            fn(*args, **call_kwargs)
            result.times.append(time.perf_counter() - start)
    except TypeError:
        # fn does not accept `device`; retry without it.
        call_kwargs = dict(kwargs)
        for _ in range(n_runs):
            start = time.perf_counter()
            fn(*args, **call_kwargs)
            result.times.append(time.perf_counter() - start)
    logger.debug(
        "benchmark_workload: device=%s n_runs=%d median=%.6fs",
        device,
        n_runs,
        result.median,
    )
    return result


# Thread-safe cache for auto_select_device results keyed by workload_type.
_auto_select_cache: dict[str, str] = {}
_auto_select_lock = threading.Lock()


def auto_select_device(
    fn: Callable[..., T],
    args_cpu: tuple[Any, ...],
    args_gpu: tuple[Any, ...],
    workload_type: str,
    n_runs: int = 3,
) -> str:
    """Benchmark ``fn`` on both CPU and GPU and return the faster device.

    Results are cached per ``workload_type`` so the (relatively expensive)
    benchmark only runs once per workload type per process. The cache is
    thread-safe.

    Args:
        fn: Callable to benchmark. Must accept a ``device`` keyword argument.
        args_cpu: Positional arguments for the CPU run (typically a small
            sample of the real workload).
        args_gpu: Positional arguments for the GPU run (same sample, but
            expected to be moved to the GPU inside ``fn``).
        workload_type: Key for the result cache.
        n_runs: Number of timed runs per device.

    Returns:
        ``"cpu"`` or ``"cuda:1"`` — whichever had the lower median runtime.
        Falls back to :func:`select_device` heuristics when CUDA is
        unavailable.
    """
    with _auto_select_lock:
        if workload_type in _auto_select_cache:
            cached = _auto_select_cache[workload_type]
            logger.debug("auto_select_device: cache hit for %s -> %s", workload_type, cached)
            return cached

    # Fast path: no CUDA, defer to heuristics (which will return cpu).
    if not _TORCH_AVAILABLE or not torch.cuda.is_available():
        chosen = select_device(workload_type, data_size=10**9)
        with _auto_select_lock:
            _auto_select_cache[workload_type] = chosen
        return chosen

    cpu_result = benchmark_workload(fn, *args_cpu, device="cpu", n_runs=n_runs)
    gpu_result = benchmark_workload(fn, *args_gpu, device=PREFERRED_GPU, n_runs=n_runs)

    chosen = PREFERRED_GPU if gpu_result.median < cpu_result.median else "cpu"
    logger.info(
        "auto_select_device: %s cpu=%.6fs gpu=%.6fs -> %s",
        workload_type,
        cpu_result.median,
        gpu_result.median,
        chosen,
    )
    with _auto_select_lock:
        _auto_select_cache[workload_type] = chosen
    return chosen


# ── DeviceContext ────────────────────────────────────────────────────────
class DeviceContext(AbstractContextManager):
    """Context manager that selects a device and exposes it as ``ctx.device``.

    Example::

        with DeviceContext("lstm_training", data_size=50_000) as ctx:
            x = ctx.to(my_tensor)   # moved only if device is cuda:1
            model = model.to(ctx.device)

    The selection decision is logged at INFO level. When CUDA is unavailable
    the context silently falls back to CPU.

    Args:
        workload_type: Workload type key (see :func:`select_device`).
        data_size: Number of rows / elements in the workload.
        estimated_vram_mb: Optional VRAM estimate for the OOM check.
        device: Override the auto-selected device (skip selection). Mainly
            useful for tests.

    References:
        - AGENTS.md §2 (GPU/CUDA) and §4.
        - pustaka/34-performance-engineering-optimization.md §6 (Memory
          Management).
    """

    def __init__(
        self,
        workload_type: str,
        data_size: int,
        estimated_vram_mb: float | None = None,
        *,
        device: str | None = None,
    ) -> None:
        self.workload_type = workload_type
        self.data_size = data_size
        self.estimated_vram_mb = estimated_vram_mb
        self.device = device or select_device(
            workload_type,
            data_size=data_size,
            estimated_vram_mb=estimated_vram_mb,
        )

    # -- tensor movement -------------------------------------------------
    def to(self, obj: T) -> T:
        """Move a tensor (or module) to the selected device if possible.

        Falls back to returning the object unchanged when torch is missing or
        the object has no ``.to`` method.
        """
        if not _TORCH_AVAILABLE:
            return obj
        mover = getattr(obj, "to", None)
        if callable(mover):
            try:
                return mover(self.device)
            except (RuntimeError, TypeError) as exc:
                logger.warning("DeviceContext.to failed for %r: %s", obj, exc)
                return obj
        return obj

    def __enter__(self) -> DeviceContext:
        logger.info(
            "DeviceContext: workload=%s data_size=%d -> %s",
            self.workload_type,
            self.data_size,
            self.device,
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Nothing to tear down; selection is stateless. We sync the GPU so
        # pending kernels complete before the caller inspects results.
        if self.device.startswith("cuda") and _TORCH_AVAILABLE and torch.cuda.is_available():
            with suppress(RuntimeError):  # pragma: no cover - hardware specific
                torch.cuda.synchronize(_device_index(self.device))
        return None
