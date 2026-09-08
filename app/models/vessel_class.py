import uuid
from sqlalchemy import Column, String, Float
from sqlalchemy.dialects.postgresql import UUID
from app.config.database import Base


class VesselClass(Base):
    __tablename__ = "vessel_classes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # "class" is a reserved word in Python — using vessel_class as column name,
    # mapped to "class" column in DB via name argument.
    vessel_class = Column("class", String, nullable=False, unique=True)
    index = Column(String, nullable=True)  # Baltic index: BCI, BPI, BSI, BHSI
    dwt = Column(Float, nullable=False)  # deadweight tonnage
    draft = Column(Float, nullable=False)  # meters
    loa = Column(Float, nullable=False)  # meters
    beam = Column(Float, nullable=True)  # meters; null for most classes
    charter_cost_per_day = Column(Float, nullable=True)  # USD
    berthing_fee_per_day = Column(Float, nullable=True)  # USD
