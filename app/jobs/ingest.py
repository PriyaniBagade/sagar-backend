"""
Ingest job — runs all 11 scrapers, validates output, writes to the
raw landing zone (feature_store raw columns), quarantines failures.

Call run_all() on a schedule or trigger POST /api/v1/ingest/{source}
to run a single scraper for debugging.
"""

import logging
from datetime import date
from sqlalchemy.orm import Session

from app.scrapers import (
    bdi,
    bunker,
    coking_coal,
    cyclone,
    geo_disruption,
    malacca,
    manufacturing_pmi,
    port_activity,
    rainfall,
    seasonality,
    steel_production,
)
from app.scrapers.base import ScraperResult
from app.models.feature_store import FeatureStoreRow
from app.config.database import SessionLocal

log = logging.getLogger(__name__)

# staleness thresholds in days — daily sources vs monthly
STALENESS_DAYS = {
    "bdi": 1,
    "bunker": 1,
    "coking_coal": 1,
    "cyclone": 1,
    "geo_disruption": 1,
    "malacca": 1,
    "port_activity": 1,
    "rainfall": 1,
    "manufacturing_pmi": 35,  # monthly
    "steel_production": 35,  # monthly
    "seasonality": 1,
}

SOURCE_RUNNERS = {
    "bdi": bdi.run,
    "bunker": bunker.run,
    "coking_coal": coking_coal.run,
    "cyclone": cyclone.run,
    "geo_disruption": geo_disruption.run,
    "malacca": malacca.run,
    "manufacturing_pmi": manufacturing_pmi.run,
    "port_activity": port_activity.run,
    "rainfall": rainfall.run,
    "seasonality": seasonality.run,
    "steel_production": steel_production.run,
}


def _upsert_raw(db: Session, result: ScraperResult, today: date) -> None:
    """
    Write validated scraper output into the feature_store row for today.
    Only touches columns owned by this source — never overwrites other sources.
    """
    row_obj = db.query(FeatureStoreRow).filter(FeatureStoreRow.date == today).first()
    if row_obj is None:
        row_obj = FeatureStoreRow(date=today)
        db.add(row_obj)

    data = result.row.model_dump()

    if result.source == "bdi":
        for idx in ("bdi", "bci", "bpi", "bsi", "bhsi"):
            if data.get(idx) is not None:
                setattr(row_obj, idx, data[idx])
        row_obj.is_stale_bdi = False

    elif result.source == "bunker":
        row_obj.vlsfo_price_usd = data["vlsfo_price_usd"]
        if data.get("mgo_price_usd") is not None:
            row_obj.mgo_price_usd = data["mgo_price_usd"]
        row_obj.is_stale_bunker = False

    elif result.source == "coking_coal":
        row_obj.coking_coal_price_usd = data["coking_coal_price_usd"]
        row_obj.is_stale_coking_coal = False

    elif result.source == "steel_production":
        row_obj.steel_production_mt = data["steel_production_mt"]
        row_obj.is_stale_steel_production = False

    elif result.source == "manufacturing_pmi":
        row_obj.manufacturing_pmi = data["manufacturing_pmi"]
        row_obj.is_stale_manufacturing_pmi = False

    elif result.source == "cyclone":
        row_obj.cyclone_india_flag = data["cyclone_india_flag"]
        row_obj.cyclone_india_days = data["cyclone_india_days"]
        row_obj.cyclone_australia_flag = data["cyclone_australia_flag"]
        row_obj.cyclone_australia_days = data["cyclone_australia_days"]
        row_obj.is_stale_cyclone = False

    elif result.source == "rainfall":
        row_obj.rainfall_paradip_mm = data["rainfall_paradip_mm"]
        row_obj.rainfall_vizag_mm = data["rainfall_vizag_mm"]
        row_obj.rainfall_haldia_mm = data["rainfall_haldia_mm"]
        row_obj.rainfall_hay_point_mm = data["rainfall_hay_point_mm"]
        row_obj.rainfall_indonesia_mm = data["rainfall_indonesia_mm"]
        row_obj.is_stale_rainfall = False

    elif result.source == "geo_disruption":
        row_obj.geo_flag = data["geo_flag"]
        row_obj.geo_severity = data["geo_severity"]
        row_obj.geo_days_active = data["geo_days_active"]
        row_obj.is_stale_geo_disruption = False

    elif result.source == "malacca":
        row_obj.malacca_dry_bulk_calls = data["malacca_dry_bulk_calls"]
        row_obj.malacca_dry_bulk_capacity = data["malacca_dry_bulk_capacity"]
        row_obj.is_stale_malacca = False

    elif result.source == "port_activity":
        row_obj.total_port_calls = data["total_port_calls"]
        row_obj.total_port_volume = data["total_port_volume"]
        row_obj.is_stale_port_activity = False

    elif result.source == "seasonality":
        row_obj.month = data["month"]
        row_obj.is_monsoon_season = data["is_monsoon_season"]

    db.commit()


