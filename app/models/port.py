import uuid
from sqlalchemy import Column, String, Float, Integer, Date, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.config.database import Base


class PortType(str, enum.Enum):
    LOADING = "LOADING"
    DISCHARGE = "DISCHARGE"


class Port(Base):
    __tablename__ = "ports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    country = Column(String, nullable=False)
    type = Column(SAEnum(PortType), nullable=False)
    # Draft modelled as a single static conservative figure (MVP scoping choice —
    # tide-aware/tidal-window adjustments are out of scope for this iteration).
    max_draft = Column(Float, nullable=True)   # meters; null = unverified
    max_loa = Column(Float, nullable=True)     # meters; null = unverified
    max_beam = Column(Float, nullable=True)    # meters; null = unverified
    berths = Column(Integer, nullable=True)
    handling_rate = Column(Float, nullable=True)  # MT/day
    last_verified = Column(Date, nullable=True)
    source_url = Column(String, nullable=True)
