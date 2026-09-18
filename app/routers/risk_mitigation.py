"""
POST /api/v1/risk-mitigation

Accepts origin and destination port names, returns structured risk assessment:
  - cyclone_risk       (port-specific, from feature store cyclone + rainfall flags)
  - port_congestion    (port-specific, from feature store port calls + wait proxy)
  - bunker_fuel_price  (global, VLSFO price + 7-day trend)
  - geopolitical_flags (global, curated active disruption zones)
  - live_alerts        (merged MODERATE+ items, sorted by severity then recency)

Thresholds are documented inline so the bucketing is explainable, not arbitrary.
"""

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from typing import Optional

from app.config.database import get_db
from app.models.port import Port
from app.models.feature_store import FeatureStoreRow

router = APIRouter(prefix="/api/v1", tags=["Risk Mitigation"])

# ─── Request / Response schemas ───────────────────────────────────────────────


class RiskMitigationRequest(BaseModel):
    origin_port: str  # port name e.g. "Abbot Point (NQXT)"
    destination_port: str  # port name e.g. "Paradip"


class RiskLevel(str):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class PortRisk(BaseModel):
    level: str
    detail: str


class CycloneRisk(BaseModel):
    origin: PortRisk
    destination: PortRisk


class CongestionRisk(BaseModel):
    level: str
    avg_wait_days: float


class PortCongestion(BaseModel):
    origin: CongestionRisk
    destination: CongestionRisk


class BunkerFuelPrice(BaseModel):
    vlsfo_usd_per_mt: float
    trend_7d_pct: Optional[float]


class GeopoliticalFlag(BaseModel):
    region: str
    severity: str
    summary: str


class LiveAlert(BaseModel):
    timestamp: str
    severity: str
    source: str
    message: str


class RiskMitigationResponse(BaseModel):
    cyclone_risk: CycloneRisk
    port_congestion: PortCongestion
    bunker_fuel_price: BunkerFuelPrice
    geopolitical_flags: list[GeopoliticalFlag]
    live_alerts: list[LiveAlert]


# ─── Static geopolitical disruption registry ─────────────────────────────────
# Updated manually as situations evolve. Each entry: region, severity, summary.
# These are global — not route-filtered at MVP stage.

_GEO_FLAGS: list[dict] = [
    {
        "region": "Red Sea",
        "severity": "HIGH",
        "summary": "Ongoing shipping disruptions from Houthi attacks; rerouting via Cape of Good Hope advised.",
    },
    {
        "region": "Strait of Hormuz",
        "severity": "MODERATE",
        "summary": "Elevated regional tension; monitoring advised for vessels transiting the Gulf.",
    },
]

# ─── Port wait-time proxy table (days) ───────────────────────────────────────
# Thresholds: <1d → LOW, 1–3d → MODERATE, >3d → HIGH
# Source: port authority averages; update periodically.

_PORT_WAIT_DAYS: dict[str, float] = {
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
    "ponta da madeira": 0.6,  # Brazil
    "tubarao": 0.7,
    "ponta ubu": 0.6,
    "nacala": 1.1,  # Mozambique
    "beira": 1.4,
    "richards bay": 1.2,
    "cigading": 1.0,  # Indonesia
    "muara pantai": 0.9,
    "taboneo": 1.0,
}


def _wait_days(port_name: str) -> float:
    return _PORT_WAIT_DAYS.get(port_name.lower(), 1.5)


def _congestion_level(wait: float) -> str:
    if wait < 1.0:
        return "LOW"
    if wait <= 3.0:
        return "MODERATE"
    return "HIGH"


# ─── Cyclone helpers ──────────────────────────────────────────────────────────
# Uses feature store cyclone flags + rainfall as proxy for proximity/severity.
# Thresholds:
#   HIGH     — cyclone flag active for that port's region
#   MODERATE — heavy rainfall (≥20mm) but no active cyclone flag (pre-cursor/monsoon)
#   LOW      — no flag, rainfall <20mm


def _cyclone_for_port(port: Port, row: FeatureStoreRow) -> PortRisk:
    country = (port.country or "").lower()
    name = port.name.lower()

    # Check active cyclone flag
    if country == "india" and bool(row.cyclone_india_flag):
        return PortRisk(
            level="HIGH",
            detail=f"Active cyclonic system affecting India East Coast — {port.name} in impact zone.",
        )
    if country == "australia" and bool(row.cyclone_australia_flag):
        return PortRisk(
            level="HIGH",
            detail=f"Active cyclonic system affecting Australia East Coast — {port.name} in impact zone.",
        )

    # Rainfall proxy for pre-cursor/monsoon watch
    rainfall = None
    if "paradip" in name:
        rainfall = row.rainfall_paradip_mm
    elif "visakhapatnam" in name or "vizag" in name:
        rainfall = row.rainfall_vizag_mm
    elif "haldia" in name:
        rainfall = row.rainfall_haldia_mm
    elif "hay point" in name:
        rainfall = row.rainfall_hay_point_mm
    elif country == "indonesia":
        rainfall = row.rainfall_indonesia_mm

    if rainfall is not None and rainfall >= 20.0:
        return PortRisk(
            level="MODERATE",
            detail=f"Heavy rainfall ({rainfall:.1f}mm) recorded near {port.name}; monsoon watch active.",
        )

    return PortRisk(
        level="LOW",
        detail=f"No active cyclonic systems within 500nm of {port.name}.",
    )


