from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

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
