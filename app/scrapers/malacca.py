"""
Malacca Strait traffic scraper adapter — IMF PortWatch ArcGIS FeatureServer.
Extracts dry bulk vessel calls and capacity for the latest available date.
"""

import datetime
import requests
from pydantic import ValidationError

from app.scrapers.base import ScraperResult
from app.schemas.sources import MalaccaRow

URL = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/"
    "ArcGIS/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query"
)
HEADERS = {"User-Agent": "Mozilla/5.0"}


def run() -> ScraperResult:
    try:
        params = {
            "where": "portname = 'Malacca Strait'",
            "outFields": "date,portname,n_dry_bulk,capacity_dry_bulk,n_total,capacity",
            "orderByFields": "date DESC",
            "resultRecordCount": 1,
            "returnGeometry": "false",
            "f": "json",
        }
        resp = requests.get(URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
        if not features:
            return ScraperResult.failure(
                "malacca", "No features returned from PortWatch API"
            )

        a = features[0]["attributes"]

        # prefer dry_bulk specific fields; fall back to total if absent
        calls = a.get("n_dry_bulk") or a.get("n_total") or 0
        capacity = a.get("capacity_dry_bulk") or a.get("capacity") or 0.0

        raw_date = a["date"]
        if isinstance(raw_date, (int, float)):
            from datetime import timezone

            dt = datetime.datetime.fromtimestamp(
                raw_date / 1000, tz=timezone.utc
            ).date()
        else:
            dt = datetime.datetime.fromisoformat(
                str(raw_date).replace("Z", "+00:00")
            ).date()

        row = MalaccaRow(
            date=dt,
            malacca_dry_bulk_calls=int(calls),
            malacca_dry_bulk_capacity=float(capacity),
        )
        return ScraperResult.success("malacca", row)

    except requests.RequestException as e:
        return ScraperResult.failure("malacca", str(e))
    except ValidationError as e:
        return ScraperResult.failure(
            "malacca", f"schema validation failed: {e}", rows_quarantined=1
        )
