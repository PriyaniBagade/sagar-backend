"""
Port activity scraper adapter — IMF PortWatch Daily_Ports_Data.
Sums dry bulk calls and volume across the 18 coal-relevant ports.
"""
import datetime
import requests
from pydantic import ValidationError

from app.scrapers.base import ScraperResult
from app.schemas.sources import PortActivityRow

QUERY_URL = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services"
    "/Daily_Ports_Data/FeatureServer/0/query"
)
HEADERS = {"User-Agent": "Mozilla/5.0"}

PORTS = [
    "Paradip", "Visakhapatnam", "Haldia", "Dhamra", "Gopalpur",
    "Port Hedland", "Dampier", "Newcastle", "Hay Point", "Abbot Point",
    "New Orleans", "Baton Rouge", "Nacala", "Beira",
    "Vostochny", "Nakhodka", "Samarinda", "Balikpapan",
]


def _latest_date() -> str:
    params = {
        "where": "1=1",
        "outFields": "date",
        "orderByFields": "date DESC",
        "resultRecordCount": 1,
        "returnGeometry": "false",
        "f": "json",
    }
    resp = requests.get(QUERY_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()["features"][0]["attributes"]["date"]


def run() -> ScraperResult:
    try:
        latest = _latest_date()
        port_list = ",".join(f"'{p}'" for p in PORTS)
        params = {
            "where": f"date = '{latest}' AND portname IN ({port_list})",
            "outFields": "portname,portcalls_dry_bulk,import_dry_bulk,export_dry_bulk",
            "returnGeometry": "false",
            "f": "json",
        }
        resp = requests.get(QUERY_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
        if not features:
            return ScraperResult.failure("port_activity", "No port features returned from PortWatch API")

        total_calls = 0
        total_volume = 0.0
        for feat in features:
            a = feat["attributes"]
            total_calls += int(a.get("portcalls_dry_bulk") or 0)
            total_volume += float((a.get("import_dry_bulk") or 0) + (a.get("export_dry_bulk") or 0))

        # parse date from the raw latest value
        if isinstance(latest, (int, float)):
            from datetime import timezone
            dt = datetime.datetime.fromtimestamp(latest / 1000, tz=timezone.utc).date()
        else:
            try:
                dt = datetime.datetime.fromisoformat(str(latest).replace("Z", "+00:00")).date()
            except ValueError:
                dt = datetime.date.today()

        row = PortActivityRow(date=dt, total_port_calls=total_calls, total_port_volume=total_volume)
        return ScraperResult.success("port_activity", row)

    except requests.RequestException as e:
        return ScraperResult.failure("port_activity", str(e))
    except ValidationError as e:
        return ScraperResult.failure("port_activity", f"schema validation failed: {e}", rows_quarantined=1)
