from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "integrations" in body
    # Keys must never be leaked, only booleans.
    assert all(isinstance(v, bool) for v in body["integrations"].values())
