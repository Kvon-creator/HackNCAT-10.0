from __future__ import annotations

import httpx
import pytest

from app.services import graph_service as graph
ORIGINAL_CLIENT = httpx.Client


@pytest.fixture(autouse=True)
def fake_obo(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if request.node.name == "test_distinguishes_obo_claims_challenge_and_expired_assertion":
        return
    monkeypatch.setattr(graph, "_get_obo_token", lambda assertion, scopes: "test-graph-token")


def use_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs):
        return ORIGINAL_CLIENT(transport=transport, **kwargs)

    monkeypatch.setattr(graph.httpx, "Client", client_factory)


def test_reads_pages_with_immutable_ids_and_normalized_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json={
                "value": [{"id": "immutable-1", "subject": "Internship", "from": {"emailAddress": {"address": "career@example.edu"}}, "receivedDateTime": "2026-11-13T15:00:00Z", "bodyPreview": "Apply now", "webLink": "https://outlook.office.com/mail/item"}],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skiptoken=abc",
            })
        return httpx.Response(200, json={"value": [{"id": "immutable-2", "subject": "Speaker"}]})

    use_transport(monkeypatch, handler)
    result = graph.list_recent_messages("validated-assertion", limit=2)

    assert [item["id"] for item in result] == ["immutable-1", "immutable-2"]
    assert result[0]["sender"] == "career@example.edu"
    assert result[0]["source_link"] == "https://outlook.office.com/mail/item"
    assert calls[0].headers["Prefer"] == 'IdType="ImmutableId"'
    assert calls[0].url.params["$top"] == "2"
    assert len(calls) == 2


def test_rejects_wrong_paging_host_before_following_it(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={
            "value": [{"id": "one"}],
            "@odata.nextLink": "https://attacker.example/v1.0/me/messages?$skiptoken=secret",
        })

    use_transport(monkeypatch, handler)
    with pytest.raises(graph.GraphServiceError) as exc:
        graph.list_recent_messages("validated-assertion", limit=2)
    assert exc.value.code == "graph_invalid_paging_link"
    assert calls == 1
    assert "attacker.example" not in str(exc.value)


def test_retries_retry_after_within_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    sleeps: list[float] = []
    monkeypatch.setattr(graph.time, "sleep", sleeps.append)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"value": [{"id": "ok"}]})

    use_transport(monkeypatch, handler)
    assert graph.list_recent_messages("validated-assertion", limit=1)[0]["id"] == "ok"
    assert calls == 2
    assert sleeps == [1.0]


def test_sanitizes_consent_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {"message": "contains private vendor details"}})

    use_transport(monkeypatch, handler)
    with pytest.raises(graph.GraphServiceError) as exc:
        graph.list_recent_messages("validated-assertion")
    assert exc.value.code == "graph_consent_required"
    assert "private vendor details" not in str(exc.value)
    assert exc.value.status_code == 403


def test_distinguishes_obo_claims_challenge_and_expired_assertion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant")
    monkeypatch.setenv("ENTRA_API_CLIENT_ID", "client")
    monkeypatch.setenv("ENTRA_API_CLIENT_SECRET", "secret")

    class FakeApplication:
        result: dict

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def acquire_token_on_behalf_of(self, **kwargs):
            return self.result

    monkeypatch.setattr(graph.msal, "ConfidentialClientApplication", FakeApplication)
    FakeApplication.result = {"error": "insufficient_claims", "claims": "encoded-claims-challenge"}
    with pytest.raises(graph.GraphServiceError) as challenge:
        graph._get_obo_token("validated-assertion", ["graph-scope"])
    assert challenge.value.code == "graph_claims_challenge"
    assert challenge.value.claims == "encoded-claims-challenge"

    FakeApplication.result = {"error": "invalid_grant"}
    with pytest.raises(graph.GraphServiceError) as expired:
        graph._get_obo_token("expired-assertion", ["graph-scope"])
    assert expired.value.code == "invalid_assertion"
    assert expired.value.status_code == 401


def test_preserves_transaction_id_and_converts_dst_boundary_to_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[dict] = []
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        payload = __import__("json").loads(request.content)
        posted.append(payload)
        if request_count == 1:
            # The retry uses exactly the same Graph transaction ID and payload.
            raise httpx.ReadTimeout("simulated timeout", request=request)
        return httpx.Response(201, json={"id": "event-1", "webLink": "https://outlook.office.com/calendar/item"})

    use_transport(monkeypatch, handler)
    monkeypatch.setattr(graph.time, "sleep", lambda _: None)
    event = {
        "confirmed": True,
        "subject": "DST review",
        "all_day": False,
        "start": "2026-11-01T01:30:00-04:00",
        "end": "2026-11-01T01:30:00-05:00",
        "time_zone": "America/New_York",
    }
    result = graph.create_event("validated-assertion", event, "stable-transaction-id")
    assert result["graph_event_id"] == "event-1"
    assert request_count == 2
    assert posted[0] == posted[1]
    assert posted[0]["transactionId"] == "stable-transaction-id"
    assert posted[0]["start"]["dateTime"] == "2026-11-01T05:30:00"
    assert posted[0]["end"]["dateTime"] == "2026-11-01T06:30:00"
    assert posted[0]["start"]["timeZone"] == posted[0]["end"]["timeZone"] == "UTC"


def test_all_day_end_is_exclusive_and_unconfirmed_writes_are_rejected() -> None:
    payload = graph._calendar_payload({
        "all_day": True,
        "start": "2026-11-19",
        "end": "2026-11-20",
        "time_zone": "America/New_York",
    }, "stable")
    assert payload["start"]["dateTime"] == "2026-11-19T00:00:00"
    assert payload["end"]["dateTime"] == "2026-11-20T00:00:00"
    assert payload["isAllDay"] is True
    with pytest.raises(ValueError, match="confirmed"):
        graph.create_event("validated-assertion", {"confirmed": False}, "stable")
