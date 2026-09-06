"""
Cyclone scraper adapter — GDACS API.
Maps active tropical cyclones to the India/Australia region flags the model needs.
"""
import datetime
import requests
from pydantic import ValidationError

from app.scrapers.base import ScraperResult
from app.schemas.sources import CycloneRow

URL = "https://www.gdacs.org/gdacsapi/api/Events/geteventlist/EVENTS4APP?eventlist=TC"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# Bounding boxes — rough but sufficient for flag purposes
# India region: Bay of Bengal + Arabian Sea shipping zone
INDIA_LAT = (5, 25)
INDIA_LON = (60, 100)
# Australia region: Coral Sea + North-West Shelf
AUSTRALIA_LAT = (-30, -10)
AUSTRALIA_LON = (110, 165)


def _in_box(lat, lon, lat_range, lon_range) -> bool:
    return lat_range[0] <= lat <= lat_range[1] and lon_range[0] <= lon <= lon_range[1]


def run() -> ScraperResult:
    try:
        resp = requests.get(URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        cyclones = [
            e for e in data.get("features", [])
            if e["properties"].get("eventtype") == "TC"
        ]

        india_active = 0
        australia_active = 0

        for event in cyclones:
            lon, lat = event["geometry"]["coordinates"]
            if _in_box(lat, lon, INDIA_LAT, INDIA_LON):
                india_active += 1
            if _in_box(lat, lon, AUSTRALIA_LAT, AUSTRALIA_LON):
                australia_active += 1

        today = datetime.date.today()
        row = CycloneRow(
            date=today,
            cyclone_india_flag=1 if india_active > 0 else 0,
            cyclone_india_days=india_active,       # proxy: count of concurrent events
            cyclone_australia_flag=1 if australia_active > 0 else 0,
            cyclone_australia_days=australia_active,
        )
        return ScraperResult.success("cyclone", row)

    except requests.RequestException as e:
        return ScraperResult.failure("cyclone", str(e))
    except ValidationError as e:
        return ScraperResult.failure("cyclone", f"schema validation failed: {e}", rows_quarantined=1)
