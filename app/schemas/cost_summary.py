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
    voyage_days: VoyageDays
    freight_cost: float
    port_charges: float
    bunker_cost: float
    canal_toll: float
    commission: float
    opex_total: float
    net_result: float
    tce_per_day: float


class CostHero(BaseModel):
    landed_cost_per_mt: float
    tag: str  # "Approx. — predicted"
    why: str  # human-readable explanation


class CostSummaryResponse(BaseModel):
    hero: CostHero
    breakdown: CostBreakdown
