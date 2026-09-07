"""
Rainfall scraper adapter — Open-Meteo API.
Fetches today's precipitation for 5 key port/mining locations.
Column names match the model's 29-feature contract exactly.
"""

import datetime
import requests
from pydantic import ValidationError

from app.scrapers.base import ScraperResult
from app.schemas.sources import RainfallRow

URL = "https://api.open-meteo.com/v1/forecast"

# (lat, lon) matched to the model feature names
LOCATIONS = {
    "rainfall_paradip_mm": (20.2630, 86.6747),  # Paradip port, Odisha
    "rainfall_vizag_mm": (17.6868, 83.2185),  # Visakhapatnam port
    "rainfall_haldia_mm": (22.0667, 88.0693),  # Haldia dock, West Bengal
    "rainfall_hay_point_mm": (-21.2844, 149.3003),  # Hay Point, Queensland
    "rainfall_indonesia_mm": (-0.7893, 113.9213),  # Kalimantan (coal mining)
}


def _get_rain(lat: float, lon: float) -> float:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum",
        "forecast_days": 1,
        "timezone": "GMT",
    }
    resp = requests.get(URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    val = data["daily"]["precipitation_sum"][0]
    return float(val) if val is not None else 0.0


def run() -> ScraperResult:
    try:
        today = datetime.date.today()
        values = {}
        for field_name, (lat, lon) in LOCATIONS.items():
            values[field_name] = _get_rain(lat, lon)

        row = RainfallRow(date=today, **values)
        return ScraperResult.success("rainfall", row)

    except requests.RequestException as e:
        return ScraperResult.failure("rainfall", str(e))
    except ValidationError as e:
        return ScraperResult.failure(
            "rainfall", f"schema validation failed: {e}", rows_quarantined=1
        )
