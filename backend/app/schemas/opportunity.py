from datetime import date, datetime
from enum import Enum
from uuid import UUID
from pydantic import BaseModel, Field, HttpUrl

class Category(str, Enum):
    internship="internship"; scholarship="scholarship"; research="research"
    event="event"; academic="academic"; emergency="emergency"; general="general"; other="other"

class Priority(str, Enum):
    emergency="emergency"; urgent="urgent"; deadline="deadline"; general="general"

class Preferences(BaseModel):
    major: str | None = None
    academic_level: str | None = None
    interests: list[str] = Field(default_factory=list, max_length=50)
    organizations: list[str] = Field(default_factory=list, max_length=50)
    career_goals: list[str] = Field(default_factory=list, max_length=50)
    show_reminders: bool = True

class Opportunity(BaseModel):
    id: UUID
    title: str
    summary: str
    category: Category
    priority: Priority
    relevance_score: int = Field(ge=0, le=100)
    relevance_reason: str
    source_link: str | None = None
    event_start: datetime | None = None
    event_end: datetime | None = None
    deadline_at: datetime | None = None
    deadline_date: date | None = None
    location: str | None = None
    needs_review: bool = False
    saved: bool = False
    calendar_status: str = "not_added"

class OpportunityList(BaseModel):
    items: list[Opportunity]
    total: int
