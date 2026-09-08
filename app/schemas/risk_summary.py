from pydantic import BaseModel
from enum import Enum


class RiskLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RiskCategory(BaseModel):
    risk: RiskLevel
    reason: str


class RiskSummaryResponse(BaseModel):
    route: dict[str, str]
    weather: RiskCategory
    bunker: RiskCategory
    port_activity: RiskCategory
    geopolitical: RiskCategory
