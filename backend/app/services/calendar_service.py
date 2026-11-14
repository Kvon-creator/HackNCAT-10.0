"""Calendar write recovery around the Graph adapter.

The starter repository has no database repository yet, so pending writes are
kept in the existing process-local store. The transaction ID is retained across
retries in that store and can move to the calendar_events table with Dev 4's
repository implementation.
"""

from __future__ import annotations

import hashlib
import json
from threading import Lock
from uuid import uuid4

from app import demo_store
from app.errors import ApiError, graph_api_error
from app.services.graph_service import GraphServiceError, _calendar_payload, create_event

_event_lock_guard = Lock()
_event_locks: dict[tuple[str, str], Lock] = {}


def _lock_for(key: tuple[str, str]) -> Lock:
    with _event_lock_guard:
        return _event_locks.setdefault(key, Lock())


def create_calendar_event(user: dict, opportunity_id: str, confirmed: bool, all_day: bool, start: str, end: str, time_zone: str) -> tuple[dict, bool]:
    if confirmed is not True:
        raise ApiError(422, "confirmation_required", "Confirm the event before adding it to Outlook")
    user_id = str(user["sub"])
    key = (user_id, opportunity_id)
    lock = _lock_for(key)
    if not lock.acquire(blocking=False):
        raise ApiError(409, "calendar_write_in_progress", "This calendar event is already being processed")

    try:
        with demo_store.seed_lock:
            opportunity = next((row for row in demo_store.feed_items if row.get("id") == opportunity_id and row.get("user_id") == user_id), None)
            if opportunity is None:
                raise ApiError(404, "not_found", "Opportunity not found")
            payload = {
                "opportunity_id": opportunity_id,
                "confirmed": True,
                "all_day": all_day,
                "start": start,
                "end": end,
                "time_zone": time_zone,
                "title": opportunity.get("title", "AggieConnect event"),
                "summary": opportunity.get("summary", ""),
                "location": opportunity.get("location"),
            }
            try:
                _calendar_payload(payload, "validation-only")
            except ValueError:
                raise ApiError(422, "invalid_calendar_event", "The event time or time zone is invalid") from None
            payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            record = demo_store.calendar_events.get(key)
            if record and record["payload_hash"] != payload_hash:
                raise ApiError(409, "calendar_conflict", "A different calendar event was already confirmed for this opportunity")
            if record and record["state"] == "added":
                return {
                    "id": record["graph_event_id"],
                    "status": "added",
                    "web_link": record["web_link"],
                    "simulated": record["simulated"],
                }, False
            created = record is None
            if record is None:
                record = {
                    "transaction_id": str(uuid4()),
                    "payload_hash": payload_hash,
                    "graph_event_id": None,
                    "web_link": None,
                    "simulated": user.get("mode") == "demo",
                    "state": "pending",
                }
                demo_store.calendar_events[key] = record

        if user.get("mode") == "demo":
            result = {
                "graph_event_id": f"demo-{uuid4()}",
                "web_link": None,
                "status": "added",
            }
        else:
            assertion = user.get("_assertion")
            if not isinstance(assertion, str) or not assertion:
                raise ApiError(401, "invalid_assertion", "A validated user assertion is required")
            try:
                result = create_event(assertion, payload, record["transaction_id"])
            except GraphServiceError as error:
                raise graph_api_error(error) from None
            except ValueError:
                raise ApiError(422, "invalid_calendar_event", "The event time or time zone is invalid") from None

        with demo_store.seed_lock:
            record.update({
                "graph_event_id": result["graph_event_id"],
                "web_link": result["web_link"],
                "state": "added",
            })
            for row in demo_store.feed_items:
                if row.get("id") == opportunity_id and row.get("user_id") == user_id:
                    row["calendar_status"] = "added"
                    break
        return {
            "id": result["graph_event_id"],
            "status": "added",
            "web_link": result["web_link"],
            "simulated": user.get("mode") == "demo",
        }, created
    finally:
        lock.release()
