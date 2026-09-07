import uuid
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.config.database import Base


class Vessel(Base):
    __tablename__ = "vessels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    vessel_class_id = Column(UUID(as_uuid=True), ForeignKey("vessel_classes.id"), nullable=False)
    current_location_id = Column(UUID(as_uuid=True), ForeignKey("ports.id"), nullable=True)

    vessel_class = relationship("VesselClass", backref="vessels")
    current_location = relationship("Port", backref="vessels")
    schedules = relationship("CharterSchedule", back_populates="vessel", cascade="all, delete-orphan")
