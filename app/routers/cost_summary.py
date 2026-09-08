from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.port import Port
from app.models.vessel_class import VesselClass
from app.models.route_distance import RouteDistance
from app.models.feature_store import FeatureStoreRow
from app.models.vessel_request import VesselOptimizationRequest as VesselRequestModel
from app.schemas.cost_summary import (
    CostSummaryRequest,
    CostSummaryResponse,
    CostHero,
    CostBreakdown,
    VoyageDays,
)
from app.services.cost_summary import compute_cost_summary, INDEX_COLUMN
from app.config.vessel_cost import DEFAULT_LOAD_RATE_MTPD, DEFAULT_DISCHARGE_RATE_MTPD

router = APIRouter(prefix="/api/vessel", tags=["Vessel Optimization"])

_FALLBACK_VLSFO = 600.0
_FALLBACK_MGO = 700.0
_FALLBACK_INDEX = 1500.0


@router.post("/cost-summary", response_model=CostSummaryResponse)
def cost_summary(payload: CostSummaryRequest, db: Session = Depends(get_db)):

    # --- 1. Resolve vessel class by ID ---
    vessel = (
        db.query(VesselClass).filter(VesselClass.id == payload.vessel_class_id).first()
    )
    if not vessel:
        raise HTTPException(
            status_code=404, detail=f"Vessel class {payload.vessel_class_id} not found"
        )

    vc = vessel.vessel_class.lower()
    if vc not in INDEX_COLUMN:
        raise HTTPException(
            status_code=422,
            detail=f"Vessel class '{vessel.vessel_class}' is not supported. "
            f"Must be one of: {list(INDEX_COLUMN.keys())}",
        )

    # --- 2. Resolve load port by ID ---
    load_port = db.query(Port).filter(Port.id == payload.load_port_id).first()
    if not load_port:
        raise HTTPException(
            status_code=404, detail=f"Load port {payload.load_port_id} not found"
        )

    # --- 3. Resolve discharge port by ID ---
    discharge_port = db.query(Port).filter(Port.id == payload.discharge_port_id).first()
    if not discharge_port:
        raise HTTPException(
            status_code=404,
            detail=f"Discharge port {payload.discharge_port_id} not found",
        )

    # --- 4. Resolve route using port names resolved from DB ---
    route = (
        db.query(RouteDistance)
        .filter(
            RouteDistance.loading_port.ilike(load_port.name),
            RouteDistance.discharge_port.ilike(discharge_port.name),
        )
        .first()
    )
    if not route:
        raise HTTPException(
            status_code=404,
            detail=f"No route found from '{load_port.name}' to '{discharge_port.name}' in route_distances table.",
        )

    # --- 5. Get live bunker prices + index points from feature store ---
    store_row = db.query(FeatureStoreRow).order_by(FeatureStoreRow.date.desc()).first()

    vlsfo_price = (
        store_row.vlsfo_price_usd
        if store_row and store_row.vlsfo_price_usd
        else _FALLBACK_VLSFO
    )
    mgo_price = (
        store_row.mgo_price_usd
        if store_row and store_row.mgo_price_usd
        else _FALLBACK_MGO
    )
    index_col = INDEX_COLUMN[vc]
    index_pts = (
        getattr(store_row, index_col) if store_row else None
    ) or _FALLBACK_INDEX

    # --- 6. Port charges — handling rates use config defaults (columns removed) ---
    load_charges = load_port.port_charges_flat_usd or 0.0
    discharge_charges = discharge_port.port_charges_flat_usd or 0.0

    # --- 7. Run calculation ---
    result = compute_cost_summary(
        vessel_class=vc,
        quantity_mt=payload.quantity_mt,
        distance_nm=route.distance_nm,
        route_type=route.route_type,
        load_rate_mtpd=DEFAULT_LOAD_RATE_MTPD,
        discharge_rate_mtpd=DEFAULT_DISCHARGE_RATE_MTPD,
        load_port_charges=load_charges,
        discharge_port_charges=discharge_charges,
        vlsfo_price=vlsfo_price,
        mgo_price=mgo_price,
        index_points=index_pts,
    )

    # --- 8. Persist to DB ---
    db_record = VesselRequestModel(
        loading_port_id=load_port.id,
        discharge_port_id=discharge_port.id,
        quantity_mt=payload.quantity_mt,
        selected_class=vessel.vessel_class,
        sailing_days=result.sailing_days,
        load_days=result.load_days,
        discharge_days=result.discharge_days,
        canal_extra_days=result.canal_extra_days,
        voyage_days=result.voyage_days,
        freight_cost_usd=result.freight_cost,
        port_charges_usd=result.port_charges,
        bunker_cost_usd=result.bunker_cost,
        canal_toll_usd=result.canal_toll,
        commission_usd=result.commission,
        opex_total_usd=result.opex_total,
        net_result_usd=result.net_result,
        tce_per_day=result.tce_per_day,
        landed_cost_per_mt=result.landed_cost_per_mt,
        cost_confidence=result.tag,
        vlsfo_price_used=result.vlsfo_price_used,
        mgo_price_used=result.mgo_price_used,
        index_points_used=result.index_points_used,
        index_to_price_ratio=result.index_multiplier_used,
        route_distance_nm=result.route_distance_nm,
        route_type=result.route_type,
    )
    db.add(db_record)
    db.commit()

    # --- 9. Build response ---
    return CostSummaryResponse(
        hero=CostHero(
            landed_cost_per_mt=result.landed_cost_per_mt,
            tag=result.tag,
            why=result.why,
        ),
        breakdown=CostBreakdown(
            voyage_days=VoyageDays(
                sailing_days=result.sailing_days,
                load_days=result.load_days,
                discharge_days=result.discharge_days,
                canal_extra_days=result.canal_extra_days,
                total=result.voyage_days,
            ),
            freight_cost=result.freight_cost,
            port_charges=result.port_charges,
            bunker_cost=result.bunker_cost,
            canal_toll=result.canal_toll,
            commission=result.commission,
            opex_total=result.opex_total,
            net_result=result.net_result,
            tce_per_day=result.tce_per_day,
        ),
    )
