"""Graph inbox synchronization into the existing classifier and feed shape.

The current backend scaffold stores feed rows in process memory. This adapter
keeps the same boundary as the demo implementation; a database repository can
replace the storage section without changing the Graph or classifier flow.
"""

from __future__ import annotations

from threading import Lock
from typing import Any

from app import demo_store
from app.schemas.classification import NormalizedMessage, Preferences
from app.services.ai_classifier import classify_email, content_hash, provider_from_env
from app.services.demo_feed import build_demo_feed, opportunity_id
from app.services.ranking_service import rank_tags
from app.services.graph_service import GraphServiceError, list_recent_messages
from app.schemas.classification import ClassifiedMessage

MAX_MODEL_CALLS_PER_SYNC = 10
_CANDIDATE_TERMS = (
    "intern", "scholarship", "fellowship", "research", "opportunity", "deadline",
    "apply", "application", "career", "job fair", "speaker", "workshop", "seminar",
    "event", "registration", "advising", "conference", "grant", "campus alert",
    "emergency", "lockdown", "evacuat", "tornado", "severe weather", "aggie alert",
)
_lock_guard = Lock()
_user_locks: dict[str, Lock] = {}


def _lock_for(user_id: str) -> Lock:
    with _lock_guard:
        return _user_locks.setdefault(user_id, Lock())


def _is_candidate(message: dict[str, Any]) -> bool:
    text = f"{message.get('subject', '')} {message.get('body_preview', '')}".casefold()
    return any(term in text for term in _CANDIDATE_TERMS)


def _as_iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _to_feed_row(user_id: str, message: NormalizedMessage, result: ClassifiedMessage, preferences: Preferences, previous: dict | None) -> dict:
    classification = result.classification
    rank = rank_tags(classification.tags, preferences)
    return {
        "id": previous["id"] if previous else opportunity_id(user_id, message.id),
        "title": classification.title,
        "summary": classification.summary,
        "category": classification.category.value,
        "priority": result.priority.value,
        "relevance_score": rank.relevance_score,
        "relevance_reason": rank.relevance_reason,
        "source_link": message.source_link,
        "event_start": _as_iso(classification.event_start),
        "event_end": _as_iso(classification.event_end),
        "deadline_at": _as_iso(classification.deadline_at),
        "deadline_date": _as_iso(classification.deadline_date),
        "location": classification.location,
        "needs_review": result.needs_review,
        "saved": previous.get("saved", False) if previous else False,
        "calendar_status": previous.get("calendar_status", "not_added") if previous else "not_added",
        # Internal metadata only; demo_feed.to_public removes it from responses.
        "user_id": user_id,
        "message_id": message.id,
        "graph_message_id": message.id,
        "tags": list(classification.tags),
        "received_at": result.received_at.isoformat(),
        "verified_source": result.verified_source,
        "confidence": classification.confidence,
        "classification_source": result.source.value,
        "classifier_version": result.classifier_version,
        "content_hash": result.content_hash,
        "_classification": result,
    }


def sync_user(user: dict) -> dict[str, int]:
    """Sync one verified user's inbox or refresh the synthetic feed in demo mode."""
    user_id = str(user["sub"])
    if user.get("mode") == "demo":
        with demo_store.seed_lock:
            existing = [row for row in demo_store.feed_items if row.get("user_id") == user_id]
            if not existing:
                existing = build_demo_feed(user_id, demo_store.profiles.get(user_id))
                demo_store.feed_items.extend(existing)
                return {"fetched": len(existing), "imported": len(existing), "unchanged": 0, "skipped": 0, "failed": 0}
            return {"fetched": len(existing), "imported": 0, "unchanged": len(existing), "skipped": 0, "failed": 0}

    assertion = user.get("_assertion")
    if not isinstance(assertion, str) or not assertion:
        raise GraphServiceError("invalid_assertion", "A validated user assertion is required", 401)
    lock = _lock_for(user_id)
    if not lock.acquire(blocking=False):
        raise GraphServiceError("sync_in_progress", "Inbox refresh is already running", 409)
    try:
        messages = list_recent_messages(assertion, limit=25)
        with demo_store.seed_lock:
            profile_data = demo_store.profiles.get(user_id, {})
            existing = [row for row in demo_store.feed_items if row.get("user_id") == user_id]
        preferences = Preferences(**profile_data)
        existing_by_message = {row.get("message_id"): row for row in existing}
        provider = provider_from_env()
        model_calls = 0
        counts = {"fetched": len(messages), "imported": 0, "unchanged": 0, "skipped": 0, "failed": 0}
        replacements: dict[str, dict] = {}

        for raw in messages:
            if not _is_candidate(raw):
                counts["skipped"] += 1
                continue
            try:
                message = NormalizedMessage.model_validate(raw)
                previous_row = existing_by_message.get(message.id)
                if previous_row and previous_row.get("content_hash") == content_hash(message):
                    counts["unchanged"] += 1
                    continue
                previous_result = previous_row.get("_classification") if previous_row else None
                selected_provider = provider if provider is not None and model_calls < MAX_MODEL_CALLS_PER_SYNC else None
                if selected_provider is not None:
                    model_calls += 1
                result = classify_email(message, provider=selected_provider, previous=previous_result)
                row = _to_feed_row(user_id, message, result, preferences, previous_row)
                replacements[message.id] = row
                counts["imported"] += 1
            except Exception:
                counts["failed"] += 1

        if replacements:
            with demo_store.seed_lock:
                new_rows = []
                for row in demo_store.feed_items:
                    if row.get("user_id") == user_id and row.get("message_id") in replacements:
                        replacement = replacements.pop(row["message_id"])
                        new_rows.append(replacement)
                    else:
                        new_rows.append(row)
                new_rows.extend(replacements.values())
                demo_store.feed_items[:] = new_rows
        return counts
    finally:
        lock.release()
