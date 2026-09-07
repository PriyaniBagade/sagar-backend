from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Literal, Union

from app.config.database import get_db
from app.services.freight_prediction import (
    get_forecast,
    get_all_forecasts,
    get_forecast_history,
    INDICES,
)
from app.jobs.ingest import run_source, SOURCE_RUNNERS
from app.schemas.freight_prediction import (
    ForecastResponse,
    ForecastHistoryItem,
    IngestResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Freight Forecasting"])

IndexLiteral = Literal["bdi", "bci", "bpi", "bsi"]


@router.get(
    "/forecast/all",
    summary="Forecast all four indices in one call",
    description="Returns BDI, BCI, BPI, BSI forecasts. Pass `days` for multi-day outlook on all.",
)
def forecast_all(
    days: int = Query(
        default=1, ge=1, le=30, description="Number of business days ahead"
    ),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return get_all_forecasts(db, days=days)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get(
    "/forecast/{index}",
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
) -> Union[ForecastResponse, list[ForecastResponse]]:
    try:
        return get_forecast(index, db, days=days)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get(
    "/forecast/{index}/history",
    response_model=list[ForecastHistoryItem],
    summary="Predicted vs actual history for an index",
)
def forecast_history(index: IndexLiteral, db: Session = Depends(get_db)):
    try:
        return get_forecast_history(index, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/ingest/{source}",
    response_model=IngestResponse,
    summary="Manually trigger a single scraper (debug aid)",
    include_in_schema=False,  # hidden from Swagger — internal use only
)
def ingest_source(source: str):
    if source not in SOURCE_RUNNERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source '{source}'. Valid: {list(SOURCE_RUNNERS.keys())}",
        )
    result = run_source(source)
    return IngestResponse(
        source=source,
        status="ok" if result.ok else "failed",
        rows_ingested=1 if result.ok else 0,
        rows_quarantined=result.rows_quarantined,
        error=result.error,
    )
