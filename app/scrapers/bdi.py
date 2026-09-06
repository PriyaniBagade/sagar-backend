"""
BDI scraper adapter — wraps the core scraping logic and validates output
against BDIRow before returning. Any structural mismatch is caught here,
not silently passed downstream.
"""
import re
import datetime
import requests
from bs4 import BeautifulSoup
from pydantic import ValidationError

from app.scrapers.base import ScraperResult
from app.schemas.sources import BDIRow

BASE_URL = "https://www.handybulk.com/baltic-dry-index/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
DATE_RE = re.compile(r"\b(\d{1,2}-[A-Za-z]+-\d{4})\b")
INDEX_DEFS = [
    ("BDI", "Baltic Dry Index", None),
    ("BCI", "Baltic Capesize Index", "capesize"),
    ("BPI", "Baltic Panamax Index", "panamax"),
    ("BSI", "Baltic Supramax Index", "supramax"),
    ("BHSI", "Baltic Handysize Index", "handysize"),
]


def _fetch_text(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text("\n")


def _split_into_day_blocks(text: str):
    """Split page text into (date_str, chunk) pairs — exact logic from original scraper."""
    matches = list(DATE_RE.finditer(text))
    blocks = []
    for i, m in enumerate(matches):
        date_str = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if "Baltic" in chunk:
            blocks.append((date_str, chunk))
    return blocks


def _parse_block(date_str: str, chunk: str) -> dict:
    dt = datetime.datetime.strptime(date_str, "%d-%B-%Y").date()
    raw: dict = {"date": dt}

    for code, full_name, rate_noun in INDEX_DEFS:
        idx_pat = re.compile(
            rf"{re.escape(full_name)} \({code}\) (increased|decreased) by "
            rf"([\d,]+) points to (?:reach )?([\d,]+) points"
        )
        m = idx_pat.search(chunk)
        if m:
            direction, change, value = m.groups()
            raw[code.lower()] = int(value.replace(",", ""))
            raw[f"{code.lower()}_change"] = int(change.replace(",", "")) * (
                1 if direction == "increased" else -1
            )
        if rate_noun:
            rate_pat = re.compile(
                rf"average daily (?:earnings|income) for {rate_noun} bulk carriers "
                rf"(increased|decreased) by \$([\d,]+) to \$([\d,]+)"
            )
            rm = rate_pat.search(chunk)
            if rm:
                rd, rc, rv = rm.groups()
                raw[f"{code.lower()}_avg_earnings"] = int(rv.replace(",", ""))

    return raw


def run() -> ScraperResult:
    try:
        text = _fetch_text(BASE_URL)
        blocks = _split_into_day_blocks(text)
        if not blocks:
            return ScraperResult.failure("bdi", "No dated BDI blocks with Baltic content found on page")

        # blocks are in page order (most recent first) — take the first valid one
        raw = _parse_block(*blocks[0])

        # must have at least BDI value to be useful
        if raw.get("bdi") is None:
            return ScraperResult.failure("bdi", f"BDI value not parsed from block dated {raw['date']}")

        row = BDIRow(**raw)
        return ScraperResult.success("bdi", row)
    except (requests.RequestException, RuntimeError) as e:
        return ScraperResult.failure("bdi", str(e))
    except ValidationError as e:
        return ScraperResult.failure("bdi", f"schema validation failed: {e}", rows_quarantined=1)
