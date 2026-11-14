from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.schemas.calendar import CalendarEventRequest
from app.security import current_user
from app.services.calendar_service import create_calendar_event

router = APIRouter()


@router.post("/calendar/events")
def add_calendar_event(payload: CalendarEventRequest, user=Depends(current_user)):
    result, created = create_calendar_event(
        user,
        str(payload.opportunity_id),
        payload.confirmed,
        payload.all_day,
        payload.start,
        payload.end,
        payload.time_zone,
    )
    return JSONResponse(status_code=201 if created else 200, content=result)
