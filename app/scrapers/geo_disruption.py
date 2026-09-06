"""
Geo disruption scraper adapter — IMF PortWatch chokepoint AIS traffic.
Computes a normalised disruption score (0-1) from traffic deviation.
Covers Bab el-Mandeb, Suez Canal, Panama Canal.
"""
import datetime
import statistics
import time
import requests
from pydantic import ValidationError

from app.scrapers.base import ScraperResult
from app.schemas.sources import GeoDisruptionRow

BASE_URL = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services"
    "/Daily_Chokepoints_Data/FeatureServer/0/query"
)
HEADERS = {"User-Agent": "Mozilla/5.0"}

CHOKEPOINTS = ["Bab el-Mandeb Strait", "Suez Canal", "Panama Canal"]
CURRENT_DAYS = 7
BASELINE_DAYS = 90
BASELINE_LOOKBACK = 97


def _fetch(params, retries=3, backoff=5):
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(backoff)
    raise last_err


def _series(portname: str, days: int = 120):
    from datetime import timezone, timedelta
    since = (datetime.datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "where": f"portname='{portname}' AND date >= DATE '{since}'",
        "outFields": "date,n_total",
        "orderByFields": "date ASC",
        "f": "json",
    }
    data = _fetch(params)
    series = []
    for f in data.get("features", []):
        attrs = f["attributes"]
        raw = attrs["date"]
        from datetime import timezone
        if isinstance(raw, (int, float)):
            d = datetime.datetime.fromtimestamp(raw / 1000, tz=timezone.utc).date()
        else:
            d = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
        series.append((d, attrs.get("n_total")))
    series.sort(key=lambda t: t[0])
    return series


def _deviation(series) -> float | None:
    values = [v for _, v in series if v is not None]
    dates = [d for d, v in series if v is not None]
    if len(values) < 10:
        return None
    today = dates[-1]
    from datetime import timedelta
    current = [v for d, v in zip(dates, values) if (today - d).days < CURRENT_DAYS]
    bl_start = today - timedelta(days=BASELINE_LOOKBACK)
    bl_end = bl_start - timedelta(days=BASELINE_DAYS)
    baseline = [v for d, v in zip(dates, values) if bl_end <= d < bl_start]
    if not current or not baseline:
        return None
    curr_avg = statistics.mean(current)
    base_avg = statistics.mean(baseline)
    if base_avg == 0:
        return None
    return curr_avg / base_avg - 1  # negative = traffic dropped = disruption


def run() -> ScraperResult:
    try:
        deviations = []
        for cp in CHOKEPOINTS:
            try:
                s = _series(cp)
                d = _deviation(s)
                if d is not None:
                    deviations.append(d)
            except Exception:
                continue

        today = datetime.date.today()

        if not deviations:
            # not enough data — safe default: no disruption
            row = GeoDisruptionRow(date=today, geo_flag=0, geo_severity=0.0, geo_days_active=0)
            return ScraperResult.success("geo_disruption", row)

        # worst deviation across chokepoints (most negative = worst disruption)
        worst = min(deviations)
        # convert to 0-1 severity: -50% drop -> 1.0 severity
        severity = min(1.0, max(0.0, -worst / 0.5))
        geo_flag = 1 if severity > 0.1 else 0
        # days_active approximated as number of chokepoints with >10% drop
        days_active = sum(1 for d in deviations if d < -0.1)

        row = GeoDisruptionRow(
            date=today,
            geo_flag=geo_flag,
            geo_severity=round(severity, 4),
            geo_days_active=days_active,
        )
        return ScraperResult.success("geo_disruption", row)

    except Exception as e:
        return ScraperResult.failure("geo_disruption", str(e))
