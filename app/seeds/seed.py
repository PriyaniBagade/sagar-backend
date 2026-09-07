"""
Seed script — loads ports from data/Ports Data.xlsx and vessel classes.
Wipes existing ports + vessel_classes rows first so re-running is safe.

Run with:
    python -m app.seeds.seed
"""

import re
from datetime import date
from pathlib import Path
import openpyxl

from app.config.database import SessionLocal, engine, Base
from app.models.port import Port, PortType
from app.models.vessel_class import VesselClass

import app.models.port  # noqa
import app.models.vessel_class  # noqa

Base.metadata.create_all(bind=engine)

DATA_FILE = Path(__file__).parent.parent.parent / "data" / "Ports Data.xlsx"


def _parse_draft(raw) -> float | None:
    """Handle values like 14.5, '14.5/16.50', '13+ tide', 'N/A'."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s.upper() in ("N/A", "N/a", ""):
        return None
    # "14.5/16.50" — take the conservative (smaller) value
    if "/" in s:
        parts = [p.strip() for p in s.split("/")]
        nums = []
        for p in parts:
            m = re.search(r"[\d.]+", p)
            if m:
                nums.append(float(m.group()))
        return min(nums) if nums else None
    # "13+ tide" — extract the number
    m = re.search(r"[\d.]+", s)
    return float(m.group()) if m else None


def _parse_float(raw) -> float | None:
    """Return float or None for N/A, N/a, text strings."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s.upper() in ("N/A", "N/A", "N/a", ""):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(raw) -> int | None:
    f = _parse_float(raw)
    return int(f) if f is not None else None


def seed():
    db = SessionLocal()
    try:
        # --- wipe existing data ---
        db.query(Port).delete()
        db.query(VesselClass).delete()
        db.commit()
        print("Cleared existing ports and vessel classes.")

        # --- vessel classes (unchanged from research data) ---
        vessel_classes = [
            VesselClass(
                vessel_class="Small Handysize", dwt=11568, draft=9, loa=132, beam=None
            ),
            VesselClass(
                vessel_class="Large Handysize", dwt=27834, draft=10, loa=177, beam=None
            ),
            VesselClass(
                vessel_class="Handymax", dwt=54049, draft=12, loa=227, beam=None
            ),
            VesselClass(
                vessel_class="Panamax", dwt=82618, draft=12, loa=288, beam=32.3
            ),
            VesselClass(
                vessel_class="Capesize", dwt=156000, draft=18, loa=295, beam=46.5
            ),
        ]
        db.add_all(vessel_classes)

        # --- ports from xlsx ---
        wb = openpyxl.load_workbook(DATA_FILE)
        ws = wb[wb.sheetnames[0]]  # "Ports Data " (note trailing space)

        ports = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            (
                name,
                country,
                port_type_raw,
                draft_raw,
                loa_raw,
                beam_raw,
                berths_raw,
                _,
            ) = row

            if not name or not port_type_raw:
                continue

            try:
                port_type = PortType[port_type_raw.strip().upper()]
            except KeyError:
                print(f"  Skipping unknown port type '{port_type_raw}' for {name}")
                continue

            ports.append(
                Port(
                    name=str(name).strip(),
                    country=str(country).strip() if country else "Unknown",
                    type=port_type,
                    max_draft=_parse_draft(draft_raw),
                    max_loa=_parse_float(loa_raw),
                    max_beam=_parse_float(beam_raw),
                    berths=_parse_int(berths_raw),
                    last_verified=date.today(),
                )
            )

        db.add_all(ports)
        db.commit()
        print(
            f"Seeded {len(vessel_classes)} vessel classes and {len(ports)} ports from Ports Data.xlsx."
        )

    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed()
