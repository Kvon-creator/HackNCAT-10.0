"""POST /api/classify: classify and rank one pasted announcement on the spot (Dev 3).

Used by the site's "Try any announcement" panel so a live audience can see the
classifier work on text it has never seen. Nothing is stored.

Uses the rule-based classifier unless OPENAI_API_KEY and OPENAI_MODEL are set in the
server's process environment, and reports which one answered. Ranking uses the
caller's saved preferences, exactly like the feed.
"""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import demo_store
from app.schemas.classification import ClassificationSource, NormalizedMessage
from app.security import current_user
from app.services.ai_classifier import (
    classify_email,
    clean_subject,
    provider_from_env,
    safety_signals,
    sanitize_text,
)
from app.services.demo_feed import coerce_preferences
from app.services.ranking_service import rank_tags

router = APIRouter()


class ClassifyRequest(BaseModel):
    subject: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=5000)
    sender: str | None = Field(default=None, max_length=200)


def _iso(value):
    return value.isoformat() if value is not None else None


@router.post("/classify")
def classify_announcement(payload: ClassifyRequest, user=Depends(current_user)):
    if not payload.subject.strip() and not payload.body.strip():
        raise HTTPException(422, "Enter a subject or message text to classify")

    message = NormalizedMessage(
        id="try-" + uuid4().hex[:12],
        subject=payload.subject,
        body=payload.body,
        sender=payload.sender or None,
        received_at=datetime.now(timezone.utc),
        verified_emergency_source=False,  # pasted text is never a trusted source
    )
    result = classify_email(message, provider=provider_from_env())
    cls = result.classification
    with demo_store.seed_lock:
        profile = demo_store.profiles.get(user["sub"])
    ranked = rank_tags(cls.tags, coerce_preferences(profile))
    text = clean_subject(payload.subject) + "\n" + sanitize_text(payload.body)

    return {
        "title": cls.title,
        "summary": cls.summary,
        "category": cls.category.value,
        "priority": result.priority.value,
        "suggested_priority": cls.suggested_priority.value,
        "relevance_score": ranked.relevance_score,
        "relevance_reason": ranked.relevance_reason,
        "event_start": _iso(cls.event_start),
        "event_end": _iso(cls.event_end),
        "deadline_at": _iso(cls.deadline_at),
        "deadline_date": _iso(cls.deadline_date),
        "location": cls.location,
        "needs_review": result.needs_review,
        "verified_source": result.verified_source,
        "confidence": cls.confidence,
        "classified_by": "AI model" if result.source == ClassificationSource.model else "Rule-based classifier",
        "safety_notes": safety_signals(result, text),
    }
