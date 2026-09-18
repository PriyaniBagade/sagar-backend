"""
Market Entry Timing request/response schemas.

Verdict: BOOK (rates rising, book now to lock in) | WAIT (rates falling, flexibility better)
Confidence: 55–95% based on signal strength.
Contract strategy: SPOT (current rate × voyages) vs COA (avg forecasted rate over duration).
"""

from pydantic import BaseModel
from typing import Optional
import uuid


class MarketEntryTimingRequest(BaseModel):
    origin_port: str  # e.g. "Abbot Point (NQXT)"
    destination_port: str  # e.g. "Paradip"
    cargo_quantity_mt: float  # e.g. 210000
    cargo_type: str  # e.g. "Coking Coal"
    vessel_type: str  # e.g. "Panamax"
    contract_duration_months: float  # e.g. 3 (can be 1–24 for various commitments)


class TopFactor(BaseModel):
    factor: str  # e.g. "Freight Forecast", "Geopolitical Disruption"
    impact: float  # positive (BOOK) or negative (WAIT)
    summary: str


class SpotComparison(BaseModel):
    rate_per_mt: float  # Current freight rate
    voyages_estimated: int
    total_cost: float  # rate_per_mt × cargo_qty × voyages


class COAComparison(BaseModel):
    duration_months: float
    rate_per_mt: float  # Average of forecasted rates across duration
    voyages_estimated: int
    total_cost: float  # rate_per_mt × cargo_qty × voyages
    vs_spot_pct: str  # "+15.3%" or "-8.2%"


class ContractStrategy(BaseModel):
    recommendation: str  # "SPOT" or "COA"
    confidence: str  # "LOW", "MEDIUM", "HIGH"
    comparison: dict  # { spot: {...}, coa: {...} }
    reasons: list[str]


class MarketEntryTimingResponse(BaseModel):
    verdict: str  # "BOOK" or "WAIT"
    confidence_pct: int  # 55–95
    reason: str  # Human-friendly summary
    score: float  # Numeric sum of weighted factors (negative = WAIT, positive = BOOK)
    expected_rate_change_pct: float
    top_factors: list[TopFactor]  # Top 3–5 weighted drivers
    contract_strategy: ContractStrategy


class MarketEntryTimingFail(BaseModel):
    """Returned if feasibility fails or data unavailable."""

    feasible: bool = False
    reason: str
