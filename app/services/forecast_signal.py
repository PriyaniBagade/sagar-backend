"""
Forecast Signal — rule-based decision engine.
Deterministic: same inputs always produce the same verdict.
No ML model — uses outputs from the existing forecast + feature store.
"""

from dataclasses import dataclass, field

# Rainfall column mapping: port name substring → feature_store column
_RAINFALL_MAP: dict[str, str] = {
    "paradip": "rainfall_paradip_mm",
    "visakhapatnam": "rainfall_vizag_mm",
    "gangavaram": "rainfall_vizag_mm",
    "haldia": "rainfall_haldia_mm",
    "sagar": "rainfall_haldia_mm",
    "hay point": "rainfall_hay_point_mm",
    "abbot point": "rainfall_hay_point_mm",
    "dalrymple": "rainfall_hay_point_mm",
    "indonesia": "rainfall_indonesia_mm",
    "tanjung": "rainfall_indonesia_mm",
    "taboneo": "rainfall_indonesia_mm",
    "balikpapan": "rainfall_indonesia_mm",
    "samarinda": "rainfall_indonesia_mm",
    "kotabaru": "rainfall_indonesia_mm",
    "muara": "rainfall_indonesia_mm",
    "bunati": "rainfall_indonesia_mm",
    "adang": "rainfall_indonesia_mm",
    "apar": "rainfall_indonesia_mm",
    "tarahan": "rainfall_indonesia_mm",
}

_HEAVY_RAIN_MM = 20.0
_MODERATE_RAIN_MM = 5.0


@dataclass
class SignalFactor:
    name: str
    score: int
    description: str  # sentence fragment used to build reason
    summary: str  # short label for top_factors list


@dataclass
class SignalResult:
    verdict: str
    confidence: int
    reason: str
    score: int
    expected_bdi_change_pct: float
    factors: list[SignalFactor] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Factor scorers
# ---------------------------------------------------------------------------


def _bdi_factor(bdi_change_pct: float) -> SignalFactor:
    p = bdi_change_pct
    if p > 4:
        return SignalFactor(
            "BDI Forecast",
            50,
            f"freight is forecast to strengthen by {p:.1f}%",
            f"Expected to rise {p:.1f}%",
        )
    if p > 1:
        return SignalFactor(
            "BDI Forecast",
            25,
            f"freight is expected to rise moderately by {p:.1f}%",
            f"Moderate rise of {p:.1f}%",
        )
    if p >= -1:
        return SignalFactor(
            "BDI Forecast",
            0,
            "the freight market outlook is largely stable",
            "Stable outlook",
        )
    if p >= -4:
        return SignalFactor(
            "BDI Forecast",
            -25,
            f"freight is expected to soften by {abs(p):.1f}%",
            f"Expected to soften {abs(p):.1f}%",
        )
    return SignalFactor(
        "BDI Forecast",
        -50,
        f"freight is forecast to weaken by {abs(p):.1f}%",
        f"Expected to fall {abs(p):.1f}%",
    )


def _bunker_factor(current_vlsfo: float, prev_vlsfo: float) -> SignalFactor:
    change_pct = (
        ((current_vlsfo - prev_vlsfo) / prev_vlsfo * 100) if prev_vlsfo else 0.0
    )
    if change_pct > 3:
        return SignalFactor(
            "Bunker Trend",
            15,
            "rising bunker prices are increasing voyage costs",
            f"Fuel up {change_pct:.1f}% — higher voyage costs",
        )
    if change_pct < -3:
        return SignalFactor(
            "Bunker Trend",
            -15,
            "falling bunker prices are reducing voyage costs",
            f"Fuel down {abs(change_pct):.1f}% — lower voyage costs",
        )
    return SignalFactor(
        "Bunker Trend", 0, "bunker prices are stable", "Fuel prices stable"
    )


