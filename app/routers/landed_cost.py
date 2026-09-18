"""
POST /api/v1/landed-cost

Runs the same physical feasibility check as vessel optimization, then computes:
  - Freight cost  (from market index × distance multiplier × quantity)
  - Origin + destination port charges  (from ports table flat fee)
  - Cargo value  (cargo_price_per_mt × quantity)           — only if price given
  - Insurance     (rate% × (cargo_value + freight_cost) × 1.10)  — only if price given
  - Total landed cost  (all of the above)   OR
    Total shipping cost (freight + port charges, if no cargo price)
"""

import math
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.port import Port
from app.models.vessel_class import VesselClass
from app.models.route_distance import RouteDistance
from app.models.feature_store import FeatureStoreRow
from app.schemas.landed_cost import (
    LandedCostRequest,
    LandedCostResponse,
    LandedCostBreakdown,
    LandedCostFeasibilityFail,
)
from app.services.cost_summary import INDEX_COLUMN
from app.config.vessel_cost import (
    SPEED,
    CONSUMPTION,
    INDEX_POINT_MULTIPLIER,
    DEFAULT_LOAD_RATE_MTPD,
    DEFAULT_DISCHARGE_RATE_MTPD,
    CANAL_EXTRA_DAYS,
)

router = APIRouter(prefix="/api/v1", tags=["Landed Cost"])

_FALLBACK_INDEX = 1500.0

# Maps vessel class → Baltic index column in feature store
_VESSEL_TO_INDEX: dict[str, str] = {
    "handysize": "bsi",
    "supramax": "bsi",
    "panamax": "bpi",
    "capesize": "bci",
}


def _feasibility_reason(vessel: VesselClass, origin: Port, dest: Port) -> str | None:
    """
    Returns a human-readable reason string if the vessel is physically
    incompatible with the route, or None if feasible.
    Same rules as vessel_optimization service.
    """
    reasons = []
    for port in (origin, dest):
        if port.max_draft is not None and vessel.draft > port.max_draft:
            reasons.append(
                f"{vessel.vessel_class} draft ({vessel.draft}m) exceeds "
                f"{port.name}'s limit ({port.max_draft}m)"
            )
        if port.max_loa is not None and vessel.loa > port.max_loa:
            reasons.append(
                f"{vessel.vessel_class} LOA ({vessel.loa}m) exceeds "
                f"{port.name}'s limit ({port.max_loa}m)"
            )
        if (
            vessel.beam is not None
            and port.max_beam is not None
            and vessel.beam > port.max_beam
        ):
            reasons.append(
                f"{vessel.vessel_class} beam ({vessel.beam}m) exceeds "
                f"{port.name}'s limit ({port.max_beam}m)"
            )
    return "; ".join(reasons) if reasons else None


