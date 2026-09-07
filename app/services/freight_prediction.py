"""
Inference service — loads the four LightGBM models once at startup and
exposes get_forecast() for a single index or all four at once.

Feature column order must match the training contract in the PRD exactly.
"""

import logging
import datetime
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from sqlalchemy.orm import Session

from app.models.feature_store import FeatureStoreRow
from app.models.forecast import Forecast, ForecastActual

log = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent.parent / "models_output"
INDICES = ["bdi", "bci", "bpi", "bsi"]

# Human-readable factor groups — maps display name to the feature columns it covers.
# SHAP values for all columns in a group are summed to produce one contribution number.
FACTOR_GROUPS = {
    "Recent index momentum": lambda idx: [
        f"{idx}_lag_1",
        f"{idx}_lag_7",
        f"{idx}_lag_30",
        f"{idx}_roll7_mean",
        f"{idx}_roll7_std",
        f"{idx}_roll30_mean",
        f"{idx}_roll30_std",
    ],
    "Bunker fuel cost": lambda idx: ["vlsfo_price_usd"],
    "Coking coal price": lambda idx: ["coking_coal_price_usd"],
    "Port & shipping activity": lambda idx: [
        "total_port_calls",
        "total_port_volume",
        "malacca_dry_bulk_calls",
        "malacca_dry_bulk_capacity",
    ],
    "Macro demand": lambda idx: ["manufacturing_pmi", "steel_production_mt"],
    "Weather & disruption": lambda idx: [
        "geo_flag",
        "geo_severity",
        "geo_days_active",
        "cyclone_india_flag",
        "cyclone_india_days",
        "cyclone_australia_flag",
        "cyclone_australia_days",
        "rainfall_paradip_mm",
        "rainfall_vizag_mm",
        "rainfall_haldia_mm",
        "rainfall_hay_point_mm",
        "rainfall_indonesia_mm",
    ],
    "Seasonality": lambda idx: ["month", "is_monsoon_season"],
}


def _feature_cols(idx: str) -> list[str]:
    return [
        f"{idx}_lag_1",
        f"{idx}_lag_7",
        f"{idx}_lag_30",
        f"{idx}_roll7_mean",
        f"{idx}_roll7_std",
        f"{idx}_roll30_mean",
        f"{idx}_roll30_std",
        "month",
        "is_monsoon_season",
        "total_port_calls",
        "total_port_volume",
        "malacca_dry_bulk_calls",
        "malacca_dry_bulk_capacity",
        "vlsfo_price_usd",
        "coking_coal_price_usd",
        "manufacturing_pmi",
        "steel_production_mt",
        "geo_flag",
        "geo_severity",
        "geo_days_active",
        "cyclone_india_flag",
        "cyclone_india_days",
        "cyclone_australia_flag",
        "cyclone_australia_days",
        "rainfall_paradip_mm",
        "rainfall_vizag_mm",
        "rainfall_haldia_mm",
        "rainfall_hay_point_mm",
        "rainfall_indonesia_mm",
    ]


# Loaded once at module import time
_models: dict = {}


def _load_models() -> None:
    for idx in INDICES:
        path = MODELS_DIR / f"{idx}_lightgbm_model.joblib"
        if not path.exists():
            log.error("Model file not found: %s", path)
            continue
        _models[idx] = joblib.load(path)
        log.info("Loaded model: %s", path.name)


_load_models()


def _model_version(idx: str) -> str:
    versioned = sorted(MODELS_DIR.glob(f"{idx}_lightgbm_model_v*.joblib"))
    if versioned:
        stem = versioned[-1].stem
        return stem.split("_v")[-1] if "_v" in stem else "v1"
    return "v1"


def _build_feature_row(store_row: FeatureStoreRow, idx: str) -> pd.DataFrame:
    cols = _feature_cols(idx)
    data = {col: getattr(store_row, col, None) for col in cols}
    return pd.DataFrame([data], columns=cols)


