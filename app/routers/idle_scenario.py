"""
POST /api/v1/idle-scenario

Charter-centric idle scenario management.
Takes a charter_id, returns:
  - vessel info + current status
  - forecasted idle window (gap between discharge and next fixture)
  - alternative employment listings (demo data, scored live)
  - repositioning savings vs staying idle

Fit score formula (documented, repeatable):
  fit_score = 100 - (ballast_distance_nm / 10) + (estimated_rate_per_mt × 2)
  Capped at [0, 100].

Alternative employment listings are simulated demo data.
All financial calculations (fit score, savings) run live on that data.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.config.vessel_cost import SPEED, CONSUMPTION

router = APIRouter(prefix="/api/v1", tags=["Idle Scenario Management"])

# ─── Constants ────────────────────────────────────────────────────────────────

VLSFO_PRICE_USD_MT = 615.0  # fallback VLSFO price $/MT

# ─── Demo charter registry ────────────────────────────────────────────────────
# 3 charters across real system ports for demo coherence.

DEMO_CHARTERS: dict = {
    "CHT-2026-0417": {
        "charter_id": "CHT-2026-0417",
        "vessel_name": "MV Ocean Horizon",
        "vessel_type": "Panamax",
        "vessel_class": "panamax",
        "current_status": "Discharging at Paradip",
        "current_port": "Paradip",
        "current_lat": 20.31,
        "current_lng": 86.68,
        "expected_discharge_complete": "2026-09-26",
        "next_fixture": None,
        "alternative_employment": [
            {
                "route": "Paradip → Visakhapatnam",
                "cargo_type": "Iron Ore",
                "cargo_qty_mt": 60000,
                "estimated_rate_per_mt": 6.80,
                "ballast_distance_nm": 210,
            },
            {
                "route": "Paradip → Haldia",
                "cargo_type": "Thermal Coal",
                "cargo_qty_mt": 45000,
                "estimated_rate_per_mt": 5.20,
                "ballast_distance_nm": 340,
            },
            {
                "route": "Paradip → Gangavaram",
                "cargo_type": "Coking Coal",
                "cargo_qty_mt": 55000,
                "estimated_rate_per_mt": 7.10,
                "ballast_distance_nm": 290,
            },
        ],
    },
    "CHT-2026-0389": {
        "charter_id": "CHT-2026-0389",
        "vessel_name": "MV Sindhu Star",
        "vessel_type": "Capesize",
        "vessel_class": "capesize",
        "current_status": "Discharging at Visakhapatnam",
        "current_port": "Visakhapatnam",
        "current_lat": 17.69,
        "current_lng": 83.22,
        "expected_discharge_complete": "2026-09-30",
        "next_fixture": "CHT-2026-0441",
        "next_fixture_start": "2026-10-18",
        "alternative_employment": [
            {
                "route": "Visakhapatnam → Paradip",
                "cargo_type": "Iron Ore",
                "cargo_qty_mt": 140000,
                "estimated_rate_per_mt": 8.50,
                "ballast_distance_nm": 340,
            },
            {
                "route": "Visakhapatnam → Dhamra",
                "cargo_type": "Thermal Coal",
                "cargo_qty_mt": 120000,
                "estimated_rate_per_mt": 7.80,
                "ballast_distance_nm": 420,
            },
        ],
    },
    "CHT-2026-0402": {
        "charter_id": "CHT-2026-0402",
        "vessel_name": "MV Bay Trader",
        "vessel_type": "Supramax",
        "vessel_class": "supramax",
        "current_status": "Discharging at Haldia",
        "current_port": "Haldia Dock Complex",
        "current_lat": 22.03,
        "current_lng": 88.07,
        "expected_discharge_complete": "2026-10-02",
        "next_fixture": None,
        "alternative_employment": [
            {
                "route": "Haldia → Paradip",
                "cargo_type": "Thermal Coal",
                "cargo_qty_mt": 35000,
                "estimated_rate_per_mt": 5.80,
                "ballast_distance_nm": 280,
            },
            {
                "route": "Haldia → Visakhapatnam",
                "cargo_type": "Iron Ore",
                "cargo_qty_mt": 40000,
                "estimated_rate_per_mt": 6.20,
                "ballast_distance_nm": 580,
            },
        ],
    },
}


# ─── Fit score formula ────────────────────────────────────────────────────────
# fit_score = 100 - (ballast_distance_nm / 10) + (estimated_rate_per_mt × 2)
# Capped at [0, 100]. Documented and repeatable — not arbitrary.


def _fit_score(ballast_distance_nm: float, rate_per_mt: float) -> int:
    raw = 100 - (ballast_distance_nm / 10) + (rate_per_mt * 2)
    return max(0, min(100, round(raw)))


# ─── Ballast fuel cost ────────────────────────────────────────────────────────
# Speed and consumption from vessel_cost config.


def _ballast_fuel_cost(vessel_class: str, distance_nm: float) -> float:
    speed = SPEED.get(vessel_class, 14.0)
    consumption_dict = CONSUMPTION.get(vessel_class, {"laden_mtpd": 29.0})
    # Use laden rate as proxy for ballast (ballast is ~10% less but close enough for demo)
    consumption = consumption_dict.get("laden_mtpd", 29.0)
    days = distance_nm / (speed * 24)
    fuel_mt = days * consumption
    return round(fuel_mt * VLSFO_PRICE_USD_MT, 0)


# ─── Schemas ──────────────────────────────────────────────────────────────────


class IdleScenarioRequest(BaseModel):
    charter_id: str


# ─── Endpoint ─────────────────────────────────────────────────────────────────


@router.post(
    "/idle-scenario",
    summary="Idle window forecast + alternative employment for a charter",
)
def idle_scenario(payload: IdleScenarioRequest) -> dict:
    charter = DEMO_CHARTERS.get(payload.charter_id.upper())
    if not charter:
        raise HTTPException(
            status_code=404,
            detail=f"Charter '{payload.charter_id}' not found. "
            f"Available: {list(DEMO_CHARTERS.keys())}",
        )

    vc = charter["vessel_class"]

    # ── Idle window ───────────────────────────────────────────────────────────
    discharge_date = charter["expected_discharge_complete"]
    next_fixture = charter.get("next_fixture")
    next_start = charter.get("next_fixture_start")

    if next_fixture and next_start:
        idle_window = {
            "start_date": discharge_date,
            "end_date": next_start,
            "status": "bounded",
            "location": f"{charter['current_port']} anchorage",
        }
    else:
        idle_window = {
            "start_date": discharge_date,
            "end_date": None,
            "status": "open-ended",
            "location": f"{charter['current_port']} anchorage",
        }

    # ── Score alternative employment listings ─────────────────────────────────
    scored = []
    for opp in charter["alternative_employment"]:
        score = _fit_score(opp["ballast_distance_nm"], opp["estimated_rate_per_mt"])
        scored.append(
            {
                "route": opp["route"],
                "cargo_type": opp["cargo_type"],
                "cargo_qty_mt": opp["cargo_qty_mt"],
                "estimated_rate_per_mt": opp["estimated_rate_per_mt"],
                "ballast_distance_nm": opp["ballast_distance_nm"],
                "fit_score": score,
                "data_note": "Simulated listing",
            }
        )

    # Sort by fit score descending
    scored.sort(key=lambda x: x["fit_score"], reverse=True)

    # ── Repositioning savings ─────────────────────────────────────────────────
    # Best option = highest fit score
    best = scored[0] if scored else None
    repositioning_savings = None

    if best:
        backhaul_revenue = round(
            best["estimated_rate_per_mt"] * best["cargo_qty_mt"], 0
        )
        ballast_fuel = _ballast_fuel_cost(vc, best["ballast_distance_nm"])
        savings = round(backhaul_revenue - ballast_fuel, 0)

        repositioning_savings = {
            "best_option": best["route"],
            "estimated_backhaul_revenue": backhaul_revenue,
            "estimated_ballast_fuel_cost": ballast_fuel,
            "estimated_savings_usd": savings,
            "basis": (
                "Backhaul cargo revenue minus ballast leg fuel cost, "
                "compared against zero revenue while idle at anchor"
            ),
        }

    return {
        "vessel_name": charter["vessel_name"],
        "vessel_type": charter["vessel_type"],
        "charter_id": charter["charter_id"],
        "current_status": charter["current_status"],
        "current_position": {
            "port": charter["current_port"],
            "lat": charter["current_lat"],
            "lng": charter["current_lng"],
        },
        "expected_discharge_complete": discharge_date,
        "next_fixture": next_fixture,
        "forecasted_idle_windows": [idle_window],
        "alternative_employment": scored,
        "repositioning_savings": repositioning_savings,
        "data_disclaimer": (
            "Alternative employment listings are simulated for demo purposes. "
            "Idle window, fit score, and savings calculations are computed live from this data."
        ),
    }


@router.get(
    "/idle-scenario/charters",
    summary="List all available demo charters",
)
def list_charters() -> list:
    return [
        {
            "charter_id": c["charter_id"],
            "vessel_name": c["vessel_name"],
            "vessel_type": c["vessel_type"],
            "current_status": c["current_status"],
            "expected_discharge_complete": c["expected_discharge_complete"],
        }
        for c in DEMO_CHARTERS.values()
    ]
