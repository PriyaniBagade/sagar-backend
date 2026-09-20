"""
POST /api/v1/market-entry-timing

Takes route, cargo, vessel, and contract duration. Returns a BOOK/WAIT verdict
plus detailed factor breakdown and SPOT vs COA pricing comparison.

Verdict logic:
  - Freight forecast direction (primary driver): falling rates → WAIT, rising → BOOK
  - Geopolitical disruptions on route: HIGH/MODERATE → WAIT (adds uncertainty)
  - Cyclone/weather risk: HIGH/MODERATE at destination → minor WAIT influence
  - Each factor gets an impact score (positive BOOK, negative WAIT)
  - Scores sum to overall verdict + confidence %

Contract strategy:
  - SPOT: current freight rate × voyages within contract duration
  - COA: average forecasted rate over contract duration × voyages
  - Recommendation follows cheaper option + verdict preference (WAIT favors SPOT flexibility)
"""

import math
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.config.database import get_db
from app.models.port import Port
from app.models.vessel_class import VesselClass
from app.models.route_distance import RouteDistance
from app.models.feature_store import FeatureStoreRow
from app.schemas.market_entry_timing import (
    MarketEntryTimingRequest,
    MarketEntryTimingResponse,
    MarketEntryTimingFail,
    TopFactor,
    SpotComparison,
    COAComparison,
    ContractStrategy,
)
from app.services.freight_prediction import get_spec_forecast, INDICES
from app.config.vessel_cost import (
    SPEED,
    DEFAULT_LOAD_RATE_MTPD,
    DEFAULT_DISCHARGE_RATE_MTPD,
    CANAL_EXTRA_DAYS,
    INDEX_POINT_MULTIPLIER,
)

router = APIRouter(prefix="/api/v1", tags=["Market Entry Timing"])

_FALLBACK_INDEX = 1500.0
_VESSEL_TO_INDEX = {
    "handysize": "bsi",
    "supramax": "bsi",
    "panamax": "bpi",
    "capesize": "bci",
}

_PORT_WAIT_DAYS = {
    "paradip": 4.2,
    "haldia dock complex": 3.1,
    "haldia": 3.1,
    "visakhapatnam": 1.8,
    "dhamra": 0.9,
    "gangavaram": 1.2,
    "new mangalore": 1.0,
    "abbot point (nqxt)": 0.5,
    "hay point (dbct)": 0.6,
    "hay point": 0.6,
    "newcastle": 0.7,
    "port kembla": 0.8,
    "ponta da madeira": 0.6,
    "tubarao": 0.7,
    "ponta ubu": 0.6,
    "nacala": 1.1,
    "beira": 1.4,
    "richards bay": 1.2,
    "cigading": 1.0,
    "muara pantai": 0.9,
    "taboneo": 1.0,
}

_GEO_FLAGS = [
    {
        "region": "Red Sea",
        "severity": "HIGH",
        "affected_routes": ["suez"],
    },
    {
        "region": "Strait of Hormuz",
        "severity": "MODERATE",
        "affected_routes": ["hormuz"],
    },
]


def _feasibility_reason(vessel: VesselClass, origin: Port, dest: Port) -> str | None:
    """Check physical compatibility."""
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


def _voyage_days(vessel: VesselClass, route: RouteDistance, vc: str) -> float:
    """Calculate round-trip voyage days (same logic as landed_cost)."""
    speed = SPEED.get(vc, 14.0)
    cap = vessel.dwt
    sailing_days = route.distance_nm / (speed * 24)
    load_days = cap / DEFAULT_LOAD_RATE_MTPD
    discharge_days = cap / DEFAULT_DISCHARGE_RATE_MTPD
    canal_extra = CANAL_EXTRA_DAYS if route.route_type == "suez" else 0.0
    return sailing_days + load_days + discharge_days + canal_extra


def _freight_rate_per_mt(
    vessel_class: str,
    route: RouteDistance,
    store_row: FeatureStoreRow | None,
) -> float:
    """Get current freight rate per MT (same logic as forecast module)."""
    index_col = _VESSEL_TO_INDEX.get(vessel_class.lower(), "bpi")
    index_pts = (
        getattr(store_row, index_col, None) if store_row else None
    ) or _FALLBACK_INDEX
    multiplier = INDEX_POINT_MULTIPLIER.get(vessel_class.lower(), 9.0)
    # Distance-based multiplier (same as forecast.py)
    BASE_DISTANCE = 3000.0
    BASE_MULTIPLIER = 0.004
    distance_adj = (route.distance_nm - BASE_DISTANCE) / 1000.0
    mult = BASE_MULTIPLIER - (distance_adj * 0.0005)
    mult = max(0.002, min(0.008, mult))
    return round(index_pts * mult, 4)


