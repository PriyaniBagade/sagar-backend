from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Literal, Union
import datetime

from app.config.database import get_db
from app.models.vessel_class import VesselClass
from app.services.freight_prediction import (
    get_spec_forecast,
    get_spec_all_forecasts,
    get_spec_forecast_history,
    INDICES,
)
from app.schemas.freight_prediction import (
    AllForecastsResponse,
    SingleForecastResponse,
    ForecastHistoryResponse,
    PredictRequest,
    PredictResponse,
    ConfidenceRange,
    IngestResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Freight Forecasting"])

IndexLiteral = Literal["bdi", "bci", "bpi", "bsi"]


@router.get(
    "/forecast/all",
    response_model=AllForecastsResponse,
    summary="Forecast all four indices in one call",
    description="Returns BDI, BCI, BPI, BSI forecasts. Pass `days` for multi-day outlook on all.",
)
def forecast_all(
    days: int = Query(
        default=1, ge=1, le=30, description="Number of business days ahead"
    ),
    db: Session = Depends(get_db),
) -> AllForecastsResponse:
    try:
        return get_spec_all_forecasts(db, forecast_horizon_days=days)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get(
    "/forecast/{index}/history",
    response_model=ForecastHistoryResponse,
    summary="Predicted vs actual history for an index",
)
def forecast_history(
    index: IndexLiteral,
    lookback_days: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db),
) -> ForecastHistoryResponse:
    try:
        return get_spec_forecast_history(index, db, lookback_days=lookback_days)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/forecast/{index}",
    response_model=SingleForecastResponse,
    summary="Forecast a single Baltic index",
    description=(
        "Returns a point forecast + confidence band + SHAP drivers for the requested index. "
        "Use `days=1` (default) for today's forecast, or `days=2..30` for a multi-day outlook."
    ),
)
def forecast_single(
    index: IndexLiteral,
    days: int = Query(
        default=1, ge=1, le=30, description="Number of business days to forecast ahead"
    ),
    db: Session = Depends(get_db),
) -> SingleForecastResponse:
    try:
        return get_spec_forecast(index, db, forecast_horizon_days=days)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post(
    "/forecast/predict",
    response_model=PredictResponse,
    summary="Predict freight rate per MT for a given route and cargo",
)
def forecast_predict(
    payload: PredictRequest,
    db: Session = Depends(get_db),
) -> PredictResponse:
    """
    Maps vessel_type to a Baltic index, runs get_spec_forecast, then converts
    the index-point forecast to a USD/MT rate using a distance-based multiplier.
    """
    from app.models.port import Port
    from app.models.route_distance import RouteDistance

    # Resolve vessel_type UUID → vessel class name
    vessel = db.query(VesselClass).filter(VesselClass.id == payload.vessel_type).first()
    if not vessel:
        raise HTTPException(
            status_code=404,
            detail=f"Vessel class '{payload.vessel_type}' not found",
        )

    vessel_to_index = {
        "capesize": "bci",
        "panamax": "bpi",
        "supramax": "bsi",
        "handymax": "bsi",
        "handysize": "bsi",
    }
    idx = vessel_to_index.get(vessel.vessel_class.lower())
    if idx is None:
        return PredictResponse(
            feasible=False,
            infeasibility_reason=f"No index mapping for vessel class '{vessel.vessel_class}'. "
            f"Supported classes: {list(vessel_to_index.keys())}",
            predicted_rate_per_mt=None,
            confidence_range=None,
            confidence_pct=None,
            forecast_date=None,
            based_on_index=None,
        )

    # Resolve ports
    origin_port = db.query(Port).filter(Port.id == payload.origin_port).first()
    dest_port = db.query(Port).filter(Port.id == payload.destination_port).first()
    if not origin_port or not dest_port:
        return PredictResponse(
            feasible=False,
            infeasibility_reason="One or both ports not found in database",
            predicted_rate_per_mt=None,
            confidence_range=None,
            confidence_pct=None,
            forecast_date=None,
            based_on_index=None,
        )

    # ── Physical feasibility checks (same rules as vessel optimization) ──
    reasons = []

    if origin_port.max_draft is not None and vessel.draft > origin_port.max_draft:
        reasons.append(
            f"{vessel.vessel_class} draft ({vessel.draft}m) exceeds {origin_port.name}'s "
            f"max draft limit ({origin_port.max_draft}m)"
        )
    if dest_port.max_draft is not None and vessel.draft > dest_port.max_draft:
        reasons.append(
            f"{vessel.vessel_class} draft ({vessel.draft}m) exceeds {dest_port.name}'s "
            f"max draft limit ({dest_port.max_draft}m)"
        )
    if origin_port.max_loa is not None and vessel.loa > origin_port.max_loa:
        reasons.append(
            f"{vessel.vessel_class} LOA ({vessel.loa}m) exceeds {origin_port.name}'s "
            f"max LOA limit ({origin_port.max_loa}m)"
        )
    if dest_port.max_loa is not None and vessel.loa > dest_port.max_loa:
        reasons.append(
            f"{vessel.vessel_class} LOA ({vessel.loa}m) exceeds {dest_port.name}'s "
            f"max LOA limit ({dest_port.max_loa}m)"
        )
    if vessel.beam is not None:
        if origin_port.max_beam is not None and vessel.beam > origin_port.max_beam:
            reasons.append(
                f"{vessel.vessel_class} beam ({vessel.beam}m) exceeds {origin_port.name}'s "
                f"max beam limit ({origin_port.max_beam}m)"
            )
        if dest_port.max_beam is not None and vessel.beam > dest_port.max_beam:
            reasons.append(
                f"{vessel.vessel_class} beam ({vessel.beam}m) exceeds {dest_port.name}'s "
                f"max beam limit ({dest_port.max_beam}m)"
            )

    if reasons:
        return PredictResponse(
            feasible=False,
            infeasibility_reason=f"Vessel physically incompatible with this route: {'; '.join(reasons)}.",
            predicted_rate_per_mt=None,
            confidence_range=None,
            confidence_pct=None,
            forecast_date=None,
            based_on_index=None,
        )

    # Resolve route distance
    route = (
        db.query(RouteDistance)
        .filter(
            RouteDistance.loading_port.ilike(origin_port.name),
            RouteDistance.discharge_port.ilike(dest_port.name),
        )
        .first()
    )
    if not route:
        return PredictResponse(
            feasible=False,
            infeasibility_reason=f"No shipping route found from {origin_port.name} to {dest_port.name}",
            predicted_rate_per_mt=None,
            confidence_range=None,
            confidence_pct=None,
            forecast_date=None,
            based_on_index=None,
        )

    try:
        result = get_spec_forecast(
            idx, db, forecast_horizon_days=payload.forecast_horizon_days
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Convert index points to USD/MT using distance-based multiplier
    # Industry: shorter routes have higher per-MT costs (lower utilization margin)
    # Longer routes have lower per-MT costs (economies of scale)
    # Base: 0.004 USD/MT per index point for ~3000nm route
    # Adjust: ±0.0005 per 1000nm deviation from baseline
    BASE_DISTANCE = 3000.0
    BASE_MULTIPLIER = 0.004
    distance_adj = (route.distance_nm - BASE_DISTANCE) / 1000.0
    multiplier = BASE_MULTIPLIER - (distance_adj * 0.0005)
    multiplier = max(0.002, min(0.008, multiplier))  # Clamp between 0.002 and 0.008

    last_day = result["forecast"][-1]
    predicted_rate = round(last_day["predicted_value"] * multiplier, 4)
    low_rate = round(last_day["low"] * multiplier, 4)
    high_rate = round(last_day["high"] * multiplier, 4)

    return PredictResponse(
        feasible=True,
        infeasibility_reason=None,
        predicted_rate_per_mt=predicted_rate,
        confidence_range=ConfidenceRange(low=low_rate, high=high_rate),
        confidence_pct=result["confidence_pct"],
        forecast_date=last_day["date"],
        based_on_index=idx.upper(),
    )
