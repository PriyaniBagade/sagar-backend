from pydantic import BaseModel
from typing import Optional


class DriverItem(BaseModel):
    factor: str
    contribution: float   # points pushed up (+) or down (-) on the index
    direction: str        # "up" | "down"


class ForecastResponse(BaseModel):
    index: str
    target_date: str
    point_forecast: float
    lower_bound: float
    upper_bound: float
    generated_at: str
    model_version: str
    data_freshness: dict[str, str]
    drivers: list[DriverItem]  # sorted by absolute contribution, biggest first


class AllForecastsResponse(BaseModel):
    bdi: ForecastResponse
    bci: ForecastResponse
    bpi: ForecastResponse
    bsi: ForecastResponse


class ForecastHistoryItem(BaseModel):
    date: str
    predicted: float
    actual: Optional[float]
    error: Optional[float]


class IngestResponse(BaseModel):
    source: str
    status: str
    rows_ingested: int
    rows_quarantined: int
    error: Optional[str] = None
