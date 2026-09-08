"""Read-only endpoint for the fixed-rule risk dashboard."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID

from app.config.database import get_db
from app.schemas.risk_summary import RiskSummaryResponse
from app.services.risk_summary import get_risk_summary

router = APIRouter(tags=["Risk"])


@router.get(
    "/risk/summary",
    response_model=RiskSummaryResponse,
    summary="Return the current traffic-light risk summary",
)
def risk_summary(
    loading_port_id: UUID = Query(...),
    discharge_port_id: UUID = Query(...),
    db: Session = Depends(get_db),
) -> RiskSummaryResponse:
    """Assess the latest feature-store values using fixed rules only."""
    try:
        return get_risk_summary(db, loading_port_id, discharge_port_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
