"""
Pydantic schemas — one per scraper source.
These are the canonical contracts between scrapers and the feature store.
If a scraper's output doesn't match, it gets quarantined here, not silently used.
"""
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class BDIRow(BaseModel):
    """Output of scraper.py — handybulk.com/baltic-dry-index"""
    date: date
    bdi: Optional[float] = Field(None, gt=0)
    bdi_change: Optional[float] = None
    bci: Optional[float] = Field(None, gt=0)
    bci_change: Optional[float] = None
    bci_avg_earnings: Optional[float] = Field(None, gt=0)
    bpi: Optional[float] = Field(None, gt=0)
    bpi_change: Optional[float] = None
    bpi_avg_earnings: Optional[float] = Field(None, gt=0)
    bsi: Optional[float] = Field(None, gt=0)
    bsi_change: Optional[float] = None
    bsi_avg_earnings: Optional[float] = Field(None, gt=0)
    bhsi: Optional[float] = Field(None, gt=0)
    bhsi_change: Optional[float] = None
    bhsi_avg_earnings: Optional[float] = Field(None, gt=0)


class BunkerRow(BaseModel):
    """Output of bunker_scraper.py — handybulk.com/ship-bunker
    Only the global average VLSFO is required; port-level fields are optional.
    """
    date: date
    vlsfo_price_usd: float = Field(..., gt=0, lt=5000)  # global avg VLSFO $/mt
    mgo_price_usd: Optional[float] = Field(None, gt=0, lt=10000)


class CokingCoalRow(BaseModel):
    """Output of coking_coal_daily.py or coking_coal_scraper.py"""
    date: date
    coking_coal_price_usd: float = Field(..., gt=50, lt=1500)  # $/t, plausible range


class SteelProductionRow(BaseModel):
    """Output of steel_production_scraper.py — steel.gov.in cumulative Mt"""
    date: date                              # first day of report month
    steel_production_mt: float = Field(..., gt=0, lt=200)  # cumulative FY Mt


class ManufacturingPMIRow(BaseModel):
    """Output of manufacturing_pmi_scraper.py — J.P.Morgan Global Mfg PMI"""
    date: date                              # first day of report month
    manufacturing_pmi: float = Field(..., gt=30, lt=70)


class CycloneRow(BaseModel):
    """Output of cyclone.py — GDACS API"""
    date: date
    cyclone_india_flag: int = Field(..., ge=0, le=1)
    cyclone_india_days: int = Field(..., ge=0)
    cyclone_australia_flag: int = Field(..., ge=0, le=1)
    cyclone_australia_days: int = Field(..., ge=0)


class RainfallRow(BaseModel):
    """Output of rainfall.py — Open-Meteo API"""
    date: date
    rainfall_paradip_mm: float = Field(..., ge=0)
    rainfall_vizag_mm: float = Field(..., ge=0)
    rainfall_haldia_mm: float = Field(..., ge=0)
    rainfall_hay_point_mm: float = Field(..., ge=0)
    rainfall_indonesia_mm: float = Field(..., ge=0)


class GeoDisruptionRow(BaseModel):
    """Output of global_disruption.py — chokepoint AIS traffic scores"""
    date: date
    geo_flag: int = Field(..., ge=0, le=1)
    geo_severity: float = Field(..., ge=0, le=1)   # normalised 0-1
    geo_days_active: int = Field(..., ge=0)

    @field_validator("geo_severity")
    @classmethod
    def severity_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"geo_severity must be 0-1, got {v}")
        return v


class MalaccaRow(BaseModel):
    """Output of malacca_traffic_scraper.py — IMF PortWatch ArcGIS"""
    date: date
    malacca_dry_bulk_calls: int = Field(..., ge=0)
    malacca_dry_bulk_capacity: float = Field(..., ge=0)  # DWT


class PortActivityRow(BaseModel):
    """Output of port_activity_scraper.py — IMF PortWatch Daily_Ports_Data"""
    date: date
    total_port_calls: int = Field(..., ge=0)
    total_port_volume: float = Field(..., ge=0)  # sum of import+export dry bulk


class SeasonalityRow(BaseModel):
    """Derived — no network call"""
    date: date
    month: int = Field(..., ge=1, le=12)
    is_monsoon_season: int = Field(..., ge=0, le=1)
