"""
Pure optimization logic — no FastAPI request/response objects here.
Inputs and outputs are plain Python dicts/dataclasses so this is fully unit-testable.
"""
import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PortData:
    id: str
    name: str
    country: str
    port_type: str      # "LOADING" | "DISCHARGE"
    max_draft: Optional[float]
    max_loa: Optional[float]
    max_beam: Optional[float]


@dataclass
class VesselClassData:
    id: str
    vessel_class: str
    dwt: float
    draft: float
    loa: float
    beam: Optional[float]
    charter_cost_per_day: Optional[float]
    berthing_fee_per_day: Optional[float]


@dataclass
class OptimizationResult:
    recommended_class: str
    voyages_needed: int
    eligible_classes: list[str]
    rejected_classes: list[dict]   # {"vessel_class": str, "rejection_reason": str}
    warnings: list[str]


# ---------------------------------------------------------------------------
# Cost stubs — P2/P4 features. Pluggable: swap these out without touching
# the optimization logic below.
# ---------------------------------------------------------------------------

def stub_freight_rate_per_voyage(vessel: VesselClassData, loading_port: PortData, discharge_port: PortData) -> float:
    """Placeholder — will be replaced by the freight-rate forecasting module (P2)."""
    return 0.0

def stub_handling_cost(vessel: VesselClassData, cargo_qty: float, discharge_port: PortData) -> float:
    """Placeholder — will be replaced by port-cost module (P4)."""
    return 0.0

def stub_congestion_risk(vessel: VesselClassData, discharge_port: PortData) -> float:
    """Placeholder — will be replaced by congestion-scoring module."""
    return 0.0

def stub_demurrage_estimate(vessel: VesselClassData, loading_port: PortData, discharge_port: PortData) -> float:
    """Placeholder — will be replaced by demurrage model."""
    return 0.0


# ---------------------------------------------------------------------------
# Main optimization function
# ---------------------------------------------------------------------------

def optimize_vessel(
    loading_port: PortData,
    discharge_port: PortData,
    cargo_quantity: float,
    vessel_classes: list[VesselClassData],
    freight_rate_fn=stub_freight_rate_per_voyage,
    handling_cost_fn=stub_handling_cost,
    congestion_risk_fn=stub_congestion_risk,
    demurrage_fn=stub_demurrage_estimate,
) -> OptimizationResult:
    warnings: list[str] = []
    rejected: list[dict] = []
    eligible: list[VesselClassData] = []

    # ------------------------------------------------------------------
    # Filter 0 — Route validity (trade-direction guard)
    # Without this, passing an Indian port as loading_port_id would pass
    # all physical checks since draft/LOA filters don't know trade direction.
    # ------------------------------------------------------------------
    if loading_port.port_type != "LOADING":
        raise ValueError(
            f"{loading_port.name} is a {loading_port.port_type} port — "
            "not valid as a loading/source port for this trade"
        )
    if discharge_port.port_type != "DISCHARGE":
        raise ValueError(
            f"{discharge_port.name} is a {discharge_port.port_type} port — "
            "not valid as a discharge/destination port for this trade"
        )

    # ------------------------------------------------------------------
    # Filter 1 — Physical feasibility (hard gate)
    # If a port constraint is None, skip that check but flag as unverified.
    # ------------------------------------------------------------------
    for v in vessel_classes:
        reasons = []

        # Draft check
        lp_draft_ok = loading_port.max_draft is None or v.draft <= loading_port.max_draft
        dp_draft_ok = discharge_port.max_draft is None or v.draft <= discharge_port.max_draft

        if not lp_draft_ok:
            reasons.append(
                f"draft {v.draft}m exceeds {loading_port.name}'s {loading_port.max_draft}m limit"
            )
        if not dp_draft_ok:
            reasons.append(
                f"draft {v.draft}m exceeds {discharge_port.name}'s {discharge_port.max_draft}m limit"
            )

        # LOA check
        lp_loa_ok = loading_port.max_loa is None or v.loa <= loading_port.max_loa
        dp_loa_ok = discharge_port.max_loa is None or v.loa <= discharge_port.max_loa

        if not lp_loa_ok:
            reasons.append(
                f"LOA {v.loa}m exceeds {loading_port.name}'s {loading_port.max_loa}m limit"
            )
        if not dp_loa_ok:
            reasons.append(
                f"LOA {v.loa}m exceeds {discharge_port.name}'s {discharge_port.max_loa}m limit"
            )

        # Beam check — only hard-reject if vessel beam AND both port beams are known
        if v.beam is not None:
            lp_beam_unverified = loading_port.max_beam is None
            dp_beam_unverified = discharge_port.max_beam is None

            if lp_beam_unverified:
                warnings.append(f"Beam constraint unverified for {loading_port.name}")
            if dp_beam_unverified:
                warnings.append(f"Beam constraint unverified for {discharge_port.name}")

            if not lp_beam_unverified and v.beam > loading_port.max_beam:
                reasons.append(
                    f"beam {v.beam}m exceeds {loading_port.name}'s {loading_port.max_beam}m limit"
                )
            if not dp_beam_unverified and v.beam > discharge_port.max_beam:
                reasons.append(
                    f"beam {v.beam}m exceeds {discharge_port.name}'s {discharge_port.max_beam}m limit"
                )

        if reasons:
            rejected.append({
                "vessel_class": v.vessel_class,
                "rejection_reason": f"{v.vessel_class} rejected: {'; '.join(reasons)}",
            })
        else:
            eligible.append(v)

    if not eligible:
        raise ValueError("No vessel class can physically serve this route with the given constraints.")

    # ------------------------------------------------------------------
    # Filter 2 — Capacity (voyages needed per vessel class)
    # ------------------------------------------------------------------
    # Filter 3 — Cost ranking (stub-pluggable cost functions)
    # ------------------------------------------------------------------
    best_vessel = None
    best_cost = float("inf")
    best_voyages = 0

    for v in eligible:
        voyages = math.ceil(cargo_quantity / v.dwt)
        total_cost = (
            freight_rate_fn(v, loading_port, discharge_port) * voyages
            + handling_cost_fn(v, cargo_quantity, discharge_port)
            + congestion_risk_fn(v, discharge_port)
            + demurrage_fn(v, loading_port, discharge_port)
        )
        if total_cost < best_cost:
            best_cost = total_cost
            best_vessel = v
            best_voyages = voyages

    # De-duplicate warnings
    warnings = list(dict.fromkeys(warnings))

    return OptimizationResult(
        recommended_class=best_vessel.vessel_class,
        voyages_needed=best_voyages,
        eligible_classes=[v.vessel_class for v in eligible],
        rejected_classes=rejected,
        warnings=warnings,
    )
