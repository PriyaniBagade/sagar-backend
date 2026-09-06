"""
Coking coal scraper adapter.
Primary source: tradingeconomics.com (daily, via coking_coal_daily logic).
Fallback: steel.gov.in PDF (monthly, via coking_coal_scraper logic).
"""
import re
import calendar
import datetime
import requests
import urllib3
from io import BytesIO
from bs4 import BeautifulSoup
from pydantic import ValidationError

from app.scrapers.base import ScraperResult
from app.schemas.sources import CokingCoalRow

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
TE_URL = "https://tradingeconomics.com/commodity/coking-coal"
LISTING_URL = "https://steel.gov.in/monthly-summary"
PLAUSIBLE_RANGE = (80, 700)

MONTHS_IDX = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTH_YEAR_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\.?,?\s*-?\s*(\d{4})", re.IGNORECASE
)
META_RE = re.compile(
    r'name=["\']description["\'][^>]*content=["\']Coking Coal (?:rose to|fell to|traded flat at)?\s*'
    r'([\d,]+\.?\d*)\s*USD/T on ([A-Za-z]+ \d{1,2},? \d{4})',
    re.IGNORECASE,
)


def _fetch(url, **kwargs):
    try:
        return requests.get(url, headers=HEADERS, timeout=30, verify=True, **kwargs)
    except requests.exceptions.SSLError:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return requests.get(url, headers=HEADERS, timeout=30, verify=False, **kwargs)


def _from_trading_economics() -> tuple[float, datetime.date]:
    resp = _fetch(TE_URL)
    resp.raise_for_status()
    m = META_RE.search(resp.text)
    if not m:
        raise RuntimeError("TE meta description pattern not found")
    price = float(m.group(1).replace(",", ""))
    market_date = datetime.datetime.strptime(
        m.group(2).replace(",", ""), "%B %d %Y"
    ).date()
    return price, market_date


def _from_steel_gov() -> tuple[float, datetime.date]:
    resp = _fetch(LISTING_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    candidates = []
    for a in soup.find_all("a", href=True):
        if not a["href"].lower().endswith(".pdf"):
            continue
        row_text = a.get_text(" ", strip=True)
        if a.find_parent("tr"):
            row_text = a.find_parent("tr").get_text(" ", strip=True)
        mm = MONTH_YEAR_RE.search(row_text)
        if not mm:
            continue
        month_idx = MONTHS_IDX.get(mm.group(1).lower())
        if not month_idx:
            continue
        url = a["href"] if a["href"].startswith("http") else requests.compat.urljoin(LISTING_URL, a["href"])
        candidates.append((int(mm.group(2)), month_idx, url))

    if not candidates:
        raise RuntimeError("No dated PDF found on steel.gov.in")
    candidates.sort()
    year, month_idx, pdf_url = candidates[-1]

    import pdfplumber
    pdf_resp = _fetch(pdf_url)
    pdf_resp.raise_for_status()
    with pdfplumber.open(BytesIO(pdf_resp.content)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    # find digit runs near "coking coal" and extract plausible price
    anchors = [m.start() for m in re.finditer(r"coking\s+coal", text, re.IGNORECASE)]
    for mm in re.finditer(r"[\d][\d\s]*[\d]|\d", text):
        digits = re.sub(r"\D", "", mm.group())
        if len(digits) < 18:
            continue
        if not anchors or min(abs(mm.start() - a) for a in anchors) > 5000:
            continue
        if len(digits) % 3 == 0:
            vals = [int(digits[i:i+3]) for i in range(0, len(digits), 3)]
            vals = [v for v in vals if PLAUSIBLE_RANGE[0] <= v <= PLAUSIBLE_RANGE[1]]
            if len(vals) >= 6:
                price = float(vals[-1])
                dt = datetime.date(year, month_idx, 1)
                return price, dt

    raise RuntimeError("Could not extract coking coal price from PDF")


def run() -> ScraperResult:
    try:
        try:
            price, dt = _from_trading_economics()
        except Exception:
            price, dt = _from_steel_gov()

        row = CokingCoalRow(date=dt, coking_coal_price_usd=price)
        return ScraperResult.success("coking_coal", row)
    except (requests.RequestException, RuntimeError) as e:
        return ScraperResult.failure("coking_coal", str(e))
    except ValidationError as e:
        return ScraperResult.failure("coking_coal", f"schema validation failed: {e}", rows_quarantined=1)
