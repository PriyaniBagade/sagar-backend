from pydantic import BaseModel, field_validator
from uuid import UUID


class CostSummaryRequest(BaseModel):
    vessel_class_id: str  # UUID of the vessel class
    load_port_id: str  # UUID of the loading port
    discharge_port_id: str  # UUID of the discharge port
    quantity_mt: float

    @field_validator("vessel_class_id", "load_port_id", "discharge_port_id")
    @classmethod
    def must_be_valid_uuid(cls, v: str) -> str:
        try:
            UUID(v)
        except ValueError:
            raise ValueError(f"'{v}' is not a valid UUID")
        return v


class VoyageDays(BaseModel):
    sailing_days: float
    load_days: float
    discharge_days: float
    canal_extra_days: float
    total: float


class CostBreakdown(BaseModel):
    num_voyages: int
    vessel_capacity: float
    voyage_days: VoyageDays
    market_tce_per_day: float
    freight_cost: float
    load_port_charges: float
    discharge_port_charges: float
    port_charges: float
    insurance: float
    cost_per_voyage: float
    total_landed_cost: float
    landed_cost_per_mt: float
    bunker_cost: float = 0.0
    canal_toll: float = 0.0
    commission: float = 0.0
    opex_total: float = 0.0
    net_result: float = 0.0
    tce_per_day: float = 0.0


class CostHero(BaseModel):
    landed_cost_per_mt: float
    total_landed_cost: float
    cost_per_voyage: float
    num_voyages: int
    tag: str  # "Approx. — predicted"
    why: str  # human-readable explanation


class CostSummaryResponse(BaseModel):
    hero: CostHero
    breakdown: CostBreakdown
