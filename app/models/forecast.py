"""
Forecast store — one row per (date_generated, target_date, index).
P3/P4/P5 and the dashboard consume this table.
"""

import uuid
from sqlalchemy import Column, Date, Float, String, DateTime, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.config.database import Base


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (
        UniqueConstraint("date_generated", "target_date", "index", name="uq_forecast"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date_generated = Column(Date, nullable=False, index=True)
    target_date = Column(Date, nullable=False, index=True)
    index = Column(String(8), nullable=False)  # bdi | bci | bpi | bsi
    point_forecast = Column(Float, nullable=False)
    lower_bound = Column(Float, nullable=False)
    upper_bound = Column(Float, nullable=False)
    model_version = Column(String(32), nullable=False, default="v1")
    features_used = Column(JSON, nullable=True)  # snapshot of input row
    source_health = Column(JSON, nullable=True)  # {source: ok|stale|down}
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ForecastActual(Base):
    """
    Stores the actual BDI/BCI/BPI/BSI print once it's known, so the
    predicted-vs-actual chart and retraining error metrics can be computed.
    """

    __tablename__ = "forecast_actuals"
    __table_args__ = (UniqueConstraint("date", "index", name="uq_forecast_actual"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=False, index=True)
    index = Column(String(8), nullable=False)
    actual = Column(Float, nullable=False)
