from pydantic import BaseModel, field_validator
from typing import Optional
from uuid import UUID


class VesselOptimizationRequest(BaseModel):
    cargo_type: Optional[str] = None  # free-text, e.g. "coking coal", "iron ore"
    loading_port_id: str
    discharge_port_id: str
    cargo_quantity: float  # metric tons

    @field_validator("loading_port_id", "discharge_port_id")
    @classmethod
    def must_be_valid_uuid(cls, v: str) -> str:
        try:
            UUID(v)
        except ValueError:
            raise ValueError(f"'{v}' is not a valid UUID")
        return v


class RejectedClass(BaseModel):
    vessel_class: str
    rejection_reason: str


class VesselOptimizationResponse(BaseModel):
    recommended_class: str
    voyages_needed: int
    eligible_classes: list[str]
    rejected_classes: list[RejectedClass]
    explanation: str  # human-readable reasoning for the recommendation
