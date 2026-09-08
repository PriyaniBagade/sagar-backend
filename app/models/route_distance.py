import uuid
from sqlalchemy import Column, String, Float, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.config.database import Base


class RouteDistance(Base):
    __tablename__ = "route_distances"
    __table_args__ = (
        UniqueConstraint("loading_port", "discharge_port", name="uq_route"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    loading_port = Column(String, nullable=False, index=True)
    discharge_port = Column(String, nullable=False, index=True)
    distance_nm = Column(Float, nullable=False)
    route_type = Column(String, nullable=False)  # "direct" | "suez"
