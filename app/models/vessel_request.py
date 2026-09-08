"""
Vessel optimization request table — one row per /vessel/optimize call,
updated in-place by /vessel/cost-summary and /vessel/cost-breakdown.
"""

import uuid
from sqlalchemy import Column, String, Float, Integer, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.config.database import Base


class VesselOptimizationRequest(Base):
    __tablename__ = "vessel_optimization_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- inputs ---
    cargo_type = Column(String, nullable=True)  # "coking coal", "thermal coal", etc.
    loading_port_id = Column(UUID(as_uuid=True), ForeignKey("ports.id"), nullable=False)
    discharge_port_id = Column(
        UUID(as_uuid=True), ForeignKey("ports.id"), nullable=False
    )
    quantity_mt = Column(Float, nullable=False)

    # --- optimize output ---
    recommended_class = Column(String, nullable=True)
    selected_class = Column(
        String, nullable=True
    )  # class actually used for cost calc (user can override)
    voyages_needed = Column(Integer, nullable=True)
    eligible_classes = Column(JSON, nullable=True)  # list[str]
    rejected_classes = Column(JSON, nullable=True)  # list[{class, reason}]
    optimization_warnings = Column(JSON, nullable=True)  # list[str]
    constraint_table = Column(JSON, nullable=True)  # port vs vessel constraint detail
    why_lines = Column(JSON, nullable=True)  # list[str], 2 human-readable lines

    # --- voyage estimate (shared calc) ---
    sailing_days = Column(Float, nullable=True)
    load_days = Column(Float, nullable=True)
    discharge_days = Column(Float, nullable=True)
    canal_extra_days = Column(Float, nullable=True)  # 0 or 1.5 (Suez transit days)
    voyage_days = Column(Float, nullable=True)

    # --- cost breakdown ---
    freight_cost_usd = Column(Float, nullable=True)
    bunker_cost_usd = Column(Float, nullable=True)  # sea + port bunker combined
    canal_toll_usd = Column(Float, nullable=True)  # 0 or flat toll per vessel class
    commission_usd = Column(Float, nullable=True)  # freight_cost × 0.05
    opex_total_usd = Column(Float, nullable=True)  # OPEX/day × voyage_days
    net_result_usd = Column(
        Float, nullable=True
    )  # freight - commission - bunker - port - canal
    tce_per_day = Column(Float, nullable=True)  # (net_result - opex) / voyage_days
    port_charges_usd = Column(Float, nullable=True)
    inland_cost_usd = Column(Float, nullable=True)
    total_landed_cost_usd = Column(Float, nullable=True)
    landed_cost_per_mt = Column(Float, nullable=True)
    cost_confidence = Column(String, nullable=True, default="Approx. — predicted")

    # --- price snapshots used in calc ---
    vlsfo_price_used = Column(Float, nullable=True)  # VLSFO $/MT at calc time
    mgo_price_used = Column(Float, nullable=True)  # MGO $/MT at calc time
    index_points_used = Column(Float, nullable=True)  # BDI/class index points used
    index_to_price_ratio = Column(
        Float, nullable=True
    )  # ratio used to derive freight_rate

    # --- route info used in calc ---
    route_distance_nm = Column(
        Float, nullable=True
    )  # distance from route_distances table
    route_type = Column(String, nullable=True)  # "direct" | "suez"

    # --- forecast inputs used ---
    forecast_bdi = Column(Float, nullable=True)
    forecast_index = Column(String, nullable=True)  # "bdi" | "bci" | "bpi" | "bsi"
    model_version = Column(String, nullable=True)
