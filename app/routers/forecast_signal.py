from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.port import Port
from app.models.feature_store import FeatureStoreRow
from app.schemas.forecast_signal import SignalRequest, SignalResponse, TopFactor
from app.services.forecast_signal import compute_signal

router = APIRouter(prefix="/api/v1", tags=["Freight Forecasting"])


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
        # If model not loaded, use current BDI as fallback (signal stays neutral on BDI)
        predicted_bdi = current_bdi

    # --- Run rule engine ---
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

    # Build top_factors — all factors sorted by abs(score), skip zero-score ones
    top_factors = [
        TopFactor(factor=f.name, impact=f.score, summary=f.summary)
        for f in sorted(result.factors, key=lambda f: abs(f.score), reverse=True)
        if f.score != 0
    ]

    return SignalResponse(
        verdict=result.verdict,
        confidence=result.confidence,
        reason=result.reason,
        score=result.score,
        expected_bdi_change_pct=result.expected_bdi_change_pct,
        top_factors=top_factors,
        strategy_cards=[],
    )