@router.post(
    "/landed-cost",
    summary="Calculate total landed cost or shipping cost for a shipment",
)
def landed_cost(payload: LandedCostRequest, db: Session = Depends(get_db)):
    # ── 1. Resolve vessel ──────────────────────────────────────────────────
    vessel = (
        db.query(VesselClass).filter(VesselClass.id == payload.vessel_class_id).first()
    )
    if not vessel:
        return LandedCostFeasibilityFail(reason="Vessel class not found in database.")

    vc = vessel.vessel_class.lower()
    if vc not in _VESSEL_TO_INDEX:
        return LandedCostFeasibilityFail(
            reason=f"Vessel class '{vessel.vessel_class}' is not supported for cost calculation."
        )

    # ── 2. Resolve ports ──────────────────────────────────────────────────
    origin = db.query(Port).filter(Port.id == payload.origin_port_id).first()
    dest = db.query(Port).filter(Port.id == payload.destination_port_id).first()
    if not origin or not dest:
        return LandedCostFeasibilityFail(
            reason="One or both ports not found in database."
        )

    # ── 3. Physical feasibility ───────────────────────────────────────────
    infeasible_reason = _feasibility_reason(vessel, origin, dest)
    if infeasible_reason:
        return LandedCostFeasibilityFail(
            reason=f"Vessel physically incompatible with this route: {infeasible_reason}."
        )

    # ── 4. Route distance ─────────────────────────────────────────────────
    route = (
        db.query(RouteDistance)
        .filter(
            RouteDistance.loading_port.ilike(origin.name),
            RouteDistance.discharge_port.ilike(dest.name),
        )
        .first()
    )
    if not route:
        return LandedCostFeasibilityFail(
            reason=f"No shipping route found from {origin.name} to {dest.name}. "
            "Route distances may not yet be seeded for this port pair."
        )

    # ── 5. Market data ────────────────────────────────────────────────────
    store_row = db.query(FeatureStoreRow).order_by(FeatureStoreRow.date.desc()).first()
    index_col = _VESSEL_TO_INDEX[vc]
    index_pts = (
        getattr(store_row, index_col, None) if store_row else None
    ) or _FALLBACK_INDEX
    multiplier = INDEX_POINT_MULTIPLIER.get(vc, 9.0)

    # ── 6. Voyage geometry ────────────────────────────────────────────────
    speed = SPEED.get(vc, 14.0)
    cap = vessel.dwt

    num_voyages = math.ceil(payload.cargo_quantity_mt / cap)
    sailing_days = route.distance_nm / (speed * 24)
    load_days = cap / DEFAULT_LOAD_RATE_MTPD
    discharge_days = cap / DEFAULT_DISCHARGE_RATE_MTPD
    canal_extra = CANAL_EXTRA_DAYS if route.route_type == "suez" else 0.0
    voyage_days = sailing_days + load_days + discharge_days + canal_extra

    # ── 7. Freight cost (total across all voyages) ────────────────────────
    market_tce_per_day = index_pts * multiplier
    freight_per_voyage = market_tce_per_day * voyage_days
    freight_total = round(freight_per_voyage * num_voyages, 2)
    freight_per_mt = round(freight_total / payload.cargo_quantity_mt, 4)

    # ── 8. Port charges ───────────────────────────────────────────────────
    origin_charges = round((origin.port_charges_flat_usd or 0.0) * num_voyages, 2)
    dest_charges = round((dest.port_charges_flat_usd or 0.0) * num_voyages, 2)

    # ── 9. Cargo value + insurance (only if cargo price supplied) ─────────
    cargo_value: float | None = None
    insurance: float | None = None
    insurance_basis: str | None = None

    if payload.cargo_price_per_mt is not None:
        cargo_value = round(payload.cargo_price_per_mt * payload.cargo_quantity_mt, 2)
        # Institute Cargo Clauses standard: rate% × (cargo value + freight) × 1.10
        insurable_value = (cargo_value + freight_total) * 1.10
        insurance = round(insurable_value * (payload.insurance_rate_pct / 100), 2)
        insurance_basis = (
            f"{payload.insurance_rate_pct}% × "
            f"(cargo value ${cargo_value:,.0f} + freight ${freight_total:,.0f}) × 1.10 "
            f"[Institute Cargo Clauses convention]"
        )

    # ── 10. Total ─────────────────────────────────────────────────────────
    total = freight_total + origin_charges + dest_charges
    if cargo_value is not None:
        total += cargo_value
    if insurance is not None:
        total += insurance
    total = round(total, 2)
    total_per_mt = round(total / payload.cargo_quantity_mt, 4)

    mode = "landed_cost" if cargo_value is not None else "shipping_cost"

    return LandedCostResponse(
        feasible=True,
        breakdown=LandedCostBreakdown(
            num_voyages=num_voyages,
            vessel_capacity_mt=cap,
            voyage_days=round(voyage_days, 2),
            sailing_days=round(sailing_days, 2),
            load_days=round(load_days, 2),
            discharge_days=round(discharge_days, 2),
            distance_nm=route.distance_nm,
            route_type=route.route_type,
            freight_cost_usd=freight_total,
            origin_port_charges_usd=origin_charges,
            destination_port_charges_usd=dest_charges,
            cargo_value_usd=cargo_value,
            insurance_usd=insurance,
            insurance_rate_pct=payload.insurance_rate_pct,
            insurance_basis=insurance_basis,
            total_usd=total,
            total_per_mt_usd=total_per_mt,
            mode=mode,
            index_used=index_col.upper(),
            index_points=round(index_pts, 0),
            freight_rate_per_mt_usd=freight_per_mt,
        ),
    )
