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
    # vessel & voyage parameters
    num_voyages: int
    vessel_capacity: float

    # voyage days breakdown (for 1 voyage)
    sailing_days: float
    load_days: float
    discharge_days: float
    canal_extra_days: float
    voyage_days: float  # single voyage duration

    # cost components (per voyage)
    market_tce_per_day: float  # index_points × multiplier
    freight_cost: float  # market_tce_per_day × voyage_days
    load_port_charges: float
    discharge_port_charges: float
    port_charges: float  # load_port_charges + discharge_port_charges
    insurance: float  # 1% of freight_cost
    cost_per_voyage: float  # freight_cost + port_charges + insurance

    # total recommendation & landed cost
    total_landed_cost: float  # cost_per_voyage × num_voyages
    landed_cost_per_mt: float  # total_landed_cost / quantity_mt

    # secondary OPEX / Net Result / TCE
    bunker_cost: float
    canal_toll: float
    commission: float
    opex_total: float
    net_result: float
    tce_per_day: float

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
    vessel_capacity: float = 75000.0,
) -> CostSummaryResult:
    import math

    vc = vessel_class.lower()

    speed = SPEED.get(vc, 14.0)
    consumption = CONSUMPTION.get(vc, {"laden_mtpd": 29.0, "port_mtpd": 3.5})
    opex_day = OPEX.get(vc, 7500.0)
    multiplier = INDEX_POINT_MULTIPLIER.get(vc, 9.0)

    # Step 1. Number of voyages needed
    cap = vessel_capacity if vessel_capacity > 0 else 75000.0
    num_voyages = math.ceil(quantity_mt / cap) if quantity_mt > 0 else 1

    # Step 2. Voyage days (for ONE trip)
    sailing_days = distance_nm / (speed * 24)
    load_days = cap / load_rate_mtpd if load_rate_mtpd > 0 else 0.0
    discharge_days = cap / discharge_rate_mtpd if discharge_rate_mtpd > 0 else 0.0
    canal_extra = CANAL_EXTRA_DAYS if route_type == "suez" else 0.0

    voyage_days = sailing_days + load_days + discharge_days + canal_extra

    # Step 3. Freight cost (ONE voyage)
    market_tce_per_day = index_points * multiplier
    freight_cost = market_tce_per_day * voyage_days

    # Step 4. Add discharge charges + insurance (ONE voyage)
    insurance = freight_cost * 0.01
    port_charges = load_port_charges + discharge_port_charges
    cost_per_voyage = freight_cost + port_charges + insurance

    # Step 5. Multiply by all voyages
    total_landed_cost = cost_per_voyage * num_voyages
    landed_cost_per_mt = total_landed_cost / quantity_mt if quantity_mt > 0 else 0.0

    # Secondary OPEX & Bunker breakdown
    sea_bunker = sailing_days * consumption["laden_mtpd"] * vlsfo_price
    port_bunker = (load_days + discharge_days) * consumption["port_mtpd"] * mgo_price
    bunker_cost = sea_bunker + port_bunker
    commission = freight_cost * COMMISSION_RATE
    canal_toll = CANAL_TOLL.get(vc, 200_000.0) if route_type == "suez" else 0.0
    opex_total = opex_day * voyage_days
    net_result = (
        freight_cost - commission - bunker_cost - port_charges - canal_toll - opex_total
    )
    tce_per_day = net_result / voyage_days if voyage_days > 0 else 0.0

    why = (
        f"Calculated for {quantity_mt:,.0f} MT cargo across {num_voyages} voyage(s) "
        f"using {vessel_class.capitalize()} ({cap:,.0f} MT capacity). "
        f"Each voyage takes {voyage_days:.1f} days at market rate ${market_tce_per_day:,.0f}/day "
        f"({index_points:,.0f} points × {multiplier})."
    )

    return CostSummaryResult(
        num_voyages=num_voyages,
        vessel_capacity=cap,
        sailing_days=round(sailing_days, 2),
        load_days=round(load_days, 2),
        discharge_days=round(discharge_days, 2),
        canal_extra_days=round(canal_extra, 2),
        voyage_days=round(voyage_days, 2),
        market_tce_per_day=round(market_tce_per_day, 2),
        freight_cost=round(freight_cost, 2),
        load_port_charges=round(load_port_charges, 2),
        discharge_port_charges=round(discharge_port_charges, 2),
        port_charges=round(port_charges, 2),
        insurance=round(insurance, 2),
        cost_per_voyage=round(cost_per_voyage, 2),
        total_landed_cost=round(total_landed_cost, 2),
        landed_cost_per_mt=round(landed_cost_per_mt, 2),
        bunker_cost=round(bunker_cost, 2),
        canal_toll=round(canal_toll, 2),
        commission=round(commission, 2),
        opex_total=round(opex_total, 2),
        net_result=round(net_result, 2),
        tce_per_day=round(tce_per_day, 2),
        vlsfo_price_used=vlsfo_price,
        mgo_price_used=mgo_price,
        index_points_used=index_points,
        index_multiplier_used=multiplier,
        route_distance_nm=distance_nm,
        route_type=route_type,
        tag="Approx. — predicted",
        why=why,
    )
