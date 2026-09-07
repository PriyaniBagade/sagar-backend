"""
Feature builder job — computes lag and rolling stats for each index
over the feature_store table, writing them back in place.
Run after ingest completes each day.

This is what turns raw daily BDI/BCI/BPI/BSI values into the 29-column
contract the four LightGBM models expect.
"""

import logging
import pandas as pd
from sqlalchemy.orm import Session
from app.config.database import SessionLocal
from app.models.feature_store import FeatureStoreRow

log = logging.getLogger(__name__)

INDICES = ["bdi", "bci", "bpi", "bsi"]


def build_features() -> None:
    db: Session = SessionLocal()
    try:
        rows = db.query(FeatureStoreRow).order_by(FeatureStoreRow.date).all()
        if len(rows) < 31:
            log.warning(
                "Only %d rows in feature store — lags/rolls will be sparse", len(rows)
            )

        # build a DataFrame from the raw index values
        records = [
            {
                "date": r.date,
                "id": r.id,
                "bdi": r.bdi,
                "bci": r.bci,
                "bpi": r.bpi,
                "bsi": r.bsi,
            }
            for r in rows
        ]
        df = pd.DataFrame(records).set_index("date").sort_index()

        for idx in INDICES:
            col = df[idx].astype(float)
            df[f"{idx}_lag_1"] = col.shift(1)
            df[f"{idx}_lag_7"] = col.shift(7)
            df[f"{idx}_lag_30"] = col.shift(30)
            df[f"{idx}_roll7_mean"] = col.shift(1).rolling(7, min_periods=1).mean()
            df[f"{idx}_roll7_std"] = col.shift(1).rolling(7, min_periods=2).std()
            df[f"{idx}_roll30_mean"] = col.shift(1).rolling(30, min_periods=1).mean()
            df[f"{idx}_roll30_std"] = col.shift(1).rolling(30, min_periods=2).std()

        # write computed features back
        id_map = {r.date: r for r in rows}
        for dt, row_data in df.iterrows():
            row_obj = id_map.get(dt)
            if row_obj is None:
                continue
            for idx in INDICES:
                for feat in [
                    f"{idx}_lag_1",
                    f"{idx}_lag_7",
                    f"{idx}_lag_30",
                    f"{idx}_roll7_mean",
                    f"{idx}_roll7_std",
                    f"{idx}_roll30_mean",
                    f"{idx}_roll30_std",
                ]:
                    val = row_data.get(feat)
                    if pd.notna(val):
                        setattr(row_obj, feat, float(val))

        db.commit()
        log.info("Feature builder complete — updated %d rows", len(rows))
    except Exception as e:
        db.rollback()
        log.exception("Feature builder failed: %s", e)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    build_features()
    print("Feature builder complete.")
