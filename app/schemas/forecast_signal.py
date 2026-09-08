from pydantic import BaseModel, field_validator
from uuid import UUID


class SignalRequest(BaseModel):
    vessel_class: str
    loading_port_id: str
    discharge_port_id: str
    quantity_mt: float

    @field_validator("loading_port_id", "discharge_port_id")
    @classmethod
    def must_be_valid_uuid(cls, v: str) -> str:
        try:
            UUID(v)
        except ValueError:
            raise ValueError(f"'{v}' is not a valid UUID")
        return v


class TopFactor(BaseModel):
    factor: str
    impact: int
    summary: str


class SignalResponse(BaseModel):
    verdict: str  # "BOOK_NOW" | "HOLD" | "WAIT"
    confidence: int  # 0–95
    reason: str  # plain-English explanation from top 2 factors
    score: int  # raw total score
    expected_bdi_change_pct: float  # ((predicted - current) / current) * 100
    top_factors: list[TopFactor]  # top contributing factors sorted by abs impact
    strategy_cards: list  # reserved for future use
