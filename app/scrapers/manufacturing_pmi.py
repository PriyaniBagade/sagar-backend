"""
Manufacturing PMI scraper adapter — J.P.Morgan Global Manufacturing PMI
via MTA's monthly writeup (plain HTML, no JS required).
"""

import re
import datetime
import requests
from pydantic import ValidationError

from app.scrapers.base import ScraperResult
from app.schemas.sources import ManufacturingPMIRow

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
BASE_URL = "https://www.mta.org.uk/resources/purchasing-managers-index-for-manufacturing-{month}-{year}/"
MONTH_NAMES = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]


def _candidates(months_back=4):
    today = datetime.date.today()
    year, month = today.year, today.month
    for _ in range(months_back):
        yield MONTH_NAMES[month - 1], year, month
        month -= 1
        if month == 0:
            month = 12
            year -= 1


def run() -> ScraperResult:
    try:
        article_url = None
        page_text = None
        report_month = None
        report_year = None

        for month_name, year, month_idx in _candidates():
            url = BASE_URL.format(month=month_name, year=year)
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                article_url = url
                page_text = resp.text
                report_month = month_idx
                report_year = year
                break

        if not article_url:
            return ScraperResult.failure(
                "manufacturing_pmi", "No recent PMI article found on MTA site"
            )

        # restrict to global section to avoid UK/euro figures
        section_m = re.search(
            r"Global Manufacturing PMI.*?(?=UK manufacturing sector)",
            page_text,
            re.IGNORECASE | re.DOTALL,
        )
        section = section_m.group(0) if section_m else page_text

        val_m = re.search(
            r"PMI\s+(?:rose|fell|edged up|edged down|remained unchanged)\s+(?:to|at)\s+(\d+\.\d+)",
            section,
            re.IGNORECASE,
        )
        if not val_m:
            return ScraperResult.failure(
                "manufacturing_pmi", "PMI value pattern not found in article"
            )

        pmi = float(val_m.group(1))
        dt = datetime.date(report_year, report_month, 1)
        row = ManufacturingPMIRow(date=dt, manufacturing_pmi=pmi)
        return ScraperResult.success("manufacturing_pmi", row)

    except requests.RequestException as e:
        return ScraperResult.failure("manufacturing_pmi", str(e))
    except ValidationError as e:
        return ScraperResult.failure(
            "manufacturing_pmi", f"schema validation failed: {e}", rows_quarantined=1
        )