def _forward_fill(db: Session, source: str, today: date) -> bool:
    """
    Copy the most recent non-stale value for this source into today's row.
    Returns True if a value was found to fill from, False if no history exists.
    """
    from sqlalchemy import desc, text

    stale_col = f"is_stale_{source}"

    row_today = db.query(FeatureStoreRow).filter(FeatureStoreRow.date == today).first()
    if row_today is None:
        row_today = FeatureStoreRow(date=today)
        db.add(row_today)

    # find most recent row where this source was NOT stale
    prev = (
        db.query(FeatureStoreRow)
        .filter(FeatureStoreRow.date < today)
        .order_by(desc(FeatureStoreRow.date))
        .all()
    )

    source_cols = {
        "bdi": ["bdi", "bci", "bpi", "bsi"],
        "bunker": ["vlsfo_price_usd", "mgo_price_usd"],
        "coking_coal": ["coking_coal_price_usd"],
        "steel_production": ["steel_production_mt"],
        "manufacturing_pmi": ["manufacturing_pmi"],
        "cyclone": [
            "cyclone_india_flag",
            "cyclone_india_days",
            "cyclone_australia_flag",
            "cyclone_australia_days",
        ],
        "rainfall": [
            "rainfall_paradip_mm",
            "rainfall_vizag_mm",
            "rainfall_haldia_mm",
            "rainfall_hay_point_mm",
            "rainfall_indonesia_mm",
        ],
        "geo_disruption": ["geo_flag", "geo_severity", "geo_days_active"],
        "malacca": ["malacca_dry_bulk_calls", "malacca_dry_bulk_capacity"],
        "port_activity": ["total_port_calls", "total_port_volume"],
        "seasonality": ["month", "is_monsoon_season"],
    }

    cols = source_cols.get(source, [])
    for p in prev:
        if all(getattr(p, c) is not None for c in cols):
            for c in cols:
                setattr(row_today, c, getattr(p, c))
            setattr(row_today, stale_col, True)
            db.commit()
            log.warning("forward-filled %s from %s for %s", source, p.date, today)
            return True

    return False


def run_source(source: str) -> ScraperResult:
    """Run a single scraper, validate, and write to feature store."""
    runner = SOURCE_RUNNERS.get(source)
    if not runner:
        return ScraperResult.failure(source, f"Unknown source: {source}")

    result = runner()
    today = date.today()

    db = SessionLocal()
    try:
        if result.ok:
            _upsert_raw(db, result, today)
            log.info("ingest OK: %s", source)
        else:
            log.error(
                "ingest FAILED: %s — %s (quarantined). Attempting forward-fill.",
                source,
                result.error,
            )
            filled = _forward_fill(db, source, today)
            if not filled:
                log.error(
                    "No historical data to forward-fill for %s — feature will be NULL",
                    source,
                )
    finally:
        db.close()

    return result


def run_all() -> dict[str, ScraperResult]:
    results = {}
    for source in SOURCE_RUNNERS:
        results[source] = run_source(source)
    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    results = run_all()
    print("\n=== Ingest summary ===")
    for source, r in results.items():
        status = "OK" if r.ok else f"FAILED — {r.error}"
        quarantine = (
            f"  ({r.rows_quarantined} quarantined)" if r.rows_quarantined else ""
        )
        print(f"  {source:<22} {status}{quarantine}")
