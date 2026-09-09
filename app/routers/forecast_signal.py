from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.port import Port
from app.models.feature_store import FeatureStoreRow
from app.schemas.forecast_signal import (
    SignalRequest,
    SignalResponse,
    TopFactor,
    ContractStrategy,
    ContractStrategyFactors,
)
from app.services.forecast_signal import compute_signal, compute_contract_strategy
from app.services.vessel_optimization import optimize_vessel, PortData, VesselClassData
from app.models.vessel_class import VesselClass
import math

router = APIRouter(prefix="/api/v1", tags=["Freight Forecasting"])

# Confidence band width thresholds derived from BDI forecast spread.
# If the forecast model exposes an explicit interval, use that directly.
# Here we derive a proxy: abs(expected_bdi_change_pct) inverse maps to spread.
_BAND_NARROW = 5.0  # <= 5% → high certainty
_BAND_WIDE = 10.0  # >10% → low certainty


def _derive_confidence_band_width(signal_confidence: int) -> float:
    """
    Map the timing signal's 0-95 confidence score to a band-width proxy
    so the contract strategy gets a meaningful uncertainty input even when
    the forecast model doesn't expose an explicit prediction interval.

    confidence 80–95 → band  2–5%  (tight — HIGH certainty)
    confidence 50–79 → band  5–10% (moderate)
    confidence  0–49 → band 10–20% (wide — LOW certainty)
    """
    if signal_confidence >= 80:
        return max(2.0, 5.0 - (signal_confidence - 80) * 0.15)
    if signal_confidence >= 50:
        return 5.0 + (80 - signal_confidence) * (5.0 / 30.0)
    return 10.0 + (50 - signal_confidence) * (10.0 / 50.0)


@router.post("/forecast/signal", response_model=SignalResponse)
def forecast_signal(payload: SignalRequest, db: Session = Depends(get_db)):

    # --- Resolve ports ---
    load_port = db.query(Port).filter(Port.id == payload.loading_port_id).first()
    if not load_port:
        raise HTTPException(
            status_code=404, detail=f"Loading port {payload.loading_port_id} not found"
        )

    discharge_port = db.query(Port).filter(Port.id == payload.discharge_port_id).first()
    if not discharge_port:
        raise HTTPException(
            status_code=404,
            detail=f"Discharge port {payload.discharge_port_id} not found",
        )

    # --- Get latest + previous feature store rows ---
    rows = (
        db.query(FeatureStoreRow).order_by(FeatureStoreRow.date.desc()).limit(2).all()
    )
    if not rows:
        raise HTTPException(
            status_code=503, detail="Feature store is empty — run the ingest job first"
        )

    latest = rows[0]
    prev = rows[1] if len(rows) > 1 else None

    current_bdi = latest.bdi or 0.0
    current_vlsfo = latest.vlsfo_price_usd or 600.0
    prev_vlsfo = (
        prev.vlsfo_price_usd if prev and prev.vlsfo_price_usd else current_vlsfo
    )

    # --- Get predicted BDI from forecast model ---
    try:
        from app.services.freight_prediction import get_forecast

        forecast = get_forecast("bdi", db, days=1)
        predicted_bdi = forecast["point_forecast"]
    except Exception:
        predicted_bdi = current_bdi

    # --- Run timing rule engine ---
    result = compute_signal(
        current_bdi=current_bdi,
        predicted_bdi=predicted_bdi,
        current_vlsfo=current_vlsfo,
        prev_vlsfo=prev_vlsfo,
        load_port_name=load_port.name,
        discharge_port_name=discharge_port.name,
        load_port_country=load_port.country,
        discharge_port_country=discharge_port.country,
        feature_store_row=latest,
    )

    top_factors = [
        TopFactor(factor=f.name, impact=f.score, summary=f.summary)
        for f in sorted(result.factors, key=lambda f: abs(f.score), reverse=True)
        if f.score != 0
    ]

    # --- Contract strategy inputs ---
    # Voyage count: derive from vessel class DWT vs quantity
    voyage_count = 1
    try:
        vessel_classes = db.query(VesselClass).all()
        vc_match = next(
            (
                v
                for v in vessel_classes
                if v.vessel_class.lower() == payload.vessel_class.lower()
            ),
            None,
        )
        if vc_match and vc_match.dwt:
            voyage_count = math.ceil(payload.quantity_mt / vc_match.dwt)
    except Exception:
        pass

    # Disruption: cyclone OR geopolitical flag active
    disruption_risk = bool(
        (getattr(latest, "cyclone_india_flag", 0) or 0)
        or (getattr(latest, "cyclone_australia_flag", 0) or 0)
        or (getattr(latest, "geo_flag", 0) or 0)
    )

    # Confidence band width derived from timing signal confidence
    band_width = _derive_confidence_band_width(result.confidence)

    # Trend percent: use BDI forecast change
    trend_pct = result.expected_bdi_change_pct

    contract = compute_contract_strategy(
        trend_percent=trend_pct,
        confidence_band_width=band_width,
        voyage_count=voyage_count,
        disruption_risk=disruption_risk,
    )

    return SignalResponse(
        verdict=result.verdict,
        confidence=result.confidence,
        reason=result.reason,
        score=result.score,
        expected_bdi_change_pct=result.expected_bdi_change_pct,
        top_factors=top_factors,
        strategy_cards=[],
        contract_strategy=ContractStrategy(
            recommendation=contract.recommendation,
            score=contract.score,
            confidence=contract.confidence,
            reasons=contract.reasons,
            factors=ContractStrategyFactors(
                trend_percent=contract.trend_percent,
                confidence_band_width=contract.confidence_band_width,
                voyage_count=contract.voyage_count,
                disruption_risk=contract.disruption_risk,
            ),
        ),
    )
