"""
Seasonality adapter — derived, no network call.
"""
import datetime
from app.scrapers.base import ScraperResult
from app.schemas.sources import SeasonalityRow


def run() -> ScraperResult:
    today = datetime.date.today()
    row = SeasonalityRow(
        date=today,
        month=today.month,
        is_monsoon_season=1 if today.month in (6, 7, 8, 9) else 0,
    )
    return ScraperResult.success("seasonality", row)
