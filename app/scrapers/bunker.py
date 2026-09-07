"""
Bunker fuel scraper adapter — extracts Global Average VLSFO from handybulk.com/ship-bunker
and validates against BunkerRow.
"""

import re
import datetime
import requests
import pandas as pd
from io import StringIO
from bs4 import BeautifulSoup
from pydantic import ValidationError

from app.scrapers.base import ScraperResult
from app.schemas.sources import BunkerRow

URL = "https://www.handybulk.com/ship-bunker/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
DATE_RE = re.compile(r"(\d{1,2}-[A-Za-z]+-\d{4}) Daily Updated Ship Bunker Prices")


def _to_number(value):
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("$", "")
    if s in ("", "-", "—", "N/A", "n/a", "nan"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def run() -> ScraperResult:
    try:
        resp = requests.get(URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        html = resp.text

        # date
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(" ")
        dm = DATE_RE.search(text)
        if not dm:
            return ScraperResult.failure("bunker", "Could not find report date on page")
        dt = datetime.datetime.strptime(dm.group(1), "%d-%B-%Y").date()

        # tables
        tables = pd.read_html(StringIO(html))
        vlsfo = None
        mgo = None
        for df in tables:
            cols = [str(c).strip() for c in df.columns]
            if not any("VLSFO" in c for c in cols):
                continue
            vlsfo_col = next((c for c in cols if "VLSFO" in c), None)
            mgo_col = next((c for c in cols if "MGO" in c), None)
            df.columns = cols
            for _, row in df.iterrows():
                port = str(row[cols[0]]).strip()
                if "global" in port.lower() or "average" in port.lower():
                    if vlsfo_col:
                        vlsfo = _to_number(row[vlsfo_col])
                    if mgo_col:
                        mgo = _to_number(row[mgo_col])
                    break
            if vlsfo is not None:
                break

        if vlsfo is None:
            return ScraperResult.failure(
                "bunker", "Global Average VLSFO price not found in tables"
            )

        row = BunkerRow(date=dt, vlsfo_price_usd=vlsfo, mgo_price_usd=mgo)
        return ScraperResult.success("bunker", row)

    except (requests.RequestException, RuntimeError) as e:
        return ScraperResult.failure("bunker", str(e))
    except ValidationError as e:
        return ScraperResult.failure(
            "bunker", f"schema validation failed: {e}", rows_quarantined=1
        )
