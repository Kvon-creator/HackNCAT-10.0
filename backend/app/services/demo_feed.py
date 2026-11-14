"""Demo-mode opportunity feed built from the shared synthetic fixtures (Dev 3).

Runs every message in demo/sample_emails.json through classify_email() and rank(),
and returns opportunity records shaped like Dev 4's ``Opportunity`` schema
(app/schemas/opportunity.py), sorted in feed order. No network or API key is
used in the default "canned" mode, so the demo cannot be broken by OpenAI limits.

Typical use in the backend (demo mode only):

    from app.services.demo_feed import build_demo_feed, rerank_feed, to_public

    items = build_demo_feed(user_id=claims["sub"], preferences=profile_or_None)
    # store items for that user; filter/paginate in the router
    return [to_public(x) for x in page]            # strip internal keys

    # after PUT /me/preferences:
    items = rerank_feed(items, new_preferences)     # rescore from stored tags, no reclassification

Python 3.9 compatible.
"""

import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.schemas.classification import NormalizedMessage, Preferences, Priority
from app.services.ai_classifier import CannedProvider, ClassificationProvider, classify_email
from app.services.ranking_service import feed_sort_key, rank_tags

# Fields of the public Opportunity contract, in contract order.
PUBLIC_FIELDS: Tuple[str, ...] = (
    "id",
    "title",
    "summary",
    "category",
    "priority",
    "relevance_score",
    "relevance_reason",
    "source_link",
    "event_start",
    "event_end",
    "deadline_at",
    "deadline_date",
    "location",
    "needs_review",
    "saved",
    "calendar_status",
)

# Extra keys kept on each record for scoping, reranking and storage. Never return
# these to the browser; use to_public().
INTERNAL_FIELDS: Tuple[str, ...] = (
    "user_id",
    "message_id",
    "tags",
    "received_at",
    "verified_source",
    "confidence",
    "classification_source",
    "classifier_version",
    "content_hash",
)

FIXTURES_ENV = "AGGIECONNECT_DEMO_FIXTURES"
_DEFAULT_FIXTURES = Path(__file__).resolve().parents[3] / "demo" / "sample_emails.json"
# Stable namespace so a user's opportunity IDs are the same on every rebuild.
_ID_NAMESPACE = uuid.UUID("6f1c2a7e-3b9d-4c55-9a0e-2d7f8b1e4c31")

_PREF_LIST_LIMIT = 20  # classification.Preferences bound; Dev 4's schema allows 50


def fixtures_path() -> Path:
    """demo/sample_emails.json, or the path in AGGIECONNECT_DEMO_FIXTURES."""
    override = os.environ.get(FIXTURES_ENV)
    return Path(override) if override else _DEFAULT_FIXTURES


def load_demo_fixtures(path: Optional[Path] = None) -> Tuple[List[NormalizedMessage], Dict[str, Any]]:
    """Return (messages, canned model outputs keyed by message id)."""
    source = Path(path) if path else fixtures_path()
    data = json.loads(source.read_text(encoding="utf-8"))
    messages, outputs = [], {}
    for row in data["messages"]:
        messages.append(
            NormalizedMessage(
                id=row["id"],
                subject=row.get("subject", ""),
                body=row.get("body", ""),
                sender=row.get("sender"),
                received_at=row["received_at"],
                source_link=row.get("source_link"),
                verified_emergency_source=bool(row.get("verified_emergency_source", False)),
            )
        )
        if "model_output" in row:
            outputs[row["id"]] = row["model_output"]
    return messages, outputs


def coerce_preferences(preferences: Any) -> Preferences:
    """Accept None, a dict, this module's Preferences, or Dev 4's Preferences model."""
    if preferences is None:
        return Preferences()
    if isinstance(preferences, Preferences):
        return preferences
    if hasattr(preferences, "model_dump"):
        preferences = preferences.model_dump()
    data = dict(preferences)
    for key in ("interests", "organizations", "career_goals"):
        if isinstance(data.get(key), list):
            data[key] = data[key][:_PREF_LIST_LIMIT]
    for key, limit in (("major", 80), ("academic_level", 40)):
        if isinstance(data.get(key), str):
            data[key] = data[key][:limit]
    return Preferences(**data)


def opportunity_id(user_id: str, message_id: str) -> str:
    """Deterministic per-user UUID: stable across rebuilds, different for each user."""
    return str(uuid.uuid5(_ID_NAMESPACE, "%s:%s" % (user_id, message_id)))


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _sort(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        items,
        key=lambda x: feed_sort_key(
            Priority(x["priority"]),
            x["relevance_score"],
            datetime.fromisoformat(x["received_at"]),
            x["id"],
            x["verified_source"],
        ),
    )


def build_demo_feed(
    user_id: str,
    preferences: Any = None,
    mode: str = "canned",
    provider: Optional[ClassificationProvider] = None,
    fixtures: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Classify and rank the demo fixtures for one user, sorted in feed order.

    mode="canned"   replay recorded model outputs (default; no network)
    mode="fallback" rule-based classifier only
    ``provider``    overrides ``mode`` (for example a live OpenAIProvider)
    """
    if not user_id:
        raise ValueError("user_id is required")
    prefs = coerce_preferences(preferences)
    messages, outputs = load_demo_fixtures(fixtures)
    if provider is None:
        if mode == "canned":
            provider = CannedProvider(outputs)
        elif mode != "fallback":
            raise ValueError("mode must be 'canned' or 'fallback' (or pass provider=)")

    items = []
    for message in messages:
        result = classify_email(message, provider=provider)
        cls = result.classification
        ranked = rank_tags(cls.tags, prefs)
        items.append(
            {
                "id": opportunity_id(user_id, message.id),
                "title": cls.title,
                "summary": cls.summary,
                "category": cls.category.value,
                "priority": result.priority.value,
                "relevance_score": ranked.relevance_score,
                "relevance_reason": ranked.relevance_reason,
                "source_link": message.source_link,
                "event_start": _iso(cls.event_start),
                "event_end": _iso(cls.event_end),
                "deadline_at": _iso(cls.deadline_at),
                "deadline_date": _iso(cls.deadline_date),
                "location": cls.location,
                "needs_review": result.needs_review,
                "saved": False,
                "calendar_status": "not_added",
                # internal
                "user_id": user_id,
                "message_id": message.id,
                "tags": list(cls.tags),
                "received_at": _iso(result.received_at),
                "verified_source": result.verified_source,
                "confidence": cls.confidence,
                "classification_source": result.source.value,
                "classifier_version": result.classifier_version,
                "content_hash": result.content_hash,
            }
        )
    return _sort(items)


def rerank_feed(items: Iterable[Dict[str, Any]], preferences: Any) -> List[Dict[str, Any]]:
    """Recompute relevance from stored tags for new preferences and re-sort.

    Returns new dicts; saved and calendar_status are preserved. No reclassification.
    """
    prefs = coerce_preferences(preferences)
    updated = []
    for item in items:
        ranked = rank_tags(item.get("tags", []), prefs)
        row = dict(item)
        row["relevance_score"] = ranked.relevance_score
        row["relevance_reason"] = ranked.relevance_reason
        updated.append(row)
    return _sort(updated)


def to_public(item: Dict[str, Any]) -> Dict[str, Any]:
    """Only the Opportunity contract fields, safe to return from the API."""
    return {key: item.get(key) for key in PUBLIC_FIELDS}