def _rainfall_factor(port_name: str, feature_store_row) -> SignalFactor:
    col = next(
        (col for key, col in _RAINFALL_MAP.items() if key in port_name.lower()),
        None,
    )
    if col is None:
        return SignalFactor("Rainfall", 0, "no rainfall data for this port", "No data")

    mm = getattr(feature_store_row, col, None) or 0.0
    if mm >= _HEAVY_RAIN_MM:
        return SignalFactor(
            "Rainfall",
            15,
            f"heavy rainfall at {port_name} may delay loading and tighten vessel availability",
            f"Heavy rain at {port_name} ({mm:.0f}mm)",
        )
    if mm >= _MODERATE_RAIN_MM:
        return SignalFactor(
            "Rainfall",
            5,
            f"moderate rainfall at {port_name} may cause minor port delays",
            f"Moderate rain at {port_name} ({mm:.0f}mm)",
        )
    return SignalFactor(
        "Rainfall",
        0,
        "no significant rainfall affecting port operations",
        "No significant rainfall",
    )


def _cyclone_factor(
    load_country: str, discharge_country: str, feature_store_row
) -> SignalFactor:
    india_flag = getattr(feature_store_row, "cyclone_india_flag", 0) or 0
    aus_flag = getattr(feature_store_row, "cyclone_australia_flag", 0) or 0
    countries = {load_country.lower(), discharge_country.lower()}
    affected = (india_flag and "india" in countries) or (
        aus_flag and "australia" in countries
    )
    if affected:
        return SignalFactor(
            "Cyclone",
            -30,
            "cyclone risk on the selected route increases operational uncertainty",
            "Active cyclone on route",
        )
    return SignalFactor(
        "Cyclone", 0, "no cyclone activity affecting this route", "No cyclone activity"
    )


def _geo_factor(feature_store_row) -> SignalFactor:
    if getattr(feature_store_row, "geo_flag", 0) or 0:
        return SignalFactor(
            "Geopolitical Disruption",
            -20,
            "an active geopolitical disruption increases route uncertainty",
            "Active disruption on the selected route",
        )
    return SignalFactor(
        "Geopolitical Disruption",
        0,
        "no geopolitical disruptions affecting this route",
        "No active disruptions",
    )


# ---------------------------------------------------------------------------
# Reason builder — uses top 2 non-zero factors
# ---------------------------------------------------------------------------


def _build_reason(factors: list[SignalFactor], verdict: str) -> str:
    top = sorted(
        [f for f in factors if f.score != 0],
        key=lambda f: abs(f.score),
        reverse=True,
    )[:2]

    if not top:
        return "The market outlook is largely stable with no significant signals on this route."

    d1 = top[0].description.capitalize()
    if len(top) == 1:
        if verdict == "BOOK_NOW":
            return f"{d1}, making this a favourable time to book."
        if verdict == "WAIT":
            return f"{d1}, suggesting it may be better to wait."
        return f"{d1}."

    d2 = top[1].description
    connector = (
        "while" if verdict == "BOOK_NOW" else "and" if verdict == "WAIT" else "though"
    )
    return f"{d1}, {connector} {d2}."


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute_signal(
    current_bdi: float,
    predicted_bdi: float,
    current_vlsfo: float,
    prev_vlsfo: float,
    load_port_name: str,
    discharge_port_name: str,
    load_port_country: str,
    discharge_port_country: str,
    feature_store_row,
) -> SignalResult:
    bdi_change_pct = (
        ((predicted_bdi - current_bdi) / current_bdi * 100) if current_bdi else 0.0
    )

    load_rain = _rainfall_factor(load_port_name, feature_store_row)
    discharge_rain = _rainfall_factor(discharge_port_name, feature_store_row)
    rain = (
        load_rain
        if abs(load_rain.score) >= abs(discharge_rain.score)
        else discharge_rain
    )

    factors: list[SignalFactor] = [
        _bdi_factor(bdi_change_pct),
        _bunker_factor(current_vlsfo, prev_vlsfo),
        rain,
        _cyclone_factor(load_port_country, discharge_port_country, feature_store_row),
        _geo_factor(feature_store_row),
    ]

    total = sum(f.score for f in factors)
    verdict = "BOOK_NOW" if total >= 40 else "WAIT" if total <= -40 else "HOLD"
    confidence = min(abs(total), 95)

    return SignalResult(
        verdict=verdict,
        confidence=confidence,
        reason=_build_reason(factors, verdict),
        score=total,
        expected_bdi_change_pct=round(bdi_change_pct, 2),
        factors=factors,
    )
