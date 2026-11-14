"""Classification and ranking contract for the AggieConnect AI workstream (Dev 3).

PROVISIONAL: these shapes follow the master plan. Freeze them against
docs/api-contract.md (owned by Dev 4) once it lands on main, and route any
change through the contract PR before updating consumers.

Python 3.9 compatible: use Optional[...] / List[...], not ``X | None``.
"""

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

CLASSIFIER_VERSION = "ai-classifier/0.1.0"

MAX_TITLE = 120
MAX_SUMMARY = 500
MAX_LOCATION = 200
MAX_TAGS = 10
MAX_TAG_LEN = 40


class Category(str, Enum):
    internship = "internship"
    scholarship = "scholarship"
    research = "research"
    event = "event"
    academic = "academic"
    emergency = "emergency"
    general = "general"
    other = "other"


class Priority(str, Enum):
    emergency = "emergency"
    urgent = "urgent"
    deadline = "deadline"
    general = "general"


# Lane order for the feed: lower sorts first.
PRIORITY_LANE_ORDER = {
    Priority.emergency: 0,
    Priority.urgent: 1,
    Priority.deadline: 2,
    Priority.general: 3,
}


class ClassificationSource(str, Enum):
    model = "model"  # validated provider output
    fallback = "fallback"  # rule-based classifier (provider off or failed)
    previous = "previous"  # prior good classification kept after a transient error


class NormalizedMessage(BaseModel):
    """Input to classify_email().

    Produced by the sync pipeline (Dev 2 / Dev 4) from a Graph message, or loaded
    from demo fixtures. ``verified_emergency_source`` is TRUSTED provenance set
    outside the model (in the prototype only by controlled fixture metadata);
    nothing the model says can set it.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    subject: str = ""
    body: str = ""
    sender: Optional[str] = None
    received_at: AwareDatetime
    source_link: Optional[str] = None
    verified_emergency_source: bool = False

    @model_validator(mode="before")
    @classmethod
    def _accept_graph_service_shape(cls, data):
        """Accept Dev 2's graph_service.list_recent_messages() rows directly.

        They carry the text as ``body_preview`` (Graph bodyPreview) and may send an
        empty sender. Graph rows have no verified_emergency_source, so it defaults to
        False; only trusted pipeline code should ever set it.
        """
        if isinstance(data, dict):
            data = dict(data)
            if not data.get("body") and data.get("body_preview"):
                data["body"] = data["body_preview"]
            if data.get("sender") == "":
                data["sender"] = None
        return data


class Classification(BaseModel):
    """Exactly what the model must return. Every key is required; nullable keys
    must still be present (null when the message does not state the fact)."""

    model_config = ConfigDict(extra="forbid")

    category: Category
    suggested_priority: Priority
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    summary: str = Field(max_length=MAX_SUMMARY)
    tags: List[str] = Field(max_length=MAX_TAGS)
    event_start: Optional[AwareDatetime]
    event_end: Optional[AwareDatetime]
    deadline_at: Optional[AwareDatetime]
    deadline_date: Optional[date]
    location: Optional[str] = Field(max_length=MAX_LOCATION)
    confidence: float = Field(ge=0.0, le=1.0)
    needs_review: bool

    @field_validator("tags")
    @classmethod
    def _bound_tags(cls, tags: List[str]) -> List[str]:
        cleaned = []
        for tag in tags:
            tag = " ".join(tag.split()).strip()
            if not tag:
                continue
            if len(tag) > MAX_TAG_LEN:
                raise ValueError("tag longer than %d characters" % MAX_TAG_LEN)
            cleaned.append(tag)
        return cleaned

    @model_validator(mode="after")
    def _resolve_inconsistencies(self) -> "Classification":
        # Inconsistent details are flagged and left unresolved rather than guessed.
        if self.event_end is not None and self.event_start is None:
            self.event_end = None
            self.needs_review = True
        if self.event_start is not None and self.event_end is not None and self.event_end <= self.event_start:
            self.event_end = None
            self.needs_review = True
        return self


class ClassifiedMessage(BaseModel):
    """Result of classify_email(): the validated extraction plus the
    trust-policy decisions made outside the model. Dev 4 stores these fields."""

    message_id: str
    classification: Classification
    priority: Priority  # final lane after trust policy, NOT the model's suggestion
    verified_source: bool
    needs_review: bool
    source: ClassificationSource
    fallback_reason: Optional[str] = None
    classifier_version: str = CLASSIFIER_VERSION
    content_hash: str
    received_at: datetime


class Preferences(BaseModel):
    """Student preferences used for ranking (mirrors PUT /api/me/preferences)."""

    model_config = ConfigDict(extra="ignore")

    major: Optional[str] = Field(default=None, max_length=80)
    academic_level: Optional[str] = Field(default=None, max_length=40)
    interests: List[str] = Field(default_factory=list, max_length=20)
    organizations: List[str] = Field(default_factory=list, max_length=20)
    career_goals: List[str] = Field(default_factory=list, max_length=20)
    show_reminders: bool = True


class RankResult(BaseModel):
    relevance_score: int = Field(ge=0, le=100)
    relevance_reason: str
    matched_fields: List[str]  # e.g. ["interest", "major"], in weight order
