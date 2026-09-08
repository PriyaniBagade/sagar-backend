import uuid
import enum
from sqlalchemy import Column, String, Date, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.config.database import Base


class CharterStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    UPCOMING = "UPCOMING"
    COMPLETED = "COMPLETED"


class CharterSchedule(Base):
    __tablename__ = "charter_schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vessel_id = Column(UUID(as_uuid=True), ForeignKey("vessels.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(SAEnum(CharterStatus), nullable=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey("ports.id"), nullable=True)

    vessel = relationship("Vessel", back_populates="schedules")
    location = relationship("Port")
