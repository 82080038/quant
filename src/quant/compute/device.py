"""Compute device dispatch — re-exports from core.device."""

from quant.core.device import select_device, DeviceContext

def lgbm_device():
    """Get device for LightGBM computation."""
    return "cpu"