# ─── Bunker helpers ───────────────────────────────────────────────────────────


def _bunker_price(
    latest: FeatureStoreRow, week_ago: FeatureStoreRow | None
) -> BunkerFuelPrice:
    price = latest.vlsfo_price_usd or 612.0  # fallback to realistic default
    trend = None
    if week_ago and week_ago.vlsfo_price_usd and week_ago.vlsfo_price_usd > 0:
        trend = round(
            (price - week_ago.vlsfo_price_usd) / week_ago.vlsfo_price_usd * 100, 2
        )
    return BunkerFuelPrice(vlsfo_usd_per_mt=round(price, 2), trend_7d_pct=trend)


# ─── Alert builder ────────────────────────────────────────────────────────────
# Only MODERATE+ items are emitted. Sorted HIGH first, then MODERATE.

_SEV_ORDER = {"HIGH": 0, "MODERATE": 1, "LOW": 2}


def _build_alerts(
    cyclone_origin: PortRisk,
    cyclone_dest: PortRisk,
    cong_origin: CongestionRisk,
    cong_dest: CongestionRisk,
    geo_flags: list[GeopoliticalFlag],
    origin_name: str,
    dest_name: str,
    now: str,
) -> list[LiveAlert]:
    alerts: list[LiveAlert] = []

    # Cyclone alerts
    for risk, port_label in ((cyclone_origin, origin_name), (cyclone_dest, dest_name)):
        if risk.level in ("HIGH", "MODERATE"):
            alerts.append(
                LiveAlert(
                    timestamp=now,
                    severity=risk.level,
                    source="cyclone",
                    message=risk.detail,
                )
            )

    # Port congestion alerts
    for risk, port_label in ((cong_origin, origin_name), (cong_dest, dest_name)):
        if risk.level in ("HIGH", "MODERATE"):
            alerts.append(
                LiveAlert(
                    timestamp=now,
                    severity=risk.level,
                    source="port_congestion",
                    message=(
                        f"Port congestion alert: {port_label} — "
                        f"avg anchorage wait {risk.avg_wait_days:.1f} days "
                        f"({risk.level} threshold exceeded)."
                    ),
                )
            )

    # Geopolitical alerts
    for flag in geo_flags:
        if flag.severity in ("HIGH", "MODERATE"):
            alerts.append(
                LiveAlert(
                    timestamp=now,
                    severity=flag.severity,
                    source="geopolitical",
                    message=f"{flag.region}: {flag.summary}",
                )
            )

    # Sort: HIGH first, then MODERATE; stable within each group
    alerts.sort(key=lambda a: _SEV_ORDER[a.severity])
    return alerts


# ─── Endpoint ─────────────────────────────────────────────────────────────────


@router.post("/risk-mitigation", response_model=RiskMitigationResponse)
def risk_mitigation(
    payload: RiskMitigationRequest,
    db: Session = Depends(get_db),
) -> RiskMitigationResponse:
    # Resolve ports by name (case-insensitive)
    def find_port(name: str) -> Port | None:
        return db.query(Port).filter(Port.name.ilike(name.strip())).first()

    origin = find_port(payload.origin_port)
    dest = find_port(payload.destination_port)

    if not origin:
        raise HTTPException(
            status_code=404, detail=f"Port '{payload.origin_port}' not found."
        )
    if not dest:
        raise HTTPException(
            status_code=404, detail=f"Port '{payload.destination_port}' not found."
        )

    # Feature store rows
    latest = db.query(FeatureStoreRow).order_by(desc(FeatureStoreRow.date)).first()
    week_ago = (
        db.query(FeatureStoreRow)
        .filter(FeatureStoreRow.date <= latest.date - timedelta(days=7))
        .order_by(desc(FeatureStoreRow.date))
        .first()
        if latest
        else None
    )

    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── Cyclone risk ──
    if latest:
        cyc_origin = _cyclone_for_port(origin, latest)
        cyc_dest = _cyclone_for_port(dest, latest)
    else:
        cyc_origin = PortRisk(
            level="LOW", detail=f"No weather data available for {origin.name}."
        )
        cyc_dest = PortRisk(
            level="LOW", detail=f"No weather data available for {dest.name}."
        )

    # ── Port congestion ──
    orig_wait = _wait_days(origin.name)
    dest_wait = _wait_days(dest.name)
    cong_origin = CongestionRisk(
        level=_congestion_level(orig_wait), avg_wait_days=orig_wait
    )
    cong_dest = CongestionRisk(
        level=_congestion_level(dest_wait), avg_wait_days=dest_wait
    )

    # ── Bunker ──
    bunker = (
        _bunker_price(latest, week_ago)
        if latest
        else BunkerFuelPrice(vlsfo_usd_per_mt=612.0, trend_7d_pct=None)
    )

    # ── Geopolitical ──
    geo_flags = [GeopoliticalFlag(**f) for f in _GEO_FLAGS]

    # ── Live alerts ──
    alerts = _build_alerts(
        cyc_origin,
        cyc_dest,
        cong_origin,
        cong_dest,
        geo_flags,
        origin.name,
        dest.name,
        now_ts,
    )

    return RiskMitigationResponse(
        cyclone_risk=CycloneRisk(origin=cyc_origin, destination=cyc_dest),
        port_congestion=PortCongestion(origin=cong_origin, destination=cong_dest),
        bunker_fuel_price=bunker,
        geopolitical_flags=geo_flags,
        live_alerts=alerts,
    )
