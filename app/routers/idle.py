from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import date
from uuid import UUID

from app.config.database import get_db
from app.schemas.idle_management import IdleGapResponse, IdleOptionsResponse
from app.services.idle_management import calculate_idle_gaps, generate_gap_options

router = APIRouter(prefix="/idle", tags=["Idle Management"])


@router.get("/gaps", response_model=List[IdleGapResponse])
def get_idle_gaps(db: Session = Depends(get_db)):
    gaps = calculate_idle_gaps(db)
    return gaps


@router.get("/gaps/{vessel_id}/options", response_model=IdleOptionsResponse)
def get_idle_gap_options(
    vessel_id: UUID, gap_start: date, gap_end: date, db: Session = Depends(get_db)
):
    options_response = generate_gap_options(db, str(vessel_id), gap_start, gap_end)
    if not options_response:
        raise HTTPException(
            status_code=404, detail="Vessel not found or no options available"
        )
    return options_response
