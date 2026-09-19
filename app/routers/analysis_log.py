"""
GET /api/v1/analysis-log

Returns a list of saved analysis runs for the My Analysis page.
Pulls real data from existing DB tables (vessel_requests, forecasts) and
supplements with demo records for modules that don't persist runs yet.
"""

import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.config.database import get_db
from app.models.vessel_request import VesselOptimizationRequest
from app.models.forecast import Forecast
from app.models.port import Port

router = APIRouter(prefix="/api/v1", tags=["Analysis Log"])

# Module label mapping
MODULE_LABELS = {
    "vessel_optimization": "Vessel optimization",
    "freight_forecast": "Freight forecast",
    "landed_cost": "Total landed cost",
    "market_timing": "Market entry timing",
    "risk_mitigation": "Risk mitigation",
    "idle_scenario": "Idle scenario",
}


def _fmt_ts(dt: datetime.datetime | datetime.date | None) -> str:
    if dt is None:
        return "—"
    if isinstance(dt, datetime.datetime):
        return (
            dt.strftime("%-d %b %Y, %-I:%M %p").replace("AM", "am").replace("PM", "pm")
        )
    return dt.strftime("%-d %b %Y")


@router.get("/analysis-log", summary="Recent analysis runs across all modules")
def analysis_log(db: Session = Depends(get_db)) -> list[dict]:
    runs: list[dict] = []

    # ── 1. Vessel optimization requests ──────────────────────────────────────
    try:
        vessel_rows = (
            db.query(VesselOptimizationRequest)
            .order_by(desc(VesselOptimizationRequest.created_at))
            .limit(10)
            .all()
        )
        for row in vessel_rows:
            # Resolve port names
            load_port = db.query(Port).filter(Port.id == row.loading_port_id).first()
            disc_port = db.query(Port).filter(Port.id == row.discharge_port_id).first()
            origin = load_port.name if load_port else "—"
            dest = disc_port.name if disc_port else "—"

            runs.append(
                {
                    "id": str(row.id),
                    "module": "vessel_optimization",
                    "title": "Vessel optimization",
                    "subtitle": f"{origin} \u2192 {dest}",
                    "result": row.selected_class or "—",
                    "result_color": "default",
                    "timestamp": _fmt_ts(row.created_at),
                    "href": "/dashboard/vessel-optimization",
                }
            )
    except Exception:
        pass

    # ── 2. Freight forecast runs (from forecasts table) ───────────────────────
    try:
        # One entry per unique date_generated × index pair, latest 10
        forecast_rows = (
            db.query(Forecast).order_by(desc(Forecast.date_generated)).limit(20).all()
        )
        seen_dates: set[str] = set()
        for row in forecast_rows:
            key = str(row.date_generated)
            if key in seen_dates:
                continue
            seen_dates.add(key)
            runs.append(
                {
                    "id": str(row.id),
                    "module": "freight_forecast",
                    "title": "Freight forecast",
                    "subtitle": f"{row.index.upper()} \u00b7 {row.model_version} model",
                    "result": f"{row.index.upper()} {int(row.point_forecast):,}",
                    "result_color": "default",
                    "timestamp": _fmt_ts(row.date_generated),
                    "href": "/dashboard/forecast",
                }
            )
            if len(seen_dates) >= 5:
                break
    except Exception:
        pass

    # ── 3. Sort combined by timestamp desc (best-effort) ─────────────────────
    # No universal created_at across tables — keep insertion order for now.

    return runs
