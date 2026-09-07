from sqlalchemy.orm import Session
from datetime import date, timedelta
from app.config.database import SessionLocal, engine, Base
from app.models.vessel_class import VesselClass
from app.models.port import Port, PortType
from app.models.vessel import Vessel
from app.models.charter_schedule import CharterSchedule, CharterStatus

def seed_idle_management_data():
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()
    
    # Check if we have vessels already
    if db.query(Vessel).count() > 0:
        print("Vessels already seeded.")
        db.close()
        return

    print("Seeding vessels and charter schedules...")
    
    # 1. Get or create some base data
    vessel_class = db.query(VesselClass).first()
    if not vessel_class:
        vessel_class = VesselClass(vessel_class="Panamax", dwt=75000, draft=13, loa=225)
        db.add(vessel_class)
        db.commit()
        db.refresh(vessel_class)
        
    port1 = db.query(Port).first()
    if not port1:
        port1 = Port(name="Singapore", country="SG", type=PortType.LOADING)
        db.add(port1)
        db.commit()
        db.refresh(port1)
        
    port2 = db.query(Port).filter(Port.id != port1.id).first()
    if not port2:
        port2 = Port(name="Rotterdam", country="NL", type=PortType.DISCHARGE)
        db.add(port2)
        db.commit()
        db.refresh(port2)

    # 2. Create Vessels
    vessel1 = Vessel(name="Oceanic Explorer", vessel_class_id=vessel_class.id, current_location_id=port1.id)
    vessel2 = Vessel(name="Pacific Trader", vessel_class_id=vessel_class.id, current_location_id=port2.id)
    
    db.add_all([vessel1, vessel2])
    db.commit()
    db.refresh(vessel1)
    db.refresh(vessel2)
    
    today = date.today()
    
    # 3. Create Schedules for Vessel 1 (Creates an idle gap of 10 days)
    # Schedule 1: ends in 5 days
    s1_v1 = CharterSchedule(
        vessel_id=vessel1.id,
        start_date=today - timedelta(days=10),
        end_date=today + timedelta(days=5),
        status=CharterStatus.ACTIVE,
        location_id=port1.id
    )
    # Schedule 2: starts in 15 days
    s2_v1 = CharterSchedule(
        vessel_id=vessel1.id,
        start_date=today + timedelta(days=15),
        end_date=today + timedelta(days=35),
        status=CharterStatus.UPCOMING,
        location_id=port2.id
    )
    
    # 4. Create Schedules for Vessel 2 (No gap)
    s1_v2 = CharterSchedule(
        vessel_id=vessel2.id,
        start_date=today - timedelta(days=5),
        end_date=today + timedelta(days=10),
        status=CharterStatus.ACTIVE,
        location_id=port2.id
    )
    s2_v2 = CharterSchedule(
        vessel_id=vessel2.id,
        start_date=today + timedelta(days=10),
        end_date=today + timedelta(days=20),
        status=CharterStatus.UPCOMING,
        location_id=port1.id
    )

    db.add_all([s1_v1, s2_v1, s1_v2, s2_v2])
    db.commit()
    
    print("Successfully seeded vessels and schedules!")
    db.close()

if __name__ == "__main__":
    seed_idle_management_data()
