"""
Feature store table — one row per date, exactly the 29-column contract
the four LightGBM models expect, plus staleness flags per source.
Lag/rolling features are computed by the feature builder job, not scrapers.
"""

import uuid
from sqlalchemy import Column, Date, Float, Integer, Boolean, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.config.database import Base


class FeatureStoreRow(Base):
    __tablename__ = "feature_store"
    __table_args__ = (UniqueConstraint("date", name="uq_feature_store_date"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, nullable=False, index=True)

    # --- Baltic indices (raw daily values, used to compute lags/rolls) ---
    bdi = Column(Float, nullable=True)
    bci = Column(Float, nullable=True)
    bpi = Column(Float, nullable=True)
    bsi = Column(Float, nullable=True)

    # --- Lag features (per index, computed by feature builder) ---
    bdi_lag_1 = Column(Float, nullable=True)
    bdi_lag_7 = Column(Float, nullable=True)
    bdi_lag_30 = Column(Float, nullable=True)
    bci_lag_1 = Column(Float, nullable=True)
    bci_lag_7 = Column(Float, nullable=True)
    bci_lag_30 = Column(Float, nullable=True)
    bpi_lag_1 = Column(Float, nullable=True)
    bpi_lag_7 = Column(Float, nullable=True)
    bpi_lag_30 = Column(Float, nullable=True)
    bsi_lag_1 = Column(Float, nullable=True)
    bsi_lag_7 = Column(Float, nullable=True)
    bsi_lag_30 = Column(Float, nullable=True)

    # --- Rolling stats (per index) ---
    bdi_roll7_mean = Column(Float, nullable=True)
    bdi_roll7_std = Column(Float, nullable=True)
    bdi_roll30_mean = Column(Float, nullable=True)
    bdi_roll30_std = Column(Float, nullable=True)
    bci_roll7_mean = Column(Float, nullable=True)
    bci_roll7_std = Column(Float, nullable=True)
    bci_roll30_mean = Column(Float, nullable=True)
    bci_roll30_std = Column(Float, nullable=True)
    bpi_roll7_mean = Column(Float, nullable=True)
    bpi_roll7_std = Column(Float, nullable=True)
    bpi_roll30_mean = Column(Float, nullable=True)
    bpi_roll30_std = Column(Float, nullable=True)
    bsi_roll7_mean = Column(Float, nullable=True)
    bsi_roll7_std = Column(Float, nullable=True)
    bsi_roll30_mean = Column(Float, nullable=True)
    bsi_roll30_std = Column(Float, nullable=True)

    # --- Seasonality ---
    month = Column(Integer, nullable=True)
    is_monsoon_season = Column(Integer, nullable=True)

    # --- Port activity ---
    total_port_calls = Column(Float, nullable=True)
    total_port_volume = Column(Float, nullable=True)

    # --- Malacca ---
    malacca_dry_bulk_calls = Column(Float, nullable=True)
    malacca_dry_bulk_capacity = Column(Float, nullable=True)

    # --- Bunker ---
    vlsfo_price_usd = Column(Float, nullable=True)
    mgo_price_usd = Column(Float, nullable=True)

    # --- Coking coal ---
    coking_coal_price_usd = Column(Float, nullable=True)

    # --- Manufacturing PMI ---
    manufacturing_pmi = Column(Float, nullable=True)

    # --- Steel production ---
    steel_production_mt = Column(Float, nullable=True)

    # --- Geo disruption ---
    geo_flag = Column(Integer, nullable=True)
    geo_severity = Column(Float, nullable=True)
    geo_days_active = Column(Integer, nullable=True)

    # --- Cyclone ---
    cyclone_india_flag = Column(Integer, nullable=True)
    cyclone_india_days = Column(Integer, nullable=True)
    cyclone_australia_flag = Column(Integer, nullable=True)
    cyclone_australia_days = Column(Integer, nullable=True)

    # --- Rainfall ---
    rainfall_paradip_mm = Column(Float, nullable=True)
    rainfall_vizag_mm = Column(Float, nullable=True)
    rainfall_haldia_mm = Column(Float, nullable=True)
    rainfall_hay_point_mm = Column(Float, nullable=True)
    rainfall_indonesia_mm = Column(Float, nullable=True)

    # --- Staleness flags (True = value was forward-filled, not freshly scraped) ---
    is_stale_bdi = Column(Boolean, nullable=False, default=False)
    is_stale_bunker = Column(Boolean, nullable=False, default=False)
    is_stale_coking_coal = Column(Boolean, nullable=False, default=False)
    is_stale_steel_production = Column(Boolean, nullable=False, default=False)
    is_stale_manufacturing_pmi = Column(Boolean, nullable=False, default=False)
    is_stale_cyclone = Column(Boolean, nullable=False, default=False)
    is_stale_rainfall = Column(Boolean, nullable=False, default=False)
    is_stale_geo_disruption = Column(Boolean, nullable=False, default=False)
    is_stale_malacca = Column(Boolean, nullable=False, default=False)
    is_stale_port_activity = Column(Boolean, nullable=False, default=False)