def _forecast_direction(
    vessel_class: str, days_ahead: int, db: Session
) -> tuple[float, str]:
    """
    Get forecast rate change % over the given days.
    Returns (change_pct, direction_text).
    """
    try:
        index_col = _VESSEL_TO_INDEX.get(vessel_class.lower(), "bpi")
        idx_forecasts = get_spec_forecast(
            index_col, db, forecast_horizon_days=days_ahead
        )
        current = idx_forecasts.get("current_value", None)
        forecast_list = idx_forecasts.get("forecast", [])
        if not forecast_list or current is None or current <= 0:
            return 0.0, "neutral"
        last_day = forecast_list[-1]
        predicted = last_day.get("predicted_value", current)
        change = (predicted - current) / current * 100
        if change > 2:
            return round(change, 2), "rising"
        elif change < -2:
            return round(change, 2), "falling"
        else:
            return round(change, 2), "stable"
    except Exception:
        return 0.0, "unknown"


def _geopolitical_factor(route: RouteDistance) -> float:
    """
    Return impact score for geopolitical disruption.
    HIGH disruption on route → -30 (WAIT)
    MODERATE → -15
    None → 0
    """
    if not route.route_type:
        return 0.0
    for flag in _GEO_FLAGS:
        if route.route_type.lower() in [
            r.lower() for r in flag.get("affected_routes", [])
        ]:
            if flag["severity"] == "HIGH":
                return -30.0
            elif flag["severity"] == "MODERATE":
                return -15.0
    return 0.0


def _cyclone_factor(dest_port: Port, store_row: FeatureStoreRow | None) -> float:
    """
    Return minor impact for cyclone/weather risk.
    HIGH active cyclone → -10 (WAIT)
    MODERATE (heavy rainfall) → -5
    None → 0
    """
    if not store_row:
        return 0.0
    country = (dest_port.country or "").lower()
    name = dest_port.name.lower()

    if country == "india" and bool(store_row.cyclone_india_flag):
        return -10.0
    if country == "australia" and bool(store_row.cyclone_australia_flag):
        return -10.0

    rainfall = None
    if "paradip" in name:
        rainfall = store_row.rainfall_paradip_mm
    elif "visakhapatnam" in name or "vizag" in name:
        rainfall = store_row.rainfall_vizag_mm
    elif "haldia" in name:
        rainfall = store_row.rainfall_haldia_mm
    elif "hay point" in name:
        rainfall = store_row.rainfall_hay_point_mm
    elif country == "indonesia":
        rainfall = store_row.rainfall_indonesia_mm

    if rainfall is not None and rainfall >= 20.0:
        return -5.0
    return 0.0


def _average_forecasted_rate(
    vessel_class: str,
    route: RouteDistance,
    contract_months: float,
    db: Session,
) -> float:
    """
    Average the forecasted freight rate per MT across the contract duration.
    Assumes constant sailing day and no index volatility between forecasts.
    """
    try:
        index_col = _VESSEL_TO_INDEX.get(vessel_class.lower(), "bpi")
        # Estimate how many business days in contract period (roughly 22 per month)
        business_days = int(contract_months * 22)
        days_ahead = min(business_days, 30)  # Max 30-day forecast available

        idx_forecasts = get_spec_forecast(
            index_col, db, forecast_horizon_days=days_ahead
        )
        forecast_list = idx_forecasts.get("forecast", [])
        if not forecast_list:
            return _freight_rate_per_mt(vessel_class, route, None)

        rates = []
        multiplier = INDEX_POINT_MULTIPLIER.get(vessel_class.lower(), 9.0)
        BASE_DISTANCE = 3000.0
        BASE_MULTIPLIER = 0.004
        distance_adj = (route.distance_nm - BASE_DISTANCE) / 1000.0
        mult = BASE_MULTIPLIER - (distance_adj * 0.0005)
        mult = max(0.002, min(0.008, mult))

        for day_forecast in forecast_list:
            predicted_idx = day_forecast.get("predicted_value", 0)
            rate = round(predicted_idx * mult, 4)
            rates.append(rate)

        return (
            round(sum(rates) / len(rates), 4)
            if rates
            else _freight_rate_per_mt(vessel_class, route, None)
        )
    except Exception:
        return _freight_rate_per_mt(vessel_class, route, None)