def _confidence_band(model, X: pd.DataFrame, point: float) -> tuple[float, float]:
    try:
        staged = list(model.staged_predict(X.values))
        if staged:
            leaf_preds = np.array([s[0] for s in staged])
            if len(leaf_preds) > 1:
                sigma = float(np.std(leaf_preds))
                return point - 1.96 * sigma, point + 1.96 * sigma
    except Exception:
        pass
    return point * 0.90, point * 1.10


def _compute_drivers(model, X: pd.DataFrame, idx: str) -> list[dict]:
    """
    Use SHAP TreeExplainer to compute per-feature contributions, then group
    them into human-readable factors sorted by absolute impact.
    """
    try:
        import shap

        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)
        if isinstance(shap_values, list):
            shap_values = shap_values[0]
        shap_row = np.array(shap_values).reshape(
            -1
        )  # force 1D regardless of shap version
        col_names = list(X.columns)
        shap_map = dict(zip(col_names, shap_row))

        drivers = []
        for factor_name, cols_fn in FACTOR_GROUPS.items():
            cols = cols_fn(idx)
            contribution = sum(float(shap_map.get(c, 0.0)) for c in cols)
            drivers.append(
                {
                    "factor": factor_name,
                    "contribution": round(contribution, 2),
                    "direction": "up" if contribution >= 0 else "down",
                }
            )

        drivers.sort(key=lambda d: abs(d["contribution"]), reverse=True)
        return drivers

    except Exception as e:
        log.warning("SHAP computation failed: %s", e, exc_info=True)
        return []


def _next_business_day(d: datetime.date) -> datetime.date:
    """Skip weekends — BDI is not published on weekends."""
    d += datetime.timedelta(days=1)
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d += datetime.timedelta(days=1)
    return d


def _forecast_one(
    model, X: pd.DataFrame, idx: str
) -> tuple[float, float, float, list[dict]]:
    """Run model + confidence band + SHAP on a single feature row. Returns (point, lower, upper, drivers)."""
    point = float(model.predict(X)[0])
    lower, upper = _confidence_band(model, X, point)
    drivers = _compute_drivers(model, X, idx)
    return round(point, 2), round(lower, 2), round(upper, 2), drivers


def _source_health(store_row: FeatureStoreRow) -> dict:
    stale_fields = [
        "bdi",
        "bunker",
        "coking_coal",
        "steel_production",
        "manufacturing_pmi",
        "cyclone",
        "rainfall",
        "geo_disruption",
        "malacca",
        "port_activity",
    ]
    health = {}
    for src in stale_fields:
        flag = getattr(store_row, f"is_stale_{src}", None)
        if flag is None:
            health[src] = "unknown"
        elif flag:
            health[src] = "stale"
        else:
            health[src] = "ok"
    return health


