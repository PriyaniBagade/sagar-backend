"""
sync_tables.py  --  sync all SQLAlchemy models to the DB.

* Creates tables that do not exist yet  (via create_all)
* Detects and ALTER-ADDs columns that exist in the model but not in the DB
* Never drops anything

Usage (from d:/SIH - 006/SAGAR with venv active):
    python sync_tables.py
"""

# -- Import all models so SQLAlchemy registers their metadata --
import app.models.port  # noqa: F401
import app.models.vessel_class  # noqa: F401
import app.models.feature_store  # noqa: F401
import app.models.forecast  # noqa: F401
import app.models.vessel_request  # noqa: F401
import app.models.route_distance  # noqa: F401
import app.models.vessel  # noqa: F401
import app.models.charter_schedule  # noqa: F401

from app.config.database import engine, Base
from sqlalchemy import text, inspect

# ── SQLAlchemy type -> Postgres DDL type ─────────────────────────────────────
SA_TO_PG = {
    "VARCHAR": "VARCHAR",
    "TEXT": "TEXT",
    "INTEGER": "INTEGER",
    "BIGINT": "BIGINT",
    "FLOAT": "DOUBLE PRECISION",
    "NUMERIC": "NUMERIC",
    "BOOLEAN": "BOOLEAN",
    "JSON": "JSON",
    "JSONB": "JSONB",
    "UUID": "UUID",
    "DATE": "DATE",
    "DATETIME": "TIMESTAMP WITH TIME ZONE",
    "TIMESTAMP": "TIMESTAMP WITH TIME ZONE",
}


def pg_type(col):
    name = type(col.type).__name__.upper()
    return SA_TO_PG.get(name, "TEXT")  # fall back to TEXT if unknown


if __name__ == "__main__":
    print("Syncing tables ...\n")

    # Step 1: create any missing tables
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    altered = []

    with engine.connect() as conn:
        for table_name, table in Base.metadata.tables.items():
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col in table.columns:
                if col.name not in existing_cols:
                    dtype = pg_type(col)
                    nullable = "NULL" if col.nullable else "NOT NULL"
                    default = ""
                    if col.server_default is not None:
                        default = f" DEFAULT {col.server_default.arg}"
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {dtype}{default} {nullable}"
                    conn.execute(text(sql))
                    altered.append(f"{table_name}.{col.name}  ({dtype})")
                    print(f"  + {table_name}.{col.name}  ({dtype})")
        conn.commit()

    tables = sorted(Base.metadata.tables.keys())
    print(f"\nDone!  {len(tables)} table(s) in schema:")
    for t in tables:
        print(f"   * {t}")

    if altered:
        print(f"\n{len(altered)} column(s) added:")
        for a in altered:
            print(f"   + {a}")
    else:
        print("\nNo schema changes needed.")
