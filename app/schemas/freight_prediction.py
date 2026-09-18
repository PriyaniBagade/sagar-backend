from pydantic import BaseModel
from typing import Optional


# ── Shared forecast day item ──────────────────────────────────────────────────
class ForecastDay(BaseModel):
    date: str
    predicted_value: float
    low: float
    high: float


# ── API 1 — GET /api/v1/forecast/all ─────────────────────────────────────────
class IndexForecast(BaseModel):
    current_value: Optional[float]
    forecast: list[ForecastDay]
    confidence_pct: int


class AllForecastsResponse(BaseModel):
    forecast_horizon_days: int
    indices: dict[str, IndexForecast]


# ── API 2 — GET /api/v1/forecast/{index} ─────────────────────────────────────
class SingleForecastResponse(BaseModel):
    index: str
    forecast_horizon_days: int
    current_value: Optional[float]
    forecast: list[ForecastDay]
    confidence_pct: int


# ── API 3 — GET /api/v1/forecast/{index}/history ─────────────────────────────
class HistoryDay(BaseModel):
    date: str
    predicted_value: float
    actual_value: Optional[float]


class ForecastHistoryResponse(BaseModel):
    index: str
    lookback_days: int
    history: list[HistoryDay]
    mean_absolute_error_pct: Optional[float]


# ── API 4 — POST /api/v1/forecast/predict ────────────────────────────────────
class PredictRequest(BaseModel):
    origin_port: str
    destination_port: str
    cargo_qty_mt: float
    cargo_type: str
    vessel_type: str  # UUID of VesselClass record
    forecast_horizon_days: int = 7


class ConfidenceRange(BaseModel):
    low: float
    high: float


class PredictResponse(BaseModel):
    feasible: bool
    infeasibility_reason: Optional[str]
    predicted_rate_per_mt: Optional[float]
    confidence_range: Optional[ConfidenceRange]
    confidence_pct: Optional[int]
    forecast_date: Optional[str]
    based_on_index: Optional[str]


# ── Legacy ingest response (internal) ────────────────────────────────────────
class IngestResponse(BaseModel):
    source: str
    status: str
    rows_ingested: int
    rows_quarantined: int
    error: Optional[str] = None
