"""
Fixed-schema retraining job — Section 7 of the PRD.

Pulls feature_store rows + actuals, retrains the four LightGBM models
on extended history (same 29-feature schema, no field changes), computes
MAE/RMSE on a holdout window, promotes only if error improves.

Run manually or on a weekly/monthly schedule.
Usage:
    python -m app.jobs.retrain
"""

import logging
import shutil
from pathlib import Path
from datetime import date

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.models.feature_store import FeatureStoreRow
from app.models.forecast import ForecastActual
from app.services.freight_prediction import _feature_cols, MODELS_DIR

log = logging.getLogger(__name__)

HOLDOUT_DAYS = 30  # last 30 days used for eval, rest for training
MIN_TRAIN_ROWS = 60


def _load_dataset(db: Session) -> pd.DataFrame:
    rows = db.query(FeatureStoreRow).order_by(FeatureStoreRow.date).all()
    actuals = {(a.date, a.index): a.actual for a in db.query(ForecastActual).all()}

    records = []
    for r in rows:
        base = {
            col: getattr(r, col, None)
            for col in [
                "date",
                "bdi",
                "bci",
                "bpi",
                "bsi",
                "bdi_lag_1",
                "bdi_lag_7",
                "bdi_lag_30",
                "bdi_roll7_mean",
                "bdi_roll7_std",
                "bdi_roll30_mean",
                "bdi_roll30_std",
                "bci_lag_1",
                "bci_lag_7",
                "bci_lag_30",
                "bci_roll7_mean",
                "bci_roll7_std",
                "bci_roll30_mean",
                "bci_roll30_std",
                "bpi_lag_1",
                "bpi_lag_7",
                "bpi_lag_30",
                "bpi_roll7_mean",
                "bpi_roll7_std",
                "bpi_roll30_mean",
                "bpi_roll30_std",
                "bsi_lag_1",
                "bsi_lag_7",
                "bsi_lag_30",
                "bsi_roll7_mean",
                "bsi_roll7_std",
                "bsi_roll30_mean",
                "bsi_roll30_std",
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
        }
        for idx in ("bdi", "bci", "bpi", "bsi"):
            base[f"actual_{idx}"] = actuals.get((r.date, idx), base.get(idx))
        records.append(base)

    return pd.DataFrame(records)


def _next_version() -> str:
    existing = sorted(MODELS_DIR.glob("bdi_lightgbm_model_v*.joblib"))
    if not existing:
        return "v2"
    last = existing[-1].stem  # e.g. bdi_lightgbm_model_v3
    n = int(last.split("_v")[-1])
    return f"v{n + 1}"


def _mae(y_true, y_pred) -> float:
    return float(np.mean(np.abs(np.array(y_true) - np.array(y_pred))))


def _rmse(y_true, y_pred) -> float:
    return float(np.sqrt(np.mean((np.array(y_true) - np.array(y_pred)) ** 2)))


def run_retrain() -> dict:
    db: Session = SessionLocal()
    results = {}
    try:
        df = _load_dataset(db)
        if len(df) < MIN_TRAIN_ROWS + HOLDOUT_DAYS:
            log.warning(
                "Not enough data for retraining (%d rows). Need %d.",
                len(df),
                MIN_TRAIN_ROWS + HOLDOUT_DAYS,
            )
            return {"error": "insufficient data"}

        df = df.sort_values("date").reset_index(drop=True)
        new_version = _next_version()

        for idx in ("bdi", "bci", "bpi", "bsi"):
            feat_cols = _feature_cols(idx)
            target_col = f"actual_{idx}"

            sub = df[feat_cols + [target_col, "date"]].dropna(subset=[target_col])
            if len(sub) < MIN_TRAIN_ROWS + HOLDOUT_DAYS:
                log.warning(
                    "Skipping %s — not enough rows with actuals (%d)", idx, len(sub)
                )
                continue

            train = sub.iloc[:-HOLDOUT_DAYS]
            holdout = sub.iloc[-HOLDOUT_DAYS:]

            X_train = train[feat_cols].fillna(0)
            y_train = train[target_col]
            X_holdout = holdout[feat_cols].fillna(0)
            y_holdout = holdout[target_col]

            # train new model
            new_model = LGBMRegressor(n_estimators=500, random_state=42)
            new_model.fit(X_train, y_train)
            new_preds = new_model.predict(X_holdout)
            new_mae = _mae(y_holdout, new_preds)
            new_rmse = _rmse(y_holdout, new_preds)

            # eval existing model on same holdout
            current_path = MODELS_DIR / f"{idx}_lightgbm_model.joblib"
            if current_path.exists():
                current_model = joblib.load(current_path)
                curr_preds = current_model.predict(X_holdout)
                curr_mae = _mae(y_holdout, curr_preds)
            else:
                curr_mae = float("inf")

            promoted = False
            if new_mae < curr_mae:
                # archive current
                if current_path.exists():
                    archive = MODELS_DIR / f"{idx}_lightgbm_model_{new_version}.joblib"
                    shutil.copy(current_path, archive)
                joblib.dump(new_model, current_path)
                promoted = True
                log.info(
                    "Promoted new %s model — MAE %.1f < %.1f", idx, new_mae, curr_mae
                )
            else:
                log.info(
                    "Kept existing %s model — new MAE %.1f >= current %.1f",
                    idx,
                    new_mae,
                    curr_mae,
                )

            results[idx] = {
                "new_mae": round(new_mae, 2),
                "new_rmse": round(new_rmse, 2),
                "current_mae": round(curr_mae, 2) if curr_mae != float("inf") else None,
                "promoted": promoted,
                "version": new_version if promoted else "unchanged",
            }

        return results
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = run_retrain()
    for idx, metrics in r.items():
        print(f"{idx.upper()}: {metrics}")
