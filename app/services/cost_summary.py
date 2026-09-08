"""
Cost summary calculation — pure Python, no FastAPI deps.
All lookup data is passed in as plain values; config constants imported from vessel_cost.py.

Freight calc:
  market_tce_per_day = index_points * INDEX_POINT_MULTIPLIER[vessel_class]
  freight_cost       = market_tce_per_day * voyage_days
"""

from dataclasses import dataclass
from app.config.vessel_cost import (
    SPEED,
    CONSUMPTION,
    OPEX,
    CANAL_TOLL,
    CANAL_EXTRA_DAYS,
    COMMISSION_RATE,
    INDEX_POINT_MULTIPLIER,
)

# Maps vessel class to the feature_store column holding its index points
INDEX_COLUMN: dict[str, str] = {
    "handysize": "bsi",  # BHSI not in feature store — BSI used as proxy
    "supramax": "bsi",  # BSI
    "panamax": "bpi",  # BPI
    "capesize": "bci",  # BCI
}


@dataclass
class CostSummaryResult:
    # voyage days breakdown
    sailing_days: float
    load_days: float
    discharge_days: float
    canal_extra_days: float
    voyage_days: float

    # cost components
    freight_cost: float
    market_tce_per_day: float  # index_points × multiplier
    port_charges: float
    bunker_cost: float
    canal_toll: float
    commission: float
    opex_total: float
    net_result: float
    tce_per_day: float
    landed_cost_per_mt: float

    # snapshots
    vlsfo_price_used: float
    mgo_price_used: float
    index_points_used: float
    index_multiplier_used: float
    route_distance_nm: float
    route_type: str

    # meta
    tag: str
    why: str


def compute_cost_summary(
    vessel_class: str,
    quantity_mt: float,
    distance_nm: float,
    route_type: str,
    load_rate_mtpd: float,
    discharge_rate_mtpd: float,
    load_port_charges: float,
    discharge_port_charges: float,
    vlsfo_price: float,
    mgo_price: float,
    index_points: float,
) -> CostSummaryResult:
    vc = vessel_class.lower()

    speed = SPEED[vc]
    consumption = CONSUMPTION[vc]
    opex_day = OPEX[vc]
    multiplier = INDEX_POINT_MULTIPLIER[vc]

    # 3. Sailing days
    sailing_days = distance_nm / (speed * 24)

    # 4-5. Port days
    load_days = quantity_mt / load_rate_mtpd
    discharge_days = quantity_mt / discharge_rate_mtpd

    # 6. Canal extra days
    canal_extra = CANAL_EXTRA_DAYS if route_type == "suez" else 0.0

    # 7. Total voyage days
    voyage_days = sailing_days + load_days + discharge_days + canal_extra

    # 8-10. Bunker costs
    sea_bunker = sailing_days * consumption["laden_mtpd"] * vlsfo_price
    port_bunker = (load_days + discharge_days) * consumption["port_mtpd"] * mgo_price
    bunker_cost = sea_bunker + port_bunker

    # 11-12. Freight via index point multiplier
    market_tce_per_day = index_points * multiplier
    freight_cost = market_tce_per_day * voyage_days

    # 13. Commission
    commission = freight_cost * COMMISSION_RATE

    # 14. Port charges
    port_charges = load_port_charges + discharge_port_charges

    # 15. Canal toll
    canal_toll = CANAL_TOLL[vc] if route_type == "suez" else 0.0

    # 16. OPEX
    opex_total = opex_day * voyage_days

    # 17. Net result (freight after all deductions including OPEX)
    net_result = (
        freight_cost - commission - bunker_cost - port_charges - canal_toll - opex_total
    )

    # 18. TCE = net_result / voyage_days (net_result already has OPEX deducted)
    tce_per_day = net_result / voyage_days

    # 19. Landed cost per MT
    landed_cost_per_mt = (
        bunker_cost + port_charges + canal_toll + commission + opex_total
    ) / quantity_mt

    why = (
        f"Based on the current {vessel_class.capitalize()} Baltic Index "
        f"({index_points:,.0f} points \u2192 estimated market TCE ${market_tce_per_day:,.0f}/day) "
        f"for this {voyage_days:.1f}-day voyage, "
        f"adjusted for current bunker prices (VLSFO ${vlsfo_price:.0f}/MT, MGO ${mgo_price:.0f}/MT)."
    )

    return CostSummaryResult(
        sailing_days=round(sailing_days, 2),
        load_days=round(load_days, 2),
        discharge_days=round(discharge_days, 2),
        canal_extra_days=canal_extra,
        voyage_days=round(voyage_days, 2),
        freight_cost=round(freight_cost, 2),
        market_tce_per_day=round(market_tce_per_day, 2),
        port_charges=round(port_charges, 2),
        bunker_cost=round(bunker_cost, 2),
        canal_toll=round(canal_toll, 2),
        commission=round(commission, 2),
        opex_total=round(opex_total, 2),
        net_result=round(net_result, 2),
        tce_per_day=round(tce_per_day, 2),
        landed_cost_per_mt=round(landed_cost_per_mt, 2),
        vlsfo_price_used=vlsfo_price,
        mgo_price_used=mgo_price,
        index_points_used=index_points,
        index_multiplier_used=multiplier,
        route_distance_nm=distance_nm,
        route_type=route_type,
        tag="Approx. — predicted",
        why=why,
    )
