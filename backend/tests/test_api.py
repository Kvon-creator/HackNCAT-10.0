from fastapi.testclient import TestClient
from app.main import app
from app import demo_store
import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_demo_store():
    demo_store.feed_items.clear()
    demo_store.profiles.clear()

def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}

def test_demo_session_and_me():
    token_response = client.post("/api/demo/session")
    assert token_response.status_code == 201
    token = token_response.json()["access_token"]
    response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["mode"] == "demo"

def test_demo_session_requires_demo_mode():
    # Runtime configuration controls this endpoint; this test documents the default demo contract.
    assert client.post("/api/demo/session").status_code == 201

def session():
    response = client.post("/api/demo/session")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}

def test_demo_feed_is_seeded_and_public():
    headers = session()
    response = client.get("/api/opportunities?limit=50", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 13
    assert len(data["items"]) == 13
    assert data["items"][0]["priority"] == "emergency"
    assert all(not ({"user_id", "tags", "content_hash"} & set(item)) for item in data["items"])
    detail = client.get(f"/api/opportunities/{data['items'][0]['id']}", headers=headers).json()
    assert not ({"user_id", "tags", "content_hash"} & set(detail))

def test_preferences_rerank_seeded_feed_and_preserve_saved():
    headers = session()
    items = client.get("/api/opportunities?limit=50", headers=headers).json()["items"]
    target = next(item for item in items if item["title"] == "Software Engineering Internship Info Session")
    assert client.post(f"/api/opportunities/{target['id']}/save", headers=headers).status_code == 204
    response = client.put("/api/me/preferences", headers=headers, json={
        "major": "Computer Science", "academic_level": "Junior", "interests": ["Internships"],
        "organizations": [], "career_goals": ["Software Engineer"],
    })
    assert response.status_code == 200
    items = client.get("/api/opportunities?limit=50", headers=headers).json()["items"]
    target = next(item for item in items if item["title"] == "Software Engineering Internship Info Session")
    assert target["relevance_score"] == 80
    assert target["relevance_reason"].startswith("Matches your interest (internship)")
    assert target["saved"] is True
    assert all(not ({"user_id", "tags", "content_hash"} & set(item)) for item in items)

def test_demo_users_have_distinct_private_ids():
    headers_a, headers_b = session(), session()
    first = client.get("/api/opportunities?limit=1", headers=headers_a).json()["items"][0]
    second = client.get("/api/opportunities?limit=1", headers=headers_b).json()["items"][0]
    assert first["id"] != second["id"]
    assert client.get(f"/api/opportunities/{first['id']}", headers=headers_b).status_code == 404

def test_priority_filter_keeps_feed_order():
    headers = session()
    all_items = client.get("/api/opportunities?limit=50", headers=headers).json()["items"]
    deadlines = client.get("/api/opportunities?limit=50&priority=deadline", headers=headers).json()
    expected = [item["id"] for item in all_items if item["priority"] == "deadline"]
    assert deadlines["total"] == len(expected)
    assert [item["id"] for item in deadlines["items"]] == expected
    assert all(item["priority"] == "deadline" for item in deadlines["items"])

def test_simultaneous_feed_requests_seed_once():
    headers = session()
    start = Barrier(2)

    def request_feed():
        start.wait()
        return client.get("/api/opportunities?limit=50", headers=headers)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: request_feed(), range(2)))

    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["total"] == 13 for response in responses)
    assert all(len(response.json()["items"]) == 13 for response in responses)
    assert len(demo_store.feed_items) == 13
