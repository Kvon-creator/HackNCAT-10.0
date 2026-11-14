from pydantic import BaseModel, Field
from uuid import UUID


class CalendarEventRequest(BaseModel):
    opportunity_id: UUID
    confirmed: bool
    all_day: bool
    start: str = Field(min_length=1, max_length=64)
    end: str = Field(min_length=1, max_length=64)
    time_zone: str = Field(min_length=1, max_length=80)