def get_forecast(idx: str, db: Session, days: int = 1) -> dict | list[dict]:
    """
    Forecast `days` ahead for a single index.
    days=1  → returns a single ForecastResponse dict (existing behaviour)
    days>1  → returns a list of ForecastResponse dicts, one per business day

    Multi-day works by iterative prediction:
      day 1 prediction → becomes lag_1 input for day 2
      day 2 prediction → becomes lag_1 for day 3, etc.
    All other features (macro, weather, etc.) are held constant at today's
    values — they update daily via ingest, not per-hour.
    """
    idx = idx.lower()
    if idx not in INDICES:
        raise ValueError(f"Unknown index '{idx}'. Must be one of: {INDICES}")
    if not 1 <= days <= 30:
        raise ValueError("days must be between 1 and 30")

    model = _models.get(idx)
    if model is None:
        raise RuntimeError(f"Model for '{idx}' not loaded — check models_output/")

    store_row = db.query(FeatureStoreRow).order_by(FeatureStoreRow.date.desc()).first()
    if store_row is None:
        raise RuntimeError("Feature store is empty — run the ingest job first")

    today = datetime.date.today()
    source_health = _source_health(store_row)
    model_ver = _model_version(idx)

    # Seed the rolling state from the feature store
    X_base = _build_feature_row(store_row, idx).fillna(0).astype(float)

    # We'll mutate lag/roll cols iteratively — work on a copy
    X_current = X_base.copy()

    # Track recent predictions to update rolling features
    # Seed with lag_1 from feature store (yesterday's actual value)
    recent_values: list[float] = []
    seed_lag1 = float(X_base[f"{idx}_lag_1"].iloc[0])
    if seed_lag1 > 0:
        recent_values.append(seed_lag1)

    results = []
    target_date = today

    for step in range(days):
        target_date = _next_business_day(target_date) if step > 0 else today

        # Update lag features from previous predictions
        if step > 0:
            prev_pred = results[-1]["point_forecast"]
            # shift lags: lag_1 = last prediction, lag_7/30 shift forward
            X_current[f"{idx}_lag_1"] = prev_pred
            if step >= 7:
                X_current[f"{idx}_lag_7"] = (
                    results[step - 7]["point_forecast"]
                    if step >= 7
                    else X_base[f"{idx}_lag_7"].iloc[0]
                )
            if step >= 30:
                X_current[f"{idx}_lag_30"] = results[step - 30]["point_forecast"]

            # update rolling stats from accumulated predictions
            recent_values.append(prev_pred)
            window7 = recent_values[-7:]
            window30 = recent_values[-30:]
            X_current[f"{idx}_roll7_mean"] = float(np.mean(window7))
            X_current[f"{idx}_roll7_std"] = (
                float(np.std(window7)) if len(window7) > 1 else 0.0
            )
            X_current[f"{idx}_roll30_mean"] = float(np.mean(window30))
            X_current[f"{idx}_roll30_std"] = (
                float(np.std(window30)) if len(window30) > 1 else 0.0
            )

            # update month/seasonality for the target date
            X_current["month"] = float(target_date.month)
            X_current["is_monsoon_season"] = float(
                1 if target_date.month in (6, 7, 8, 9) else 0
            )

        point, lower, upper, drivers = _forecast_one(model, X_current, idx)

        # widen confidence band for further-out forecasts (uncertainty grows)
        spread = (upper - lower) / 2
        widened_lower = round(point - spread * (1 + step * 0.15), 2)
        widened_upper = round(point + spread * (1 + step * 0.15), 2)

        entry = {
            "index": idx.upper(),
            "target_date": str(target_date),
            "point_forecast": point,
            "lower_bound": widened_lower,
            "upper_bound": widened_upper,
            "generated_at": str(today),
            "model_version": model_ver,
            "data_freshness": source_health,
            "drivers": drivers,
        }

        # persist each day's forecast
        existing = (
            db.query(Forecast)
            .filter(
                Forecast.date_generated == today,
                Forecast.target_date == target_date,
                Forecast.index == idx,
            )
            .first()
        )
        features_snapshot = {c: float(v) for c, v in X_current.iloc[0].items()}
        if existing:
            existing.point_forecast = point
            existing.lower_bound = widened_lower
            existing.upper_bound = widened_upper
            existing.features_used = features_snapshot
            existing.source_health = source_health
        else:
            db.add(
                Forecast(
                    date_generated=today,
                    target_date=target_date,
                    index=idx,
                    point_forecast=point,
                    lower_bound=widened_lower,
                    upper_bound=widened_upper,
                    model_version=model_ver,
                    features_used=features_snapshot,
                    source_health=source_health,
                )
            )
        db.commit()
        results.append(entry)

    return results[0] if days == 1 else results


def get_all_forecasts(db: Session, days: int = 1) -> dict:
    return {idx: get_forecast(idx, db, days=days) for idx in INDICES}


def get_forecast_history(idx: str, db: Session) -> list[dict]:
    idx = idx.lower()
    forecasts = (
        db.query(Forecast)
        .filter(Forecast.index == idx)
        .order_by(Forecast.target_date)
        .all()
    )
    actuals_map = {
        a.date: a.actual
        for a in db.query(ForecastActual).filter(ForecastActual.index == idx).all()
    }
    result = []
    for f in forecasts:
        actual = actuals_map.get(f.target_date)
        error = round(f.point_forecast - actual, 2) if actual is not None else None
        result.append(
            {
                "date": str(f.target_date),
                "predicted": f.point_forecast,
                "actual": actual,
                "error": error,
            }
        )
    return result
