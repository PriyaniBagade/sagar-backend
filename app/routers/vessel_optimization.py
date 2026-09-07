from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.models.port import Port
from app.models.vessel_class import VesselClass
from app.schemas.vessel_optimization import (
    VesselOptimizationRequest,
    VesselOptimizationResponse,
    RejectedClass,
)
from app.services.vessel_optimization import optimize_vessel, PortData, VesselClassData

router = APIRouter(prefix="/api", tags=["Vessel Optimization"])


@router.post("/vessel-optimization", response_model=VesselOptimizationResponse)
def vessel_optimization(
    payload: VesselOptimizationRequest, db: Session = Depends(get_db)
):
    loading_port = db.query(Port).filter(Port.id == payload.loading_port_id).first()
    discharge_port = db.query(Port).filter(Port.id == payload.discharge_port_id).first()

    if not loading_port:
        raise HTTPException(
            status_code=404, detail=f"Loading port {payload.loading_port_id} not found"
        )
    if not discharge_port:
        raise HTTPException(
            status_code=404,
            detail=f"Discharge port {payload.discharge_port_id} not found",
        )

    vessel_classes = db.query(VesselClass).all()

    lp = PortData(
        id=str(loading_port.id),
        name=loading_port.name,
        country=loading_port.country,
        port_type=loading_port.type.value,
        max_draft=loading_port.max_draft,
        max_loa=loading_port.max_loa,
        max_beam=loading_port.max_beam,
    )
    dp = PortData(
        id=str(discharge_port.id),
        name=discharge_port.name,
        country=discharge_port.country,
        port_type=discharge_port.type.value,
        max_draft=discharge_port.max_draft,
        max_loa=discharge_port.max_loa,
        max_beam=discharge_port.max_beam,
    )
    vessels = [
        VesselClassData(
            id=str(v.id),
            vessel_class=v.vessel_class,
            dwt=v.dwt,
            draft=v.draft,
            loa=v.loa,
            beam=v.beam,
            charter_cost_per_day=v.charter_cost_per_day,
            berthing_fee_per_day=v.berthing_fee_per_day,
        )
        for v in vessel_classes
    ]

    try:
        result = optimize_vessel(lp, dp, payload.cargo_quantity, vessels)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return VesselOptimizationResponse(
        recommended_class=result.recommended_class,
        voyages_needed=result.voyages_needed,
        eligible_classes=result.eligible_classes,
        rejected_classes=[RejectedClass(**r) for r in result.rejected_classes],
        warnings=result.warnings,
    )
