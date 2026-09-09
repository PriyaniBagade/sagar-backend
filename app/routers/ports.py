from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.models.port import Port, PortType
from app.models.vessel_class import VesselClass
from app.models.feature_store import FeatureStoreRow
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

router = APIRouter(tags=["Ports & Vessel Classes"])


class PortResponse(BaseModel):
    id: str
    name: str
    country: str
    type: str
    max_draft: Optional[float]
    max_loa: Optional[float]
    max_beam: Optional[float]
    berths: Optional[int]
    handling_rate: Optional[float]

    class Config:
        from_attributes = True


@router.get("/api/ports", response_model=list[PortResponse])
def list_ports(
    port_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Port)
    if port_type:
        try:
            q = q.filter(Port.type == PortType[port_type.upper()])
        except KeyError:
            pass
    ports = q.order_by(Port.country, Port.name).all()
    return [
        PortResponse(
            id=str(p.id),
            name=p.name,
            country=p.country,
            type=p.type.value,
            max_draft=p.max_draft,
            max_loa=p.max_loa,
            max_beam=p.max_beam,
            berths=p.berths,
            handling_rate=p.handling_rate,
        )
        for p in ports
    ]


class VesselClassResponse(BaseModel):
    id: str
    vessel_class: str
    dwt: float
    draft: float
    loa: float
    beam: Optional[float]
    charter_cost_per_day: Optional[float]

    class Config:
        from_attributes = True


@router.get("/api/vessel-classes", response_model=list[VesselClassResponse])
def list_vessel_classes(db: Session = Depends(get_db)):
    classes = db.query(VesselClass).order_by(VesselClass.dwt).all()
    return [
        VesselClassResponse(
            id=str(v.id),
            vessel_class=v.vessel_class,
            dwt=v.dwt,
            draft=v.draft,
            loa=v.loa,
            beam=v.beam,
            charter_cost_per_day=v.charter_cost_per_day,
        )
        for v in classes
    ]


class MarketSnapshotResponse(BaseModel):
    date: Optional[str]
    bdi: Optional[float]
    bci: Optional[float]
    bpi: Optional[float]
    bsi: Optional[float]
    bdi_change: Optional[float]  # vs previous day
    bci_change: Optional[float]
    bpi_change: Optional[float]
    bsi_change: Optional[float]
    vlsfo_price_usd: Optional[float]
    coking_coal_price_usd: Optional[float]


@router.get("/api/market/snapshot", response_model=MarketSnapshotResponse)
def market_snapshot(db: Session = Depends(get_db)):
    rows = (
        db.query(FeatureStoreRow).order_by(FeatureStoreRow.date.desc()).limit(2).all()
    )
    if not rows:
        return MarketSnapshotResponse(
            date=None,
            bdi=None,
            bci=None,
            bpi=None,
            bsi=None,
            bdi_change=None,
            bci_change=None,
            bpi_change=None,
            bsi_change=None,
            vlsfo_price_usd=None,
            coking_coal_price_usd=None,
        )
    latest = rows[0]
    prev = rows[1] if len(rows) > 1 else None

    def chg(curr, previous):
        if curr is None or previous is None or previous == 0:
            return None
        return round(((curr - previous) / previous) * 100, 2)

    return MarketSnapshotResponse(
        date=str(latest.date),
        bdi=latest.bdi,
        bci=latest.bci,
        bpi=latest.bpi,
        bsi=latest.bsi,
        bdi_change=chg(latest.bdi, prev.bdi if prev else None),
        bci_change=chg(latest.bci, prev.bci if prev else None),
        bpi_change=chg(latest.bpi, prev.bpi if prev else None),
        bsi_change=chg(latest.bsi, prev.bsi if prev else None),
        vlsfo_price_usd=latest.vlsfo_price_usd,
        coking_coal_price_usd=latest.coking_coal_price_usd,
    )
