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


def _compute_drivers(
    model, X: pd.DataFrame, idx: str, compute_shap: bool = True
) -> list[dict]:
    """
    Use SHAP TreeExplainer to compute per-feature contributions, then group
    them into human-readable factors sorted by absolute impact.

    If compute_shap is False or SHAP fails, returns empty list instead of blocking.
    """
    if not compute_shap:
        return []

    try:
        import shap

        # Set a timeout on SHAP computation — if it takes >5s, bail out
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("SHAP computation exceeded 5 seconds")

        # Note: signal.alarm() only works on Unix. On Windows, SHAP may still be slow.
        # We'll just let it run but log a warning if it's slow.

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

    except TimeoutError:
        log.warning("SHAP computation timeout for %s — skipping drivers", idx)
        return []
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
    model, X: pd.DataFrame, idx: str, compute_shap: bool = False
) -> tuple[float, float, float, list[dict]]:
    """Run model + confidence band + SHAP on a single feature row. Returns (point, lower, upper, drivers).

    compute_shap=False by default to avoid slow SHAP computation on API requests.
    Set to True only for detailed driver analysis (can take 1-5s per forecast).
    """
    point = float(model.predict(X)[0])
    lower, upper = _confidence_band(model, X, point)
    drivers = (
        _compute_drivers(model, X, idx, compute_shap=compute_shap)
        if compute_shap
        else []
    )
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

        point, lower, upper, drivers = _forecast_one(
            model, X_current, idx, compute_shap=False
        )

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


def save_daily_actuals(db: Session) -> dict[str, float | None]:
    """
    Read today's BDI/BCI/BPI/BSI values from the feature store and upsert
    them into forecast_actuals so the predicted-vs-actual chart has real data.

    Called at the end of the daily pipeline, after ingest + feature_builder.
    Returns a dict of { index: value_saved } for logging.
    """
    today = datetime.date.today()
    store_row = db.query(FeatureStoreRow).filter(FeatureStoreRow.date == today).first()
    if store_row is None:
        log.warning("save_daily_actuals: no feature store row for %s", today)
        return {}

    saved = {}
    for idx in INDICES:
        value = getattr(store_row, idx, None)
        if value is None:
            log.warning("save_daily_actuals: %s is NULL for %s, skipping", idx, today)
            saved[idx] = None
            continue

        existing = (
            db.query(ForecastActual)
            .filter(ForecastActual.date == today, ForecastActual.index == idx)
            .first()
        )
        if existing:
            existing.actual = value
        else:
            db.add(ForecastActual(date=today, index=idx, actual=value))

        saved[idx] = value

    db.commit()
    log.info("save_daily_actuals: saved actuals for %s → %s", today, saved)
    return saved


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


# ---------------------------------------------------------------------------
# Spec-shaped helpers used by the new router endpoints
# ---------------------------------------------------------------------------


def _confidence_pct_from_band(point: float, lower: float, upper: float) -> int:
    """
    Derive a 0-95 confidence % from how tight the band is relative to point.
    Tight band (< 5% spread) → ~90%, wide band (> 20%) → ~55%.
    """
    if point <= 0:
        return 70
    spread_pct = (upper - lower) / point * 100
    if spread_pct <= 5:
        return 90
    if spread_pct <= 10:
        return 80
    if spread_pct <= 15:
        return 72
    if spread_pct <= 20:
        return 65
    return 55


def get_spec_forecast(idx: str, db: Session, forecast_horizon_days: int) -> dict:
    """
    Returns a spec-shaped dict for a single index:
    { index, forecast_horizon_days, current_value, forecast: [...], confidence_pct }
    """
    idx_lower = idx.lower()
    log.info(
        "get_spec_forecast starting: index=%s, horizon=%s",
        idx_lower,
        forecast_horizon_days,
    )

    raw = get_forecast(idx_lower, db, days=forecast_horizon_days)
    if not isinstance(raw, list):
        raw = [raw]

    store_row = db.query(FeatureStoreRow).order_by(FeatureStoreRow.date.desc()).first()
    current_value = getattr(store_row, idx_lower, None) if store_row else None

    forecast_days = [
        {
            "date": r["target_date"],
            "predicted_value": r["point_forecast"],
            "low": r["lower_bound"],
            "high": r["upper_bound"],
        }
        for r in raw
    ]

    # Use the last day's band to derive an overall confidence_pct
    last = raw[-1]
    confidence_pct = _confidence_pct_from_band(
        last["point_forecast"], last["lower_bound"], last["upper_bound"]
    )

    log.info(
        "get_spec_forecast completed: index=%s, forecast_days=%d, confidence=%d%%",
        idx_lower,
        len(forecast_days),
        confidence_pct,
    )

    return {
        "index": idx.upper(),
        "forecast_horizon_days": forecast_horizon_days,
        "current_value": current_value,
        "forecast": forecast_days,
        "confidence_pct": confidence_pct,
    }


def get_spec_all_forecasts(db: Session, forecast_horizon_days: int) -> dict:
    """
    Returns the allPurpose response shape:
    { forecast_horizon_days, indices: { BDI: {...}, BCI: {...}, BPI: {...}, BSI: {...} } }
    """
    # Quick check: if feature store is empty, fail fast with clear error
    store_row = db.query(FeatureStoreRow).order_by(FeatureStoreRow.date.desc()).first()
    if store_row is None:
        raise RuntimeError(
            "Feature store is empty — run the daily ingest pipeline first to generate market data (BDI, bunker, etc.)"
        )

    indices_data = {}
    for idx in INDICES:
        result = get_spec_forecast(idx, db, forecast_horizon_days)
        indices_data[idx.upper()] = {
            "current_value": result["current_value"],
            "forecast": result["forecast"],
            "confidence_pct": result["confidence_pct"],
        }
    return {
        "forecast_horizon_days": forecast_horizon_days,
        "indices": indices_data,
    }


def get_spec_forecast_history(idx: str, db: Session, lookback_days: int) -> dict:
    """
    Returns spec-shaped history:
    { index, lookback_days, history: [{date, predicted_value, actual_value}], mean_absolute_error_pct }

    Only returns resolved past dates (target_date <= today) so the x-axis
    never extends into the future.  We query the Forecast table for the
    *earliest* forecast generated for each target_date (date_generated ==
    target_date means the prediction was made the same day it was for, which
    is the standard daily-run case).
    """
    idx_lower = idx.lower()
    today = datetime.date.today()
    cutoff = today - datetime.timedelta(days=lookback_days)

    # Only past resolved dates — never future
    forecasts = (
        db.query(Forecast)
        .filter(
            Forecast.index == idx_lower,
            Forecast.target_date >= cutoff,
            Forecast.target_date <= today,
        )
        .order_by(Forecast.target_date)
        .all()
    )
    actuals_map = {
        a.date: a.actual
        for a in db.query(ForecastActual)
        .filter(ForecastActual.index == idx_lower)
        .all()
    }

    history = []
    errors = []
    for f in forecasts:
        actual = actuals_map.get(f.target_date)
        history.append(
            {
                "date": str(f.target_date),
                "predicted_value": f.point_forecast,
                "actual_value": actual,
            }
        )
        if actual is not None and actual > 0:
            errors.append(abs(f.point_forecast - actual) / actual * 100)

    mae_pct = round(float(np.mean(errors)), 2) if errors else None

    return {
        "index": idx.upper(),
        "lookback_days": lookback_days,
        "history": history,
        "mean_absolute_error_pct": mae_pct,
    }
