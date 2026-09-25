# GENERATED — edit house_sim/core/ (or fixtures), then run:
#   python -m scripts.sync_house_sim_integration
# Do not hand-edit this copy.
"""Single-node thermal Euler (copied for core isolation; no Earnie imports)."""
from __future__ import annotations


def compute_heat_loss_kw(
    temp_c: float,
    ambient_c: float,
    heat_loss_kw_per_k: float,
) -> float:
    """Primary-path heat loss only (S4 core has no extra_paths)."""
    return float(heat_loss_kw_per_k) * (float(temp_c) - float(ambient_c))


def simulate_next_temp_c(
    temp_c: float,
    ambient_c: float,
    heat_kw: float,
    *,
    capacity_kwh_per_k: float,
    heat_loss_kw_per_k: float,
    heating_efficiency: float,
) -> float:
    """One-hour Euler step (same formula as optimizer.thermal_model)."""
    if capacity_kwh_per_k <= 0:
        raise ValueError("capacity_kwh_per_k must be > 0")
    if heat_loss_kw_per_k < 0:
        raise ValueError("heat_loss_kw_per_k must be >= 0")
    if not 0.0 < heating_efficiency <= 1.0:
        raise ValueError("heating_efficiency must be in (0, 1]")
    loss_kw = compute_heat_loss_kw(temp_c, ambient_c, heat_loss_kw_per_k)
    net_kw = float(heat_kw) * heating_efficiency - loss_kw
    return float(temp_c) + net_kw / capacity_kwh_per_k
