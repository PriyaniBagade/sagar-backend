from pydantic import BaseModel, field_validator
from typing import Optional
from uuid import UUID


class LandedCostRequest(BaseModel):
    vessel_class_id: str
    origin_port_id: str
    destination_port_id: str
    cargo_quantity_mt: float
    cargo_type: str
    cargo_price_per_mt: Optional[float] = None  # if omitted → shipping cost only
    insurance_rate_pct: float = 0.5  # default 0.5%, user-editable

    @field_validator("vessel_class_id", "origin_port_id", "destination_port_id")
    @classmethod
    def must_be_uuid(cls, v: str) -> str:
        try:
            UUID(v)
        except ValueError:
            raise ValueError(f"'{v}' is not a valid UUID")
        return v


class LandedCostFeasibilityFail(BaseModel):
    feasible: bool = False
    reason: str


class LandedCostBreakdown(BaseModel):
    # voyage
    num_voyages: int
    vessel_capacity_mt: float
    voyage_days: float
    sailing_days: float
    load_days: float
    discharge_days: float
    distance_nm: float
    route_type: str

    # cost components (total across all voyages)
    freight_cost_usd: float
    origin_port_charges_usd: float
    destination_port_charges_usd: float
    cargo_value_usd: Optional[float]  # None if no cargo price given
    insurance_usd: Optional[float]  # None if no cargo price given
    insurance_rate_pct: float
    insurance_basis: Optional[str]  # human-readable basis if calculable

    # totals
    total_usd: float
    total_per_mt_usd: float

    # mode label
    mode: str  # "landed_cost" | "shipping_cost"

    # market data used
    index_used: str
    index_points: float
    freight_rate_per_mt_usd: float


class LandedCostResponse(BaseModel):
    feasible: bool = True
    breakdown: LandedCostBreakdown
