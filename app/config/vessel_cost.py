"""
Vessel cost calculation constants — MVP hardcoded values.
All per-port and per-route data lives in the DB (ports, route_distances tables).
These are class-level physical/commercial constants that only change with a
deliberate business/fleet decision.
"""

# Speed in knots — laden leg only (ballast leg out of scope for MVP)
SPEED: dict[str, float] = {
    "handysize": 13.5,
    "supramax": 13.5,
    "panamax": 14.0,
    "capesize": 13.5,
}

# Fuel consumption in MT/day
CONSUMPTION: dict[str, dict[str, float]] = {
    "handysize": {"laden_mtpd": 19.0, "port_mtpd": 2.5},
    "supramax": {"laden_mtpd": 27.0, "port_mtpd": 2.5},
    "panamax": {"laden_mtpd": 29.0, "port_mtpd": 3.5},
    "capesize": {"laden_mtpd": 36.0, "port_mtpd": 4.5},
}

# Daily operating expenditure in USD
OPEX: dict[str, float] = {
    "handysize": 6000.0,
    "supramax": 7000.0,
    "panamax": 7500.0,
    "capesize": 8500.0,
}

# Flat Suez Canal toll in USD — only applied when route_type == "suez"
CANAL_TOLL: dict[str, float] = {
    "handysize": 150_000.0,
    "supramax": 200_000.0,
    "panamax": 200_000.0,
    "capesize": 300_000.0,
}

# Extra transit days added for Suez routing
CANAL_EXTRA_DAYS: float = 1.5

# Flat broker commission rate applied to freight cost
COMMISSION_RATE: float = 0.05

# Baltic index point → market TCE/day multipliers
# freight_cost = (index_points × multiplier) × voyage_days
# Source: derived from Baltic Exchange fixture data for India coal trade routes.
INDEX_POINT_MULTIPLIER: dict[str, float] = {
    "handysize": 18.0,
    "supramax": 12.64,
    "panamax": 9.0,
    "capesize": 8.3,
}

# Default port handling rates (MT/day) — used only when load_rate_mtpd /
# discharge_rate_mtpd are not populated on a port row.
DEFAULT_LOAD_RATE_MTPD: float = 40000.0
DEFAULT_DISCHARGE_RATE_MTPD: float = 15000.0
