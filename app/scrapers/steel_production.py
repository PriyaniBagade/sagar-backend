"""
Steel production scraper adapter — steel.gov.in monthly PDF.
Returns the latest cumulative finished steel production (Mt) for India.
"""
import re
import calendar
import datetime
from io import BytesIO
from urllib.parse import urljoin

import requests
import urllib3
import pdfplumber
from bs4 import BeautifulSoup
from pydantic import ValidationError

from app.scrapers.base import ScraperResult
from app.schemas.sources import SteelProductionRow

LISTING_URL = "https://steel.gov.in/monthly-summary"
HEADERS = {"User-Agent": "Mozilla/5.0"}
MONTHS = [m.lower() for m in calendar.month_name if m]


def _fetch(url, **kwargs):
    try:
        return requests.get(url, headers=HEADERS, timeout=30, verify=True, **kwargs)
    except requests.exceptions.SSLError:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return requests.get(url, headers=HEADERS, timeout=30, verify=False, **kwargs)


def run() -> ScraperResult:
    try:
        resp = _fetch(LISTING_URL)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        candidates = []
        month_re = re.compile(
            r"(" + "|".join(MONTHS) + r")\D{0,10}?(\d{4})", re.IGNORECASE
        )
        for link in soup.find_all("a", href=True):
            if not link["href"].lower().endswith(".pdf"):
                continue
            text = link.get_text(" ", strip=True)
            m = month_re.search(text)
            if not m:
                continue
            month_idx = MONTHS.index(m.group(1).lower()) + 1
            year = int(m.group(2))
            full_url = urljoin(LISTING_URL, link["href"])
            candidates.append((year, month_idx, full_url))

        if not candidates:
            return ScraperResult.failure("steel_production", "No dated PDF found on steel.gov.in")

        candidates.sort(reverse=True)
        year, month_idx, pdf_url = candidates[0]

        pdf_resp = _fetch(pdf_url)
        pdf_resp.raise_for_status()

        with pdfplumber.open(BytesIO(pdf_resp.content)) as pdf:
            full_text = "".join(page.extract_text() or "" for page in pdf.pages)

        summary_pat = re.compile(
            r"production of Finished Steel during\s+[A-Za-z\s\-]+\d{4}"
            r"\s+is\s+(\d+\.\d+)\s+million tonnes",
            re.IGNORECASE,
        )
        m = summary_pat.search(full_text)
        if m:
            value = float(m.group(1))
        else:
            # fallback: Annexure-I table last number in a finished-steel row
            with pdfplumber.open(BytesIO(pdf_resp.content)) as pdf:
                value = None
                for page in pdf.pages:
                    for table in (page.extract_tables() or []):
                        for row in table:
                            row_text = " ".join(cell or "" for cell in row)
                            if "finished steel production" in row_text.lower():
                                nums = re.findall(r"\d+\.\d+", row_text)
                                if nums:
                                    value = float(nums[-1])
                                    break
                        if value is not None:
                            break
                    if value is not None:
                        break
            if value is None:
                return ScraperResult.failure("steel_production", "Steel production value not found in PDF")

        dt = datetime.date(year, month_idx, 1)
        row = SteelProductionRow(date=dt, steel_production_mt=value)
        return ScraperResult.success("steel_production", row)

    except (requests.RequestException, RuntimeError) as e:
        return ScraperResult.failure("steel_production", str(e))
    except ValidationError as e:
        return ScraperResult.failure("steel_production", f"schema validation failed: {e}", rows_quarantined=1)
