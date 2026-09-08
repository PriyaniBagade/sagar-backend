from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date
from uuid import UUID

class IdleGapResponse(BaseModel):
    vessel_id: UUID
    vessel_name: str
    gap_start_date: date
    gap_end_date: date
    gap_length_days: int

class IdleOption(BaseModel):
    option_type: str = Field(..., description="'reposition', 'short_fixture', or 'hold'")
    estimated_cost: float
    estimated_benefit: float
    description: str

class IdleOptionsResponse(BaseModel):
    vessel_id: UUID
    vessel_name: str
    options: List[IdleOption]
