from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app import demo_store
from app.errors import graph_api_error
from app.main import app
from app.routers import sync as sync_router
from app.services import calendar_service, sync_service
from app.services.graph_service import GraphServiceError

client = TestClient(app)


def _demo_headers() -> dict[str, str]:
    response = client.post("/api/demo/session")
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_demo_sync_and_calendar_routes_connect_to_the_existing_feed(monkeypatch) -> None:
    def no_graph(*args, **kwargs):
        raise AssertionError("demo mode must not call Microsoft Graph")

    monkeypatch.setattr(sync_service, "list_recent_messages", no_graph)
    monkeypatch.setattr(calendar_service, "create_event", no_graph)
    headers = _demo_headers()

    first_sync = client.post("/api/sync", headers=headers)
    assert first_sync.status_code == 200
    assert first_sync.json()["imported"] > 0
    assert first_sync.json()["fetched"] == first_sync.json()["imported"]

    second_sync = client.post("/api/sync", headers=headers)
    assert second_sync.status_code == 200
    assert second_sync.json()["unchanged"] == first_sync.json()["fetched"]

    item = client.get("/api/opportunities?limit=1", headers=headers).json()["items"][0]
    payload = {
        "opportunity_id": item["id"],
        "confirmed": True,
        "all_day": False,
        "start": "2026-11-19T15:00:00-05:00",
        "end": "2026-11-19T16:00:00-05:00",
        "time_zone": "America/New_York",
    }
    created = client.post("/api/calendar/events", headers=headers, json=payload)
    replay = client.post("/api/calendar/events", headers=headers, json=payload)
    assert created.status_code == 201
    assert replay.status_code == 200
    assert created.json()["simulated"] is True
    assert created.json()["id"] == replay.json()["id"]
    assert created.json()["web_link"] is None


def test_live_sync_classifies_graph_messages_and_upserts_stable_opportunity(monkeypatch) -> None:
    user_id = f"tenant:{uuid4()}"
    demo_store.feed_items[:] = [row for row in demo_store.feed_items if row.get("user_id") != user_id]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    rows = [{
        "id": "immutable-graph-message-id",
        "subject": "Software Engineering Internship Applications Open",
        "sender": "careers@example.edu",
        "received_at": "2026-11-13T15:00:00Z",
        "body_preview": "Apply for the software engineering internship by December 1.",
        "source_link": "https://outlook.office365.com/owa/?itemid=mail-item",
    }]
    monkeypatch.setattr(sync_service, "list_recent_messages", lambda assertion, limit: rows)
    user = {"sub": user_id, "mode": "live", "_assertion": "validated-test-assertion"}

    first = sync_service.sync_user(user)
    saved = [row for row in demo_store.feed_items if row.get("user_id") == user_id]
    second = sync_service.sync_user(user)

    assert first == {"fetched": 1, "imported": 1, "unchanged": 0, "skipped": 0, "failed": 0}
    assert second == {"fetched": 1, "imported": 0, "unchanged": 1, "skipped": 0, "failed": 0}
    assert len(saved) == 1
    assert saved[0]["message_id"] == "immutable-graph-message-id"
    assert saved[0]["category"] == "internship"
    assert saved[0]["source_link"] == rows[0]["source_link"]
    assert "body_preview" not in saved[0]


def test_live_calendar_replay_reuses_transaction_id(monkeypatch) -> None:
    user_id = f"tenant:{uuid4()}"
    opportunity_id = str(uuid4())
    demo_store.feed_items.append({
        "id": opportunity_id,
        "user_id": user_id,
        "title": "Confirmed internship event",
        "summary": "A test event.",
        "location": "McNair Hall",
        "calendar_status": "not_added",
    })
    calls: list[str] = []

    def fake_graph(assertion, event, transaction_id):
        calls.append(transaction_id)
        return {"graph_event_id": "graph-event-id", "web_link": "https://outlook.office365.com/calendar/item/graph-event-id", "status": "added"}

    monkeypatch.setattr(calendar_service, "create_event", fake_graph)
    user = {"sub": user_id, "mode": "live", "_assertion": "validated-test-assertion"}
    args = (user, opportunity_id, True, False, "2026-11-19T15:00:00-05:00", "2026-11-19T16:00:00-05:00", "America/New_York")

    created, is_new = calendar_service.create_calendar_event(*args)
    replay, is_replay_new = calendar_service.create_calendar_event(*args)

    assert is_new is True
    assert is_replay_new is False
    assert created == replay
    assert created["id"] == "graph-event-id"
    assert created["web_link"].startswith("https://outlook.office365.com/")
    assert len(calls) == 1
    assert calls[0] == demo_store.calendar_events[(user_id, opportunity_id)]["transaction_id"]


def test_sync_route_returns_retry_after_in_the_shared_api_error_shape(monkeypatch) -> None:
    headers = _demo_headers()

    def throttled(user):
        raise GraphServiceError("graph_throttled", "Microsoft Graph is temporarily throttling requests", 429, retry_after=12)

    monkeypatch.setattr(sync_router, "sync_user", throttled)
    response = client.post("/api/sync", headers=headers)
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "12"
    assert set(response.json()["error"]) == {"code", "message", "request_id"}


def test_claims_challenge_mapping_does_not_expose_raw_vendor_text() -> None:
    error = GraphServiceError(
        "graph_claims_challenge",
        "Microsoft requires additional account verification",
        403,
        '{"access_token":{"essential":true}}',
    )
    mapped = graph_api_error(error)
    assert mapped.status_code == 403
    assert mapped.message == "Microsoft requires additional account verification"
    assert "Bearer claims=\"" in mapped.headers["WWW-Authenticate"]
    assert "essential" not in mapped.headers["WWW-Authenticate"]
