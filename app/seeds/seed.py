"""
Seed script — vessel classes and ports.
Run with: python -m app.seeds.seed
"""
from datetime import date
from app.config.database import SessionLocal, engine, Base
from app.models.port import Port, PortType
from app.models.vessel_class import VesselClass

# ensure tables exist
import app.models.port  # noqa
import app.models.vessel_class  # noqa
Base.metadata.create_all(bind=engine)


def seed():
    db = SessionLocal()
    try:
        # Skip if already seeded
        if db.query(VesselClass).count() > 0:
            print("Already seeded — skipping.")
            return

        # --------------------------------------------------------------
        # Vessel classes
        # Source: peer-reviewed AIS-tracking dataset (exact figures).
        # beam null except Panamax (32.3 — canal limit, not confirmed built-beam)
        # and Capesize (46.5).
        # --------------------------------------------------------------
        vessel_classes = [
            VesselClass(vessel_class="Small Handysize", dwt=11568,  draft=9,  loa=132, beam=None),
            VesselClass(vessel_class="Large Handysize", dwt=27834,  draft=10, loa=177, beam=None),
            VesselClass(vessel_class="Handymax",        dwt=54049,  draft=12, loa=227, beam=None),
            VesselClass(vessel_class="Panamax",         dwt=82618,  draft=12, loa=288, beam=32.3),  # canal-limit, not confirmed built-beam
            VesselClass(vessel_class="Capesize",        dwt=156000, draft=18, loa=295, beam=46.5),
        ]
        db.add_all(vessel_classes)

        # --------------------------------------------------------------
        # Discharge ports — India (fixed by PS text, do not add more)
        # Draft = one static conservative figure (MVP scoping — no tide-aware logic)
        # --------------------------------------------------------------
        discharge_ports = [
            Port(name="Paradip",                  country="India", type=PortType.DISCHARGE, max_draft=14.5, max_loa=300,  max_beam=48,   last_verified=date.today()),
            Port(name="Visakhapatnam Outer",       country="India", type=PortType.DISCHARGE, max_draft=18.1, max_loa=390,  max_beam=None, last_verified=date.today()),
            Port(name="Visakhapatnam Inner",       country="India", type=PortType.DISCHARGE, max_draft=14.5, max_loa=260,  max_beam=None, last_verified=date.today()),
            Port(name="Gangavaram",                country="India", type=PortType.DISCHARGE, max_draft=18.0, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Dhamra",                    country="India", type=PortType.DISCHARGE, max_draft=17.5, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Gopalpur",                  country="India", type=PortType.DISCHARGE, max_draft=14.5, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Haldia Dock Complex",       country="India", type=PortType.DISCHARGE, max_draft=9.1,  max_loa=None, max_beam=None, last_verified=date.today()),
            # Sagar-Sandheads: anchorage only — no physical berth constraints applicable
            Port(name="Sagar-Sandheads",           country="India", type=PortType.DISCHARGE, max_draft=None, max_loa=None, max_beam=None, last_verified=date.today()),
        ]
        db.add_all(discharge_ports)

        # --------------------------------------------------------------
        # Loading ports — Australia
        # null values are intentional: no figure found in research.
        # Treat null constraints as "unverified", not as zero/no-limit.
        # --------------------------------------------------------------
        loading_ports_australia = [
            Port(name="Newcastle — PWCS Carrington", country="Australia", type=PortType.LOADING, max_draft=16.5, max_loa=275,  max_beam=47,   last_verified=date.today()),
            Port(name="Newcastle — NCIG",            country="Australia", type=PortType.LOADING, max_draft=15.2, max_loa=230,  max_beam=32.3, last_verified=date.today()),
            Port(name="Port Kembla (PKCT)",          country="Australia", type=PortType.LOADING, max_draft=16.2, max_loa=300,  max_beam=50,   last_verified=date.today()),
            Port(name="Dalrymple Bay (DBCT)",        country="Australia", type=PortType.LOADING, max_draft=None, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Hay Point (HPCT)",            country="Australia", type=PortType.LOADING, max_draft=None, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Abbot Point (NQXT)",          country="Australia", type=PortType.LOADING, max_draft=19.1, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Gladstone — RG Tanna",        country="Australia", type=PortType.LOADING, max_draft=18.8, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Gladstone — WICET",           country="Australia", type=PortType.LOADING, max_draft=18.8, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Gladstone — Barney Point",    country="Australia", type=PortType.LOADING, max_draft=15.0, max_loa=None, max_beam=None, last_verified=date.today()),
        ]
        db.add_all(loading_ports_australia)

        # --------------------------------------------------------------
        # Loading ports — USA
        # --------------------------------------------------------------
        loading_ports_usa = [
            Port(name="Lamberts Point (Norfolk, VA)",                  country="USA", type=PortType.LOADING, max_draft=15.2, max_loa=None, max_beam=53.3, last_verified=date.today()),
            Port(name="Dominion Terminal Associates (Newport News, VA)",country="USA", type=PortType.LOADING, max_draft=None, max_loa=None, max_beam=53,   last_verified=date.today()),
            Port(name="Curtis Bay (Baltimore, MD)",                    country="USA", type=PortType.LOADING, max_draft=12.5, max_loa=198,  max_beam=24.7, last_verified=date.today()),
            Port(name="CONSOL Marine Terminal (Baltimore, MD)",        country="USA", type=PortType.LOADING, max_draft=None, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="McDuffie Terminal (Mobile, AL)",                country="USA", type=PortType.LOADING, max_draft=13.7, max_loa=300,  max_beam=50,   last_verified=date.today()),
            Port(name="IMT Myrtle Grove (New Orleans, LA)",            country="USA", type=PortType.LOADING, max_draft=18.9, max_loa=304.79,max_beam=45.72,last_verified=date.today()),
        ]
        db.add_all(loading_ports_usa)

        # --------------------------------------------------------------
        # Loading ports — Mozambique
        # --------------------------------------------------------------
        loading_ports_mozambique = [
            Port(name="Nacala-a-Velha",           country="Mozambique", type=PortType.LOADING, max_draft=None, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Beira — direct berth",     country="Mozambique", type=PortType.LOADING, max_draft=8.0,  max_loa=200,  max_beam=None, last_verified=date.today()),
            Port(name="Beira — offshore anchorage",country="Mozambique", type=PortType.LOADING, max_draft=None, max_loa=220,  max_beam=45,   last_verified=date.today()),
            Port(name="Matola (Maputo) — TCM",    country="Mozambique", type=PortType.LOADING, max_draft=None, max_loa=None, max_beam=None, last_verified=date.today()),
        ]
        db.add_all(loading_ports_mozambique)

        # --------------------------------------------------------------
        # Loading ports — Indonesia
        # Several rows are all-null on dimensions: real, actively-used loading
        # points confirmed via trade-flow data, but no draft/LOA/beam figure
        # found in research. Kept as placeholders — null = unverified, not zero.
        # --------------------------------------------------------------
        loading_ports_indonesia = [
            Port(name="Tanjung Bara (KPC)",                  country="Indonesia", type=PortType.LOADING, max_draft=17.25,max_loa=310,  max_beam=50,   last_verified=date.today()),
            Port(name="Taboneo Anchorage (Banjarmasin)",     country="Indonesia", type=PortType.LOADING, max_draft=19.0, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Muara Pantai / Berau Anchorage",      country="Indonesia", type=PortType.LOADING, max_draft=18.0, max_loa=289,  max_beam=None, last_verified=date.today()),
            Port(name="Balikpapan Coal Terminal",            country="Indonesia", type=PortType.LOADING, max_draft=13.0, max_loa=250,  max_beam=43,   last_verified=date.today()),
            Port(name="Adang Bay Anchorage",                 country="Indonesia", type=PortType.LOADING, max_draft=None, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Apar Bay Anchorage",                  country="Indonesia", type=PortType.LOADING, max_draft=19.0, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Tarahan Coal Port (Sumatra)",         country="Indonesia", type=PortType.LOADING, max_draft=None, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Samarinda Anchorage",                 country="Indonesia", type=PortType.LOADING, max_draft=None, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Muara Satui Anchorage",               country="Indonesia", type=PortType.LOADING, max_draft=None, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Bunati Transshipment Anchorage",      country="Indonesia", type=PortType.LOADING, max_draft=None, max_loa=None, max_beam=None, last_verified=date.today()),
            Port(name="Kotabaru",                            country="Indonesia", type=PortType.LOADING, max_draft=None, max_loa=None, max_beam=None, last_verified=date.today()),
        ]
        db.add_all(loading_ports_indonesia)

        db.commit()
        print("Seeded successfully.")
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed()
