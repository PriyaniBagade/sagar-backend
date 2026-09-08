"""Fixed-rule, DB-backed risk summary for a selected voyage."""

from datetime import timedelta
import re
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.feature_store import FeatureStoreRow
from app.models.port import Port
from app.schemas.risk_summary import RiskCategory, RiskLevel, RiskSummaryResponse

RAINFALL_BY_PORT = (
    ("paradip", "rainfall_paradip_mm", "Paradip"),
    ("visakhapatnam", "rainfall_vizag_mm", "Visakhapatnam"),
    ("haldia", "rainfall_haldia_mm", "Haldia"),
    ("hay point", "rainfall_hay_point_mm", "Hay Point"),
    ("indonesia", "rainfall_indonesia_mm", "Indonesia"),
)


def normalise_port_name(name: str) -> str:
    """Match query values to seeded port names despite dash variants."""
    cleaned = name.replace("\u2014", "-").replace("\u2013", "-").replace("\ufffd", "-")
    return re.sub(r"\s+", " ", cleaned.strip()).casefold()


def port_region(port: Port) -> str:
    country = (port.country or "").casefold()
    if country == "australia":
        return "Australia East Coast"
    if country == "india":
        return "India East Coast"
    if country == "indonesia":
        return "Indonesia"
    if country == "mozambique":
        return "Mozambique"
    return port.country or "Unknown"


def _rainfall_for_port(
    row: FeatureStoreRow, port: Port
) -> tuple[float | None, str | None]:
    name, country = normalise_port_name(port.name), (port.country or "").casefold()
    for needle, column, label in RAINFALL_BY_PORT:
        if needle in name or (needle == "indonesia" and country == "indonesia"):
            return getattr(row, column, None), label
    return None, None


def _weather_risk(row: FeatureStoreRow, loading: Port, discharge: Port) -> RiskCategory:
    cyclone_regions: list[str] = []
    for port in (loading, discharge):
        region = port_region(port)
        if (region == "India East Coast" and bool(row.cyclone_india_flag)) or (
            region == "Australia East Coast" and bool(row.cyclone_australia_flag)
        ):
            cyclone_regions.append(region)
    if cyclone_regions:
        return RiskCategory(
            risk=RiskLevel.HIGH,
            reason=f"Active cyclone affects {', '.join(dict.fromkeys(cyclone_regions))} on this voyage.",
        )

    readings: list[tuple[float, str, str]] = []
    for phase, port in (("loading", loading), ("discharge", discharge)):
        rainfall, label = _rainfall_for_port(row, port)
        if rainfall is not None and label is not None:
            readings.append((rainfall, label, phase))
    for threshold, risk, adjective in (
        (20.0, RiskLevel.MEDIUM, "Heavy"),
        (5.0, RiskLevel.LOW, "Moderate"),
    ):
        matches = [item for item in readings if item[0] >= threshold]
        if matches:
            value, label, phase = matches[0]
            return RiskCategory(
                risk=risk,
                reason=f"{adjective} rainfall of {value:.1f} mm recorded for {label} during {phase}.",
            )
    if readings:
        values = "; ".join(f"{label}: {value:.1f} mm" for value, label, _ in readings)
        return RiskCategory(
            risk=RiskLevel.LOW,
            reason=f"No active cyclone and recorded route rainfall is below 5.0 mm ({values}).",
        )
    return RiskCategory(
        risk=RiskLevel.LOW,
        reason="No active cyclone affects a mapped region; no rainfall field exists for either selected port.",
    )


def _bunker_risk(
    latest: FeatureStoreRow, baseline: FeatureStoreRow | None
) -> RiskCategory:
    current, previous = latest.vlsfo_price_usd, (
        baseline.vlsfo_price_usd if baseline else None
    )
    if current is None or previous is None or previous == 0:
        return RiskCategory(
            risk=RiskLevel.LOW,
            reason="VLSFO 7-day comparison is unavailable because a price record is missing.",
        )
    change = (current - previous) / previous * 100
    level = (
        RiskLevel.HIGH
        if change > 5
        else RiskLevel.MEDIUM if change >= 2 else RiskLevel.LOW
    )
    direction = "risen" if change >= 0 else "fallen"
    return RiskCategory(
        risk=level,
        reason=f"VLSFO has {direction} {abs(change):.1f}% over the last 7 days (${previous:.0f} to ${current:.0f}/MT).",
    )


def _port_activity_risk(
    row: FeatureStoreRow, loading: Port, discharge: Port
) -> RiskCategory:
    # Existing data is a total across monitored ports, not activity for each port.
    if row.total_port_calls is None:
        return RiskCategory(
            risk=RiskLevel.LOW,
            reason="No monitored-port activity value is available for the selected ports.",
        )
    if row.total_port_calls > 500:
        return RiskCategory(
            risk=RiskLevel.MEDIUM,
            reason=(
                f"High monitored-port activity: {row.total_port_calls:.0f} total dry-bulk calls. "
                f"The aggregate is not stored per port, so activity cannot be attributed solely to "
                f"{loading.name} or {discharge.name}."
            ),
        )
    return RiskCategory(
        risk=RiskLevel.LOW,
        reason=(
            f"The database records {row.total_port_calls:.0f} total dry-bulk calls across monitored ports, "
            f"but no per-port activity record for {loading.name} or {discharge.name}; defaulting to LOW."
        ),
    )


def _geopolitical_risk(
    row: FeatureStoreRow, loading: Port, discharge: Port
) -> RiskCategory:
    # The current table has a global aggregate, with no affected-route attribute.
    if not bool(row.geo_flag):
        return RiskCategory(
            risk=RiskLevel.LOW,
            reason="No active geopolitical disruptions are recorded.",
        )
    return RiskCategory(
        risk=RiskLevel.LOW,
        reason=(
            "An active global geopolitical score is recorded, but the database does not store "
            f"affected routes, so it cannot be matched to {loading.name} -> {discharge.name}."
        ),
    )


def get_risk_summary(
    db: Session, loading_port_id: UUID, discharge_port_id: UUID
) -> RiskSummaryResponse:
    """Return the current fixed-rule risks for the requested voyage."""
    loading = db.query(Port).filter(Port.id == loading_port_id).first()
    discharge = db.query(Port).filter(Port.id == discharge_port_id).first()
    if loading is None or discharge is None:
        missing_id = loading_port_id if loading is None else discharge_port_id
        raise ValueError(f"Port '{missing_id}' was not found in the ports table")

    latest = db.query(FeatureStoreRow).order_by(desc(FeatureStoreRow.date)).first()
    route = {"loading_port": loading.name, "discharge_port": discharge.name}
    if latest is None:
        no_data = RiskCategory(
            risk=RiskLevel.LOW, reason="No feature-store row is available."
        )
        return RiskSummaryResponse(
            route=route,
            weather=no_data,
            bunker=no_data,
            port_activity=no_data,
            geopolitical=no_data,
        )
    baseline = (
        db.query(FeatureStoreRow)
        .filter(FeatureStoreRow.date <= latest.date - timedelta(days=7))
        .order_by(desc(FeatureStoreRow.date))
        .first()
    )
    return RiskSummaryResponse(
        route=route,
        weather=_weather_risk(latest, loading, discharge),
        bunker=_bunker_risk(latest, baseline),
        port_activity=_port_activity_risk(latest, loading, discharge),
        geopolitical=_geopolitical_risk(latest, loading, discharge),
    )