@router.post(
    "/market-entry-timing",
    response_model=dict,
    summary="BOOK vs WAIT verdict + SPOT vs COA strategy recommendation",
)
def market_entry_timing(
    payload: MarketEntryTimingRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Market Entry Timing analysis: should user book now or wait?
    If considering a contract, is SPOT or COA better?
    """

    # ── 1. Resolve and validate ────────────────────────────────────────
    def find_port(name: str) -> Port | None:
        return db.query(Port).filter(Port.name.ilike(name.strip())).first()

    origin = find_port(payload.origin_port)
    dest = find_port(payload.destination_port)
    if not origin:
        return MarketEntryTimingFail(
            reason=f"Origin port '{payload.origin_port}' not found."
        )
    if not dest:
        return MarketEntryTimingFail(
            reason=f"Destination port '{payload.destination_port}' not found."
        )

    vessel = (
        db.query(VesselClass)
        .filter(VesselClass.vessel_class.ilike(payload.vessel_type.strip()))
        .first()
    )
    if not vessel:
        return MarketEntryTimingFail(
            reason=f"Vessel type '{payload.vessel_type}' not found."
        )

    vc = vessel.vessel_class.lower()
    if vc not in _VESSEL_TO_INDEX:
        return MarketEntryTimingFail(
            reason=f"Vessel class '{vessel.vessel_class}' not supported for market timing."
        )

    # ── 2. Physical feasibility ────────────────────────────────────────
    infeasible = _feasibility_reason(vessel, origin, dest)
    if infeasible:
        return MarketEntryTimingFail(
            reason=f"Vessel not feasible for route: {infeasible}"
        )

    # ── 3. Route distance ─────────────────────────────────────────────
    route = (
        db.query(RouteDistance)
        .filter(
            RouteDistance.loading_port.ilike(origin.name),
            RouteDistance.discharge_port.ilike(dest.name),
        )
        .first()
    )
    if not route:
        return MarketEntryTimingFail(
            reason=f"No route found from {origin.name} to {dest.name}."
        )

    # ── 4. Voyage geometry ────────────────────────────────────────────
    voyage_days_val = _voyage_days(vessel, route, vc)
    voyages_in_contract = max(
        1, int(payload.contract_duration_months * 30 / voyage_days_val)
    )

    # ── 5. Current freight rate ───────────────────────────────────────
    store_row = db.query(FeatureStoreRow).order_by(desc(FeatureStoreRow.date)).first()
    current_rate = _freight_rate_per_mt(vc, route, store_row)

    # ── 6. Forecast direction (primary driver) ────────────────────────
    # Use a forward-looking horizon: 2–3 months ≈ 45 business days
    forecast_days = min(30, int(payload.contract_duration_months * 22))
    rate_change_pct, direction = _forecast_direction(vc, forecast_days, db)

    # Scoring: -50 (strong WAIT if falling) to +50 (strong BOOK if rising)
    if direction == "falling":
        forecast_impact = -50.0 * (abs(rate_change_pct) / 10.0)  # Scale by magnitude
        forecast_impact = max(-50.0, min(-10.0, forecast_impact))
    elif direction == "rising":
        forecast_impact = 50.0 * (abs(rate_change_pct) / 10.0)
        forecast_impact = min(50.0, max(10.0, forecast_impact))
    else:
        forecast_impact = 0.0

    # ── 7. Geopolitical factor ────────────────────────────────────────
    geo_impact = _geopolitical_factor(route)

    # ── 8. Cyclone/weather factor ─────────────────────────────────────
    cyclone_impact = _cyclone_factor(dest, store_row)

    # ── 9. Overall score & verdict ────────────────────────────────────
    factors = [
        {
            "factor": "Freight Forecast",
            "impact": round(forecast_impact, 1),
            "summary": (
                f"Expected to {'fall' if rate_change_pct < 0 else 'rise' if rate_change_pct > 0 else 'stay flat'} {abs(rate_change_pct):.1f}% over the horizon"
                if rate_change_pct != 0
                else "Expected to remain stable"
            ),
        }
    ]

    if geo_impact != 0:
        factors.append(
            {
                "factor": "Geopolitical Disruption",
                "impact": round(geo_impact, 1),
                "summary": "Active disruption flagged on/near the selected route",
            }
        )

    if cyclone_impact != 0:
        factors.append(
            {
                "factor": "Cyclone/Weather Risk",
                "impact": round(cyclone_impact, 1),
                "summary": "Minor risk at destination port; may cause delays",
            }
        )

    overall_score = forecast_impact + geo_impact + cyclone_impact
    overall_score = max(-100.0, min(100.0, overall_score))

    # Verdict: BOOK if score > 10, WAIT if < -10, else LOW CONFIDENCE either way
    if overall_score > 10:
        verdict = "BOOK"
        confidence = min(95, 50 + abs(overall_score) * 0.5)
        reason = "Freight rates are forecast to strengthen; booking now locks in better pricing."
        if geo_impact < -20:
            reason += " However, active route disruption adds some uncertainty."
    elif overall_score < -10:
        verdict = "WAIT"
        confidence = min(95, 50 + abs(overall_score) * 0.5)
        reason = (
            "Freight is forecast to weaken; waiting for rate improvement is advisable."
        )
        if geo_impact < -20:
            reason += " An active geopolitical disruption increases route uncertainty, favoring flexibility over immediate commitment."
    else:
        verdict = "NEUTRAL"
        confidence = 55
        reason = "Market signals are mixed; current rate is competitive, but no strong signal to commit or delay."

    # ── 10. SPOT vs COA strategy ──────────────────────────────────────
    # cargo_quantity_mt = quantity per shipment.
    # total_mt = cargo per shipment × number of voyages in the contract period.
    total_mt = payload.cargo_quantity_mt * voyages_in_contract

    # SPOT: current rate × total MT shipped over contract
    spot_rate = current_rate
    spot_total = round(spot_rate * total_mt, 2)

    # COA: average forecasted rate × same total MT
    coa_rate = _average_forecasted_rate(vc, route, payload.contract_duration_months, db)
    coa_total = round(coa_rate * total_mt, 2)

    # Savings expressed as percentage of spot total (positive = COA is cheaper)
    savings = round(spot_total - coa_total, 2)
    savings_pct = round(savings / spot_total * 100, 1) if spot_total > 0 else 0.0

    # ── Contract type: always the cheaper option ──────────────────────
    # (Timing signal and contract type are independent outputs)
    cheaper = "COA" if coa_total < spot_total else "SPOT"
    recommendation = cheaper

    # ── Build "why" text — must be consistent with both signals ───────
    timing_text = {
        "BOOK": "rates are forecast to strengthen",
        "WAIT": "rates are forecast to soften",
        "NEUTRAL": "market signals are mixed",
    }[verdict]

    if cheaper == "COA":
        cost_text = (
            f"COA is the lower-cost option at ${coa_total:,.0f} vs spot ${spot_total:,.0f} "
            f"(saves ${abs(savings):,.0f}, {abs(savings_pct):.1f}% cheaper)."
        )
        if verdict == "WAIT":
            reason_rec = (
                f"Although {timing_text}, COA locks in the lower forecasted rate now. "
                + cost_text
            )
        else:
            reason_rec = (
                f"Because {timing_text}, securing a COA now protects against further increases. "
                + cost_text
            )
    else:
        cost_text = (
            f"Spot is the lower-cost option at ${spot_total:,.0f} vs COA ${coa_total:,.0f} "
            f"(COA costs ${abs(savings):,.0f} more, {abs(savings_pct):.1f}% dearer)."
        )
        if verdict == "WAIT":
            reason_rec = (
                f"Because {timing_text}, waiting for better spot rates is advisable. "
                + cost_text
                + " Booking spot gives maximum flexibility while rates adjust."
            )
        else:
            reason_rec = (
                f"Despite {timing_text}, spot remains cheaper for this volume. "
                + cost_text
            )

    if geo_impact < -20:
        reason_rec += " Active route disruption adds short-term uncertainty; spot flexibility has additional value."

    # Format savings label for UI: "Saves $X (Y% cheaper than spot)" or "Costs $X (Y% more than spot)"
    if savings >= 0:
        vs_spot_label = (
            f"Saves ${savings:,.0f} ({abs(savings_pct):.1f}% cheaper than spot)"
        )
    else:
        vs_spot_label = (
            f"Costs ${abs(savings):,.0f} ({abs(savings_pct):.1f}% more than spot)"
        )

    return MarketEntryTimingResponse(
        verdict=verdict,
        confidence_pct=int(confidence),
        reason=reason,
        score=round(overall_score, 1),
        expected_rate_change_pct=rate_change_pct,
        top_factors=factors,
        contract_strategy=ContractStrategy(
            recommendation=recommendation,
            confidence=(
                "HIGH"
                if abs(savings_pct) > 10
                else "MEDIUM" if abs(savings_pct) > 5 else "LOW"
            ),
            comparison={
                "spot": {
                    "rate_per_mt": round(spot_rate, 4),
                    "voyages_estimated": voyages_in_contract,
                    "total_mt": total_mt,
                    "total_cost": spot_total,
                },
                "coa": {
                    "duration_months": payload.contract_duration_months,
                    "rate_per_mt": round(coa_rate, 4),
                    "voyages_estimated": voyages_in_contract,
                    "total_mt": total_mt,
                    "total_cost": coa_total,
                    "vs_spot_label": vs_spot_label,
                },
            },
            reasons=[
                reason_rec,
                f"COA estimate ({round(coa_rate, 2)}/MT avg) based on forecasted rates over {payload.contract_duration_months} months; not actual negotiated rates.",
            ],
        ),
    ).model_dump()
