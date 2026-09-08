from sqlalchemy.orm import Session
from datetime import date, timedelta
from app.models.vessel import Vessel
from app.models.charter_schedule import CharterSchedule, CharterStatus
from app.schemas.idle_management import IdleGapResponse, IdleOption, IdleOptionsResponse

# Mock static distances between some regions for the MVP
# In a real app, this would use an API or a larger port-to-port distance matrix
MOCK_DISTANCES_NM = {
    "default": 1000  # 1000 nautical miles
}

def calculate_idle_gaps(db: Session, min_gap_days: int = 3):
    vessels = db.query(Vessel).all()
    gaps = []
    
    for vessel in vessels:
        schedules = db.query(CharterSchedule).filter(
            CharterSchedule.vessel_id == vessel.id
        ).order_by(CharterSchedule.start_date).all()
        
        for i in range(len(schedules) - 1):
            current_charter = schedules[i]
            next_charter = schedules[i+1]
            
            gap_days = (next_charter.start_date - current_charter.end_date).days
            if gap_days >= min_gap_days:
                gaps.append(IdleGapResponse(
                    vessel_id=vessel.id,
                    vessel_name=vessel.name,
                    gap_start_date=current_charter.end_date,
                    gap_end_date=next_charter.start_date,
                    gap_length_days=gap_days
                ))
    
    return gaps

def generate_gap_options(db: Session, vessel_id: str, gap_start: date, gap_end: date):
    vessel = db.query(Vessel).filter(Vessel.id == vessel_id).first()
    if not vessel:
        return None

    gap_length = (gap_end - gap_start).days
    berthing_cost = vessel.vessel_class.berthing_fee_per_day or 2000.0
    
    # Option 1: Hold position
    hold_cost = gap_length * berthing_cost
    opt_hold = IdleOption(
        option_type="hold",
        estimated_cost=hold_cost,
        estimated_benefit=0.0,
        description=f"Hold position at current port for {gap_length} days."
    )
    
    # Option 2: Reposition
    # We use a mock distance for this MVP
    distance_nm = MOCK_DISTANCES_NM["default"]
    speed_knots = 13.0
    sailing_days = distance_nm / (speed_knots * 24)
    # Mock bunker price ($600 / ton), mock consumption (30 tons/day)
    bunker_cost = sailing_days * 30 * 600
    opt_repo = IdleOption(
        option_type="reposition",
        estimated_cost=bunker_cost,
        estimated_benefit=0.0,  # The benefit is being in a better position, hard to quantify right now
        description=f"Reposition to high-demand region. Estimated {sailing_days:.1f} days sailing."
    )
    
    # Option 3: Short fixture
    # Estimated revenue minus costs
    estimated_revenue = 15000.0 * gap_length # mock $15k / day rate
    opt_fixture = IdleOption(
        option_type="short_fixture",
        estimated_cost=bunker_cost + (2 * berthing_cost), # mock cost
        estimated_benefit=estimated_revenue,
        description=f"Take a short spot fixture for {gap_length} days."
    )
    
    return IdleOptionsResponse(
        vessel_id=vessel.id,
        vessel_name=vessel.name,
        options=[opt_hold, opt_repo, opt_fixture]
    )
